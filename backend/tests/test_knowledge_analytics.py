from datetime import datetime
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin_routes import router as admin_router
from app.auth_dependencies import get_current_user
from app.database import Base, get_db
from app.models import (Chunk, DocumentVersion, RetrievalRequest, RetrievalResult,
                        SourceDocument, User)


class KnowledgeAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.admin = self.user("Admin", "admin@example.com", "admin")
        self.agent = self.user("Agent", "agent@example.com", "agent")
        self.other = self.user("Other", "other@example.com", "agent")
        self.a = self.chunk(1, 10, "Article A", "KB-A", "a::1")
        self.b = self.chunk(2, 20, "Article B", "KB-B", "b::1")
        old = self.request(self.agent, " How   now? ", "2026-01-01T10:00:00", "search")
        self.result(old, self.a, .4, 1)
        one = self.request(self.agent, "how now?", "2026-01-02T10:00:00", "search")
        self.result(one, self.a, .8, 2)
        self.result(one, self.b, .6, 1)
        two = self.request(self.other, "  HOW  NOW? ", "2026-01-02T11:00:00", "chat")
        self.result(two, self.a, .3, 1)
        self.zero = self.request(self.agent, "New question", "2026-01-02T12:00:00",
                                 "keyword_search")
        self.document(10, "used.docx", 10)
        self.document(30, "unused.docx", 30)
        self.app = FastAPI()
        self.app.include_router(admin_router, prefix="/api/v1")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def user(self, name, email, role):
        value = User(full_name=name, email=email, role=role, is_active=True,
                     password_hash="secret-hash")
        self.db.add(value); self.db.commit(); self.db.refresh(value)
        return value

    def chunk(self, chunk_id, version_id, title, code, external):
        value = Chunk(chunk_id=chunk_id, sheet_id=1, version_id=version_id,
                      chunk_text="text", chunk_index=chunk_id, chunk_type="article",
                      metadata_json={"article_title": title, "kb_code": code,
                                     "external_chunk_id": external,
                                     "section_title": "Section", "priority": "high"})
        self.db.add(value); self.db.commit()
        return value

    def request(self, user, query, timestamp, search_type):
        value = RetrievalRequest(message_id=1, user_id=user.user_id, query_text=query,
                                 top_k=5, created_at=datetime.fromisoformat(timestamp),
                                 retriever_config_json={"interaction_type": search_type})
        self.db.add(value); self.db.commit(); self.db.refresh(value)
        return value

    def result(self, request, chunk, score, rank):
        self.db.add(RetrievalResult(retrieval_id=request.retrieval_id,
                                    chunk_id=chunk.chunk_id,
                                    similarity_score=score, rank=rank))
        self.db.commit()

    def document(self, document_id, filename, version_id):
        doc = SourceDocument(document_id=document_id, kb_id=1, department_id=1,
                             file_name=filename, file_type="docx", current_version_id=version_id)
        version = DocumentVersion(version_id=version_id, document_id=document_id,
                                  version_number=1, is_current=True)
        self.db.add_all([doc, version]); self.db.commit()

    def url(self, suffix):
        return f"/api/v1/admin/analytics/knowledge/{suffix}"

    def test_access_control_on_all_routes(self):
        paths = ["trending-questions", "low-confidence", "score-distribution",
                 "articles", "unreferenced-content", f"retrievals/{self.zero.retrieval_id}"]
        self.app.dependency_overrides[get_current_user] = lambda: self.agent
        for path in paths:
            self.assertEqual(self.client.get(self.url(path)).status_code, 403)
        del self.app.dependency_overrides[get_current_user]
        for path in paths:
            self.assertEqual(self.client.get(self.url(path)).status_code, 401)

    def test_trending_normalization_previous_period_and_filters(self):
        body = self.client.get(self.url("trending-questions"), params={
            "date_from": "2026-01-02", "date_to": "2026-01-02"
        }).json()
        item = next(item for item in body["items"]
                    if item["normalized_question"] == "how now?")
        self.assertEqual((item["current_count"], item["previous_count"]), (2, 1))
        self.assertEqual(item["absolute_change"], 1)
        self.assertEqual(item["percentage_change"], 100)
        new = next(item for item in body["items"]
                   if item["normalized_question"] == "new question")
        self.assertIsNone(new["percentage_change"])
        filtered = self.client.get(self.url("trending-questions"),
                                   params={"search_type": "chat"}).json()
        self.assertEqual(filtered["items"][0]["current_count"], 1)

    def test_low_confidence_zero_threshold_pagination_and_secret_safety(self):
        body = self.client.get(self.url("low-confidence"),
                               params={"threshold": .5}).json()
        reasons = {item["low_confidence_reason"] for item in body["items"]}
        self.assertEqual(reasons, {"zero_results", "top_score_below_threshold"})
        self.assertNotIn("password", str(body).lower())
        without_zero = self.client.get(self.url("low-confidence"), params={
            "threshold": .5, "include_zero_results": False,
            "page": 1, "page_size": 1,
        }).json()
        self.assertEqual(without_zero["total"], 2)
        self.assertEqual(len(without_zero["items"]), 1)

    def test_score_distribution_bases_clamping_percentages_and_empty(self):
        top = self.client.get(self.url("score-distribution"),
                              params={"bucket_size": .2}).json()
        self.assertEqual(top["total"], 3)
        self.assertAlmostEqual(sum(item["percentage"] for item in top["buckets"]), 100)
        all_results = self.client.get(self.url("score-distribution"), params={
            "bucket_size": .2, "score_basis": "all_results"}).json()
        self.assertEqual(all_results["total"], 4)
        empty = self.client.get(self.url("score-distribution"),
                                params={"date_from": "2030-01-01"}).json()
        self.assertEqual(empty["total"], 0)
        self.assertTrue(all(item["count"] == 0 for item in empty["buckets"]))

    def test_article_ranking_search_and_date_filter(self):
        body = self.client.get(self.url("articles")).json()
        self.assertEqual(body["items"][0]["article_title"], "Article A")
        self.assertEqual(body["items"][0]["consultation_count"], 3)
        searched = self.client.get(self.url("articles"), params={"search": " kb-b "}).json()
        self.assertEqual([item["kb_code"] for item in searched["items"]], ["KB-B"])

    def test_unreferenced_relational_period_logic_and_search(self):
        global_body = self.client.get(self.url("unreferenced-content")).json()
        self.assertEqual([item["filename"] for item in global_body["items"]], ["unused.docx"])
        period = self.client.get(self.url("unreferenced-content"), params={
            "date_from": "2030-01-01", "search": "used"}).json()
        self.assertEqual(period["total"], 2)
        self.assertEqual(period["scope_label"], "unreferenced_in_selected_period")

    def test_drill_down_ordering_not_found_and_no_secrets(self):
        retrieval_id = self.db.query(RetrievalRequest).filter_by(query_text="how now?").one().retrieval_id
        response = self.client.get(self.url(f"retrievals/{retrieval_id}"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([item["rank"] for item in body["results"]], [1, 2])
        self.assertEqual(body["results"][0]["chunk_external_id"], "b::1")
        self.assertNotIn("hash", str(body).lower())
        self.assertEqual(self.client.get(self.url("retrievals/99999")).status_code, 404)

    def test_validation_failures(self):
        cases = [
            ("trending-questions", {"limit": 0}),
            ("low-confidence", {"threshold": 1.1}),
            ("score-distribution", {"bucket_size": .3}),
            ("score-distribution", {"score_basis": "median"}),
            ("articles", {"sort_by": "query"}),
            ("articles", {"sort_order": "sideways"}),
            ("articles", {"role": "developer"}),
            ("articles", {"search_type": "semantic"}),
            ("unreferenced-content", {"page_size": 101}),
            ("unreferenced-content", {"date_from": "2026-02-01", "date_to": "2026-01-01"}),
        ]
        for path, params in cases:
            with self.subTest(path=path, params=params):
                self.assertEqual(self.client.get(self.url(path), params=params).status_code, 422)


if __name__ == "__main__":
    unittest.main()

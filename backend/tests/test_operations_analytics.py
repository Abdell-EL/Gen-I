from __future__ import annotations

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
from app.models import Chunk, RetrievalRequest, RetrievalResult, User


class OperationsAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.admin = self.add_user("Admin", "admin@example.com", "admin")
        self.agent = self.add_user("Agent", "agent@example.com", "agent")
        self.other_agent = self.add_user("Other", "other@example.com", "agent")
        self.article_a = self.add_chunk(101, "Article A", "KB-A")
        self.article_b = self.add_chunk(102, "Article B", "KB-B")

        first = self.add_request(
            self.agent, "  How   to Close? ", "2026-01-05T10:15:00", "search"
        )
        self.add_result(first, self.article_a, 0.80, 1)
        self.add_result(first, self.article_b, 0.60, 2)
        second = self.add_request(
            self.agent, "how to close?", "2026-01-05T11:30:00", "keyword_search"
        )
        self.add_result(second, self.article_a, 0.40, 1)
        third = self.add_request(
            self.other_agent, "Another question", "2026-01-06T09:00:00", "chat"
        )
        self.add_result(third, self.article_a, 0.90, 1)
        self.add_request(
            self.admin, "No mapped chunks", "2026-02-02T12:00:00", "search"
        )

        self.app = FastAPI()
        self.app.include_router(admin_router, prefix="/api/v1")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def add_user(self, name, email, role):
        user = User(
            full_name=name,
            email=email,
            role=role,
            is_active=True,
            password_hash="unused",
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def add_chunk(self, chunk_id, article_title, kb_code):
        chunk = Chunk(
            chunk_id=chunk_id,
            sheet_id=1,
            version_id=1,
            chunk_text=f"Text for {article_title}",
            chunk_index=chunk_id,
            metadata_json={"article_title": article_title, "kb_code": kb_code},
        )
        self.db.add(chunk)
        self.db.commit()
        return chunk

    def add_request(self, user, query, created_at, interaction_type):
        request = RetrievalRequest(
            message_id=1,
            user_id=user.user_id,
            query_text=query,
            top_k=5,
            retriever_config_json={"interaction_type": interaction_type},
            created_at=datetime.fromisoformat(created_at),
        )
        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return request

    def add_result(self, request, chunk, score, rank):
        self.db.add(
            RetrievalResult(
                retrieval_id=request.retrieval_id,
                chunk_id=chunk.chunk_id,
                similarity_score=score,
                rank=rank,
            )
        )
        self.db.commit()

    def get_summary(self, **params):
        return self.client.get(
            "/api/v1/admin/analytics/operations/summary", params=params
        )

    def test_admin_access_agent_forbidden_and_missing_token_unauthorized(self):
        self.assertEqual(self.get_summary().status_code, 200)
        self.app.dependency_overrides[get_current_user] = lambda: self.agent
        self.assertEqual(self.get_summary().status_code, 403)
        del self.app.dependency_overrides[get_current_user]
        self.assertEqual(self.get_summary().status_code, 401)

    def test_invalid_filters_return_422(self):
        for path in ("summary", "question-volume"):
            base = f"/api/v1/admin/analytics/operations/{path}"
            with self.subTest(path=path, kind="date"):
                response = self.client.get(
                    base, params={"date_from": "2026-02-02", "date_to": "2026-01-01"}
                )
                self.assertEqual(response.status_code, 422)
            with self.subTest(path=path, kind="role"):
                self.assertEqual(
                    self.client.get(base, params={"role": "developer"}).status_code,
                    422,
                )
            with self.subTest(path=path, kind="search_type"):
                self.assertEqual(
                    self.client.get(base, params={"search_type": "semantic"}).status_code,
                    422,
                )

    def test_summary_totals_averages_and_confidence_counts(self):
        body = self.get_summary().json()
        self.assertEqual(body["total_questions"], 4)
        self.assertEqual(body["unique_users"], 3)
        self.assertEqual(body["active_users"], 3)
        self.assertAlmostEqual(body["average_questions_per_active_user"], 4 / 3)
        self.assertAlmostEqual(body["average_results_count"], 1.0)
        self.assertAlmostEqual(body["average_top_score"], 0.7)
        self.assertEqual(body["low_confidence_questions"], 2)
        self.assertEqual(body["zero_result_questions"], 1)

    def test_summary_rankings_and_normalized_question(self):
        body = self.get_summary().json()
        self.assertEqual(body["most_active_user"]["user_id"], self.agent.user_id)
        self.assertEqual(body["most_active_user"]["questions_count"], 2)
        self.assertEqual(
            body["most_asked_question"],
            {
                "question": "How   to Close?",
                "normalized_question": "how to close?",
                "questions_count": 2,
            },
        )
        self.assertEqual(
            body["most_consulted_article"],
            {
                "article_title": "Article A",
                "kb_code": "KB-A",
                "references_count": 3,
            },
        )

    def test_summary_filters_user_role_and_interaction_type(self):
        cases = [
            ({"user_id": self.admin.user_id}, 1, 1),
            ({"role": "admin"}, 1, 1),
            ({"role": "agent"}, 3, 2),
            ({"search_type": "search"}, 2, 2),
            ({"search_type": "keyword_search"}, 1, 1),
            ({"search_type": "chat"}, 1, 1),
        ]
        for params, questions, users in cases:
            with self.subTest(params=params):
                body = self.get_summary(**params).json()
                self.assertEqual(body["total_questions"], questions)
                self.assertEqual(body["unique_users"], users)

    def test_filters_apply_to_question_volume(self):
        response = self.client.get(
            "/api/v1/admin/analytics/operations/question-volume",
            params={"role": "agent", "search_type": "search"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(item["questions_count"], item["unique_users"]) for item in response.json()["items"]],
            [(1, 1)],
        )

    def test_question_volume_groups_all_intervals_chronologically(self):
        expected = {
            "hour": [1, 1, 1, 1],
            "day": [2, 1, 1],
            "week": [3, 1],
            "month": [3, 1],
        }
        for interval, counts in expected.items():
            with self.subTest(interval=interval):
                response = self.client.get(
                    "/api/v1/admin/analytics/operations/question-volume",
                    params={"interval": interval},
                )
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["interval"], interval)
                self.assertEqual(
                    [item["questions_count"] for item in body["items"]], counts
                )
                starts = [item["period_start"] for item in body["items"]]
                self.assertEqual(starts, sorted(starts))

    def test_date_filters_are_inclusive_and_consistent(self):
        params = {"date_from": "2026-01-05", "date_to": "2026-01-05"}
        summary = self.get_summary(**params).json()
        volume = self.client.get(
            "/api/v1/admin/analytics/operations/question-volume", params=params
        ).json()
        self.assertEqual(summary["total_questions"], 2)
        self.assertEqual(sum(item["questions_count"] for item in volume["items"]), 2)

    def test_empty_data_returns_safe_zero_and_null_values(self):
        body = self.get_summary(date_from="2030-01-01").json()
        self.assertEqual(body["total_questions"], 0)
        self.assertEqual(body["unique_users"], 0)
        self.assertEqual(body["active_users"], 0)
        self.assertEqual(body["low_confidence_questions"], 0)
        self.assertEqual(body["zero_result_questions"], 0)
        for field in (
            "average_questions_per_active_user",
            "average_results_count",
            "average_top_score",
            "most_active_user",
            "most_asked_question",
            "most_consulted_article",
        ):
            self.assertIsNone(body[field])
        volume = self.client.get(
            "/api/v1/admin/analytics/operations/question-volume",
            params={"date_from": "2030-01-01"},
        ).json()
        self.assertEqual(volume["items"], [])


if __name__ == "__main__":
    unittest.main()

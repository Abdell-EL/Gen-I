from datetime import datetime
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.auth_dependencies import get_current_user
from app.database import Base, get_db
from app.feedback_routes import router
from app.models import (ChatMessage, ChatSession, Chunk, RetrievalRequest,
                        RetrievalResult, User)


class FeedbackWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine); self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.admin = self.user("Admin", "admin@x.test", "admin")
        self.agent = self.user("Agent", "agent@x.test", "agent")
        self.other = self.user("Other", "other@x.test", "agent")
        self.session = ChatSession(user_id=self.agent.user_id, created_at=datetime(2026, 1, 2))
        self.db.add(self.session); self.db.commit(); self.db.refresh(self.session)
        self.question = ChatMessage(session_id=self.session.session_id, role="user", content="Question", created_at=datetime(2026, 1, 2, 10))
        self.answer = ChatMessage(session_id=self.session.session_id, role="assistant", content="Generated answer", created_at=datetime(2026, 1, 2, 11))
        self.db.add_all([self.question, self.answer]); self.db.commit(); self.db.refresh(self.question); self.db.refresh(self.answer)
        chunk = Chunk(chunk_id=1, sheet_id=1, version_id=1, chunk_text="x", chunk_index=1,
                      metadata_json={"article_title": "Article A", "kb_code": "KB-A", "external_chunk_id": "a1"})
        retrieval = RetrievalRequest(message_id=self.question.message_id, user_id=self.agent.user_id,
                                     query_text="Question", created_at=datetime(2026, 1, 2, 10),
                                     retriever_config_json={"interaction_type": "chat"})
        self.db.add_all([chunk, retrieval]); self.db.commit(); self.db.refresh(retrieval)
        self.db.add_all([RetrievalResult(retrieval_id=retrieval.retrieval_id, chunk_id=1, similarity_score=.8, rank=2),
                         RetrievalResult(retrieval_id=retrieval.retrieval_id, chunk_id=1, similarity_score=.9, rank=1)])
        self.db.commit()
        app = FastAPI(); app.include_router(router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.agent
        self.app = app; self.client = TestClient(app)

    def tearDown(self):
        self.db.close(); Base.metadata.drop_all(self.engine); self.engine.dispose()

    def user(self, name, email, role):
        value = User(full_name=name, email=email, role=role, is_active=True, password_hash="secret")
        self.db.add(value); self.db.commit(); self.db.refresh(value); return value

    def path(self): return f"/api/v1/chat/messages/{self.answer.message_id}/feedback"

    def test_create_update_read_delete_and_validation(self):
        created = self.client.post(self.path(), json={"rating": "helpful"})
        self.assertEqual(created.status_code, 200); self.assertFalse(created.json()["was_updated"])
        self.assertNotIn("secret", str(created.json()).lower())
        invalid = self.client.post(self.path(), json={"rating": "not_helpful"})
        self.assertEqual(invalid.status_code, 422)
        other = self.client.post(self.path(), json={"rating": "partially_helpful", "reason": "other"})
        self.assertEqual(other.status_code, 422)
        updated = self.client.post(self.path(), json={"rating": "not_helpful", "reason": "incorrect_answer", "comment": " Fix "})
        self.assertTrue(updated.json()["was_updated"]); self.assertEqual(updated.json()["comment"], "Fix")
        self.assertEqual(self.client.get(self.path()).json()["rating"], "not_helpful")
        self.assertEqual(self.client.delete(self.path()).status_code, 204)
        self.assertEqual(self.client.get(self.path()).status_code, 404)

    def test_ownership_assistant_constraint_and_access(self):
        self.app.dependency_overrides[get_current_user] = lambda: self.other
        self.assertEqual(self.client.post(self.path(), json={"rating": "helpful"}).status_code, 403)
        self.assertEqual(self.client.get(self.path()).status_code, 404)
        self.app.dependency_overrides[get_current_user] = lambda: self.agent
        user_path = f"/api/v1/chat/messages/{self.question.message_id}/feedback"
        self.assertEqual(self.client.post(user_path, json={"rating": "helpful"}).status_code, 422)
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.assertEqual(self.client.post(self.path(), json={"rating": "helpful"}).status_code, 200)

    def test_admin_summary_listing_filters_and_drilldown(self):
        self.client.post(self.path(), json={"rating": "not_helpful", "reason": "incorrect_answer", "comment": "No"})
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        summary = self.client.get("/api/v1/admin/analytics/feedback/summary").json()
        self.assertEqual(summary["total_feedback"], 1); self.assertEqual(summary["negative_percentage"], 100)
        self.assertEqual(summary["most_affected_article"]["kb_code"], "KB-A")
        listing = self.client.get("/api/v1/admin/analytics/feedback", params={"rating": "not_helpful", "search": "Article A"}).json()
        self.assertEqual(listing["total"], 1); self.assertEqual(listing["items"][0]["question"], "Question")
        detail = self.client.get(f"/api/v1/admin/analytics/feedback/{listing['items'][0]['feedback_id']}").json()
        self.assertEqual([row["rank"] for row in detail["results"]], [1, 2])
        self.assertNotIn("password", str(detail).lower())
        empty = self.client.get("/api/v1/admin/analytics/feedback", params={"rating": "helpful"}).json()
        self.assertEqual(empty["items"], [])
        self.assertEqual(self.client.get("/api/v1/admin/analytics/feedback", params={"sort_by": "secret"}).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/admin/analytics/feedback/9999").status_code, 404)


if __name__ == "__main__": unittest.main()

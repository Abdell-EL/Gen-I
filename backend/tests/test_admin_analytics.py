from __future__ import annotations

from datetime import datetime
import re
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin_routes import router as admin_router
from app.auth_dependencies import get_current_user
from app.database import Base, get_db
from app.models import RetrievalRequest, User


class AdminAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def install_functions(connection, _record):
            connection.create_function("btrim", 1, lambda value: value.strip() if value else value)
            connection.create_function(
                "regexp_replace",
                4,
                lambda value, pattern, replacement, flags: re.sub(
                    r"\s+", replacement, value
                ),
            )

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.admin = self.add_user("Admin", "admin@example.com", "admin", True)
        self.agent = self.add_user("Agent", "agent@example.com", "agent", True)
        self.zero_user = self.add_user("Zero", "zero@example.com", "agent", True)
        self.dev_user = self.add_user(
            "Development User", "dev.user@sogetrel.local", "developer", True
        )
        self.add_question(self.admin, "  How   to Close? ", "2026-01-01T10:00:00")
        self.add_question(self.agent, "how to close?", "2026-01-02T10:00:00")
        self.add_question(self.agent, "Different wording", "2026-02-01T10:00:00")
        self.add_question(self.dev_user, "Historical question", "2025-12-01T10:00:00")
        self.add_question(self.agent, "   ", "2026-02-02T10:00:00")
        self.app = FastAPI()
        self.app.include_router(admin_router, prefix="/api/v1")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def add_user(self, name, email, role, active):
        user = User(
            full_name=name,
            email=email,
            role=role,
            is_active=active,
            password_hash="unused",
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def add_question(self, user, text, created_at):
        request = RetrievalRequest(
            message_id=1,
            user_id=user.user_id,
            query_text=text,
            top_k=5,
            created_at=datetime.fromisoformat(created_at),
        )
        self.db.add(request)
        self.db.commit()

    def test_user_ranking_counts_orders_and_includes_zero_and_historical_users(self):
        response = self.client.get("/api/v1/admin/analytics/users", params={"page_size": 10})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        counts = {item["email"]: item["questions_count"] for item in body["items"]}
        self.assertEqual(counts["agent@example.com"], 3)
        self.assertEqual(counts["admin@example.com"], 1)
        self.assertEqual(counts["zero@example.com"], 0)
        self.assertEqual(counts["dev.user@sogetrel.local"], 1)
        self.assertEqual(body["items"][0]["email"], "agent@example.com")

    def test_user_date_filter_applies_to_count_not_user_visibility(self):
        response = self.client.get(
            "/api/v1/admin/analytics/users",
            params={"date_from": "2026-02-01", "date_to": "2026-02-28", "page_size": 10},
        )
        self.assertEqual(response.status_code, 200)
        counts = {item["email"]: item["questions_count"] for item in response.json()["items"]}
        self.assertEqual(counts["agent@example.com"], 2)
        self.assertEqual(counts["admin@example.com"], 0)
        self.assertEqual(counts["dev.user@sogetrel.local"], 0)

    def test_invalid_date_range_is_422(self):
        response = self.client.get(
            "/api/v1/admin/analytics/users",
            params={"date_from": "2026-03-01", "date_to": "2026-02-01"},
        )
        self.assertEqual(response.status_code, 422)

    def test_question_normalization_combines_case_and_spacing(self):
        response = self.client.get("/api/v1/admin/analytics/questions")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        combined = next(item for item in items if item["normalized_question"] == "how to close?")
        self.assertEqual(combined["count"], 2)
        self.assertEqual(combined["unique_users"], 2)
        self.assertTrue(combined["question"].strip())
        self.assertTrue(any(item["normalized_question"] == "different wording" for item in items))
        self.assertFalse(any(not item["normalized_question"] for item in items))

    def test_question_user_and_role_filters(self):
        response = self.client.get(
            "/api/v1/admin/analytics/questions",
            params={"user_id": self.admin.user_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(response.json()["items"][0]["count"], 1)

        response = self.client.get(
            "/api/v1/admin/analytics/questions", params={"role": "admin"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["example_user"]["user_id"], self.admin.user_id)

    def test_minimum_count_limit_and_validation(self):
        response = self.client.get(
            "/api/v1/admin/analytics/questions",
            params={"minimum_count": 2, "limit": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(response.json()["items"][0]["count"], 2)
        self.assertEqual(
            self.client.get(
                "/api/v1/admin/analytics/questions", params={"minimum_count": 0}
            ).status_code,
            422,
        )

    def test_agent_cannot_access_and_admin_can_access_analytics(self):
        self.assertEqual(self.client.get("/api/v1/admin/analytics/users").status_code, 200)
        self.app.dependency_overrides[get_current_user] = lambda: self.agent
        self.assertEqual(self.client.get("/api/v1/admin/analytics/users").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/admin/analytics/questions").status_code, 403)


if __name__ == "__main__":
    unittest.main()

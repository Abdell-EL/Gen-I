from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_dependencies import get_current_user
import app.routes as routes_module
from app.routes import router as api_router
from app.services import retrieval_logging_service


def make_user(user_id: int, role: str):
    return SimpleNamespace(user_id=user_id, role=role, is_active=True)


def audit_for(actor_user_id: int):
    return {
        "audit_logged": True,
        "retrieval_id": 101,
        "user_id": actor_user_id,
        "session_id": 202,
        "message_id": 303,
        "logged_results": 0,
        "missing_chunk_ids": [],
    }


class AuditAttributionRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(api_router, prefix="/api/v1")
        self.client = TestClient(self.app)

    def authenticate(self, user_id: int, role: str):
        user = make_user(user_id, role)
        self.app.dependency_overrides[get_current_user] = lambda: user
        return user

    @staticmethod
    def logging_side_effect(**kwargs):
        return audit_for(kwargs["actor_user_id"])

    def post_search(self, body=None):
        with (
            patch("app.routes.search_chunks", return_value=[]),
            patch(
                "app.routes.log_retrieval_event",
                side_effect=self.logging_side_effect,
            ) as logger,
        ):
            response = self.client.post(
                "/api/v1/search",
                json=body or {"query": "audit attribution", "limit": 3},
            )
        return response, logger

    def test_admin_search_attributes_authenticated_admin(self):
        self.authenticate(5, "admin")
        response, logger = self.post_search()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit"]["user_id"], 5)
        self.assertEqual(logger.call_args.kwargs["actor_user_id"], 5)

    def test_agent_search_attributes_authenticated_agent(self):
        self.authenticate(17, "agent")
        response, logger = self.post_search()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit"]["user_id"], 17)
        self.assertEqual(logger.call_args.kwargs["actor_user_id"], 17)

    def test_two_authenticated_users_produce_distinct_audit_users(self):
        observed = []
        for user_id, role in ((5, "admin"), (17, "agent")):
            self.authenticate(user_id, role)
            response, _ = self.post_search()
            observed.append(response.json()["audit"]["user_id"])
        self.assertEqual(observed, [5, 17])

    def test_request_body_user_id_cannot_override_authenticated_actor(self):
        self.authenticate(5, "admin")
        response, logger = self.post_search(
            {"query": "audit attribution", "limit": 3, "user_id": 999}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit"]["user_id"], 5)
        self.assertEqual(logger.call_args.kwargs["actor_user_id"], 5)

    def test_keyword_search_attributes_authenticated_user(self):
        self.authenticate(23, "agent")
        with (
            patch.object(
                routes_module.retrieval_service, "keyword_search", return_value=[]
            ),
            patch(
                "app.routes.log_retrieval_event",
                side_effect=self.logging_side_effect,
            ) as logger,
        ):
            response = self.client.post(
                "/api/v1/keyword-search", json={"query": "keyword", "limit": 4}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit"]["user_id"], 23)
        self.assertEqual(logger.call_args.kwargs["actor_user_id"], 23)
        self.assertEqual(logger.call_args.kwargs["interaction_type"], "keyword_search")

    def test_chat_attributes_authenticated_user(self):
        self.authenticate(31, "agent")
        with (
            patch("app.routes.search_chunks", return_value=[]),
            patch(
                "app.routes.compose_answer",
                return_value={"answer": "fallback", "confidence": "low"},
            ),
            patch(
                "app.routes.generate_answer_with_ollama",
                return_value={"answer": "generated", "model": "test-model"},
            ),
            patch(
                "app.routes.log_retrieval_event",
                side_effect=self.logging_side_effect,
            ) as logger,
        ):
            response = self.client.post(
                "/api/v1/chat", json={"question": "chat attribution"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit"]["user_id"], 31)
        self.assertEqual(logger.call_args.kwargs["actor_user_id"], 31)
        self.assertEqual(logger.call_args.kwargs["interaction_type"], "chat")

    def test_search_response_shape_is_unchanged(self):
        self.authenticate(5, "admin")
        response, _ = self.post_search()
        self.assertEqual(
            set(response.json()),
            {"query", "search_type", "top_k", "results_count", "results", "audit"},
        )
        self.assertEqual(
            set(response.json()["audit"]),
            {
                "audit_logged", "retrieval_id", "user_id", "session_id",
                "message_id", "logged_results", "missing_chunk_ids",
            },
        )

    def test_authentication_and_authorization_precede_business_logic(self):
        with patch("app.routes.search_chunks") as search:
            response = self.client.post("/api/v1/search", json={"query": "test"})
        self.assertEqual(response.status_code, 401)
        search.assert_not_called()

        self.authenticate(7, "unknown")
        with patch("app.routes.search_chunks") as search:
            response = self.client.post("/api/v1/search", json={"query": "test"})
        self.assertEqual(response.status_code, 403)
        search.assert_not_called()

    def test_development_user_helper_is_absent(self):
        self.assertFalse(hasattr(retrieval_logging_service, "_get_or_create_dev_user"))


class AuditPersistenceTests(unittest.TestCase):
    def test_persistence_receives_authenticated_actor_id(self):
        db = MagicMock()
        with (
            patch.object(retrieval_logging_service, "SessionLocal", return_value=db),
            patch.object(
                retrieval_logging_service, "_create_chat_session", return_value=10
            ) as create_session,
            patch.object(
                retrieval_logging_service, "_create_user_message", return_value=20
            ),
            patch.object(
                retrieval_logging_service, "_create_retrieval_request", return_value=30
            ) as create_retrieval,
        ):
            result = retrieval_logging_service.log_retrieval_event(
                actor_user_id=42,
                query_text="persistence attribution",
                top_k=5,
                retrieved_chunks=[],
                interaction_type="search",
            )
        self.assertEqual(result["user_id"], 42)
        self.assertEqual(create_session.call_args.kwargs["user_id"], 42)
        self.assertEqual(create_retrieval.call_args.kwargs["user_id"], 42)
        db.commit.assert_called_once_with()
        db.rollback.assert_not_called()
        db.close.assert_called_once_with()

    def test_invalid_actor_fails_before_opening_database_session(self):
        for actor_user_id in (None, 0, -1, True, "5"):
            with self.subTest(actor_user_id=actor_user_id):
                with patch.object(retrieval_logging_service, "SessionLocal") as session:
                    with self.assertRaises(ValueError):
                        retrieval_logging_service.log_retrieval_event(
                            actor_user_id=actor_user_id,
                            query_text="invalid actor",
                            top_k=5,
                            retrieved_chunks=[],
                            interaction_type="search",
                        )
                session.assert_not_called()


if __name__ == "__main__":
    unittest.main()

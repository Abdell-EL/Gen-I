from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_dependencies import get_current_user
from app.auth_routes import router as auth_router
from app.config import AuthSettings, get_auth_settings
from app.database import get_db
from app.routes import router as api_router
from app.security import create_access_token


SIGNING_KEY = "authorization-test-key-0123456789abcdef0123456789abcdef0123456789abcdef"
SETTINGS = AuthSettings(
    jwt_secret=SIGNING_KEY,
    jwt_issuer="authorization-test-issuer",
    jwt_audience="authorization-test-audience",
    access_token_minutes=15,
)


def make_user(*, role="agent", is_active=True, user_id=1):
    return SimpleNamespace(
        user_id=user_id,
        full_name="Authorization Test User",
        email="authz@example.com",
        password_hash="unused-test-hash",
        role=role,
        is_active=is_active,
    )


class AuthorizationRouteTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.app = FastAPI()
        self.app.include_router(api_router, prefix="/api/v1")
        self.app.include_router(auth_router, prefix="/api/v1")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_auth_settings] = lambda: SETTINGS
        self.settings_patch = patch(
            "app.auth_dependencies.get_auth_settings", return_value=SETTINGS
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.client = TestClient(self.app)

    def token(self, *, lifetime=timedelta(minutes=5), subject="1"):
        return create_access_token(
            signing_key=SIGNING_KEY,
            issuer=SETTINGS.jwt_issuer,
            audience=SETTINGS.jwt_audience,
            lifetime=lifetime,
            subject=subject,
        )

    def bearer(self, token=None):
        return {"Authorization": f"Bearer {token or self.token()}"}

    def override_user(self, role="agent"):
        user = make_user(role=role)
        self.app.dependency_overrides[get_current_user] = lambda: user
        return user

    def assert_unauthorized(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Not authenticated."})
        self.assertEqual(response.headers.get("www-authenticate"), "Bearer")

    def assert_forbidden(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Insufficient permissions."})

    def test_public_health_works_without_token(self):
        with patch("app.routes.get_system_health", return_value={"status": "ok"}):
            response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_signin_remains_public(self):
        user = make_user(role="admin")
        with patch("app.auth_routes.authenticate_user", return_value=user):
            response = self.client.post(
                "/api/v1/auth/signin",
                json={"email": "authz@example.com", "password": "not-logged"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.json())

    def test_search_without_token_is_401_and_does_not_run_search(self):
        with patch("app.routes.search_chunks") as search:
            response = self.client.post("/api/v1/search", json={"query": "test"})
        self.assert_unauthorized(response)
        search.assert_not_called()

    def test_chat_with_malformed_token_is_401(self):
        response = self.client.post(
            "/api/v1/chat",
            json={"question": "test"},
            headers=self.bearer("malformed-token"),
        )
        self.assert_unauthorized(response)

    def test_expired_token_is_401(self):
        response = self.client.post(
            "/api/v1/search",
            json={"query": "test"},
            headers=self.bearer(self.token(lifetime=timedelta(seconds=-1))),
        )
        self.assert_unauthorized(response)

    def test_deleted_user_is_401(self):
        self.db.get.return_value = None
        response = self.client.post(
            "/api/v1/search", json={"query": "test"}, headers=self.bearer()
        )
        self.assert_unauthorized(response)

    def test_inactive_user_is_401(self):
        self.db.get.return_value = make_user(is_active=False)
        response = self.client.post(
            "/api/v1/search", json={"query": "test"}, headers=self.bearer()
        )
        self.assert_unauthorized(response)

    def test_agent_and_admin_can_search_with_unchanged_shape(self):
        source = {"id": "chunk-1", "rank": 1, "score": 0.9, "text": "answer"}
        for role in ("agent", "admin", " Admin "):
            with self.subTest(role=role):
                self.override_user(role)
                with (
                    patch("app.routes.search_chunks", return_value=[source]),
                    patch("app.routes.log_retrieval_event", return_value=None),
                ):
                    response = self.client.post(
                        "/api/v1/search", json={"query": "test", "limit": 3}
                    )
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(
                    set(body),
                    {"query", "search_type", "top_k", "results_count", "results", "audit"},
                )
                self.assertEqual(body["results_count"], 1)

    def test_unknown_empty_and_null_roles_fail_closed_on_search(self):
        for role in ("manager", "", "   ", None):
            with self.subTest(role=role):
                self.override_user(role)
                response = self.client.post("/api/v1/search", json={"query": "test"})
                self.assert_forbidden(response)

    def test_admin_can_access_ingestion_jobs(self):
        self.override_user("admin")
        with patch("app.routes.list_ingestion_jobs", return_value=[]):
            response = self.client.get("/api/v1/admin/ingestion/jobs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_agent_and_unknown_roles_cannot_access_admin_ingestion(self):
        for role in ("agent", "unknown"):
            with self.subTest(role=role):
                self.override_user(role)
                response = self.client.get("/api/v1/admin/ingestion/jobs")
                self.assert_forbidden(response)

    def test_admin_route_authentication_failure_is_401_not_403(self):
        response = self.client.get("/api/v1/admin/ingestion/jobs")
        self.assert_unauthorized(response)

    def test_admin_can_access_audit_and_agent_cannot(self):
        self.override_user("admin")
        with patch("app.routes.get_latest_retrievals", return_value=[]):
            response = self.client.get("/api/v1/audit/retrievals/latest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"count": 0, "retrievals": []})

        self.override_user("agent")
        response = self.client.get("/api/v1/audit/retrievals/latest")
        self.assert_forbidden(response)

    def test_auth_me_remains_authenticated(self):
        self.db.get.return_value = make_user(role="agent")
        response = self.client.get("/api/v1/auth/me", headers=self.bearer())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "agent")

    def test_openapi_builds_and_declares_bearer_security(self):
        schema = self.app.openapi()
        self.assertIn("/api/v1/health", schema["paths"])
        self.assertNotIn("security", schema["paths"]["/api/v1/health"]["get"])
        self.assertNotIn("security", schema["paths"]["/api/v1/auth/signin"]["post"])
        self.assertTrue(schema["paths"]["/api/v1/search"]["post"]["security"])
        self.assertTrue(schema["paths"]["/api/v1/admin/ingestion/jobs"]["get"]["security"])

    def test_documentation_routes_remain_available(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertEqual(self.client.get("/redoc").status_code, 200)
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)


if __name__ == "__main__":
    unittest.main()

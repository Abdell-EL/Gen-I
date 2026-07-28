from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin_routes import router as admin_router
from app.auth_dependencies import get_current_user
from app.database import Base, get_db
from app.models import AuditLog, User
from app.security import MAX_PASSWORD_BYTES


class AdminUserManagementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.admin = self.add_user("Admin", "admin@example.com", "admin", True)
        self.agent = self.add_user("Agent One", "agent@example.com", "agent", True)
        self.app = FastAPI()
        self.app.include_router(admin_router, prefix="/api/v1")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(self.app)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def add_user(self, name, email, role, active, password_hash="existing-hash"):
        user = User(
            full_name=name,
            email=email,
            role=role,
            is_active=active,
            password_hash=password_hash,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def audits(self):
        return list(self.db.execute(select(AuditLog).order_by(AuditLog.audit_id)).scalars())

    def test_admin_lists_searches_and_paginates_users_safely(self):
        response = self.client.get(
            "/api/v1/admin/users",
            params={"search": "  AGENT@EXAMPLE  ", "page": 1, "page_size": 1},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["pages"], 1)
        self.assertEqual(body["items"][0]["email"], "agent@example.com")
        self.assertNotIn("password_hash", body["items"][0])
        self.assertNotIn("password", body["items"][0])

    def test_agent_and_missing_auth_cannot_list_users(self):
        self.app.dependency_overrides[get_current_user] = lambda: self.agent
        self.assertEqual(self.client.get("/api/v1/admin/users").status_code, 403)
        del self.app.dependency_overrides[get_current_user]
        self.assertEqual(self.client.get("/api/v1/admin/users").status_code, 401)

    def test_list_validation_rejects_bad_pagination_role_and_sort(self):
        cases = (
            {"page": 0},
            {"page_size": 101},
            {"role": "developer"},
            {"sort_by": "password_hash"},
            {"sort_order": "sideways"},
        )
        for params in cases:
            with self.subTest(params=params):
                self.assertEqual(
                    self.client.get("/api/v1/admin/users", params=params).status_code,
                    422,
                )

    def test_get_user_and_unknown_user(self):
        response = self.client.get(f"/api/v1/admin/users/{self.agent.user_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.agent.user_id)
        self.assertNotIn("password_hash", response.json())
        self.assertEqual(self.client.get("/api/v1/admin/users/9999").status_code, 404)

    def test_admin_creates_agent_with_normalized_email_and_audit(self):
        with patch("app.services.admin_user_service.hash_password", return_value="hashed") as hasher:
            response = self.client.post(
                "/api/v1/admin/users",
                json={
                    "full_name": " New Agent ",
                    "email": " NEW.Agent@Example.COM ",
                    "password": "safe-password",
                    "actor_user_id": 999,
                },
            )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["email"], "new.agent@example.com")
        self.assertEqual(body["role"], "agent")
        self.assertNotIn("password_hash", body)
        hasher.assert_called_once_with("safe-password")
        audit = self.audits()[-1]
        self.assertEqual(audit.user_id, self.admin.user_id)
        self.assertEqual(audit.entity_id, body["id"])
        self.assertEqual(audit.action, "user.created")

    def test_admin_creates_admin(self):
        with patch("app.services.admin_user_service.hash_password", return_value="hashed"):
            response = self.client.post(
                "/api/v1/admin/users",
                json={
                    "full_name": "Second Admin",
                    "email": "second.admin@example.com",
                    "password": "safe-password",
                    "role": "admin",
                },
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["role"], "admin")

    def test_duplicate_email_fails_without_audit(self):
        before = len(self.audits())
        response = self.client.post(
            "/api/v1/admin/users",
            json={
                "full_name": "Duplicate",
                "email": " AGENT@example.com ",
                "password": "safe-password",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.audits()), before)

    def test_create_validation_rejects_role_name_and_password_byte_limit(self):
        base = {
            "full_name": "Candidate",
            "email": "candidate@example.com",
            "password": "safe-password",
        }
        cases = (
            {**base, "role": "developer"},
            {**base, "full_name": "   "},
            {**base, "password": "é" * (MAX_PASSWORD_BYTES // 2 + 1)},
        )
        for payload in cases:
            with self.subTest(keys=payload.keys()):
                self.assertEqual(
                    self.client.post("/api/v1/admin/users", json=payload).status_code,
                    422,
                )

    def test_partial_update_normalizes_values_and_audits_actions(self):
        response = self.client.patch(
            f"/api/v1/admin/users/{self.agent.user_id}",
            json={"full_name": " Updated Agent ", "role": "admin", "is_active": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["full_name"], "Updated Agent")
        self.assertEqual(response.json()["role"], "admin")
        self.assertFalse(response.json()["is_active"])
        actions = [audit.action for audit in self.audits()]
        self.assertEqual(actions, ["user.updated", "user.role_changed", "user.deactivated"])
        self.assertTrue(all(audit.user_id == self.admin.user_id for audit in self.audits()))

    def test_empty_null_password_and_unknown_updates_are_rejected(self):
        self.assertEqual(
            self.client.patch(f"/api/v1/admin/users/{self.agent.user_id}", json={}).status_code,
            422,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/admin/users/{self.agent.user_id}", json={"role": None}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/admin/users/{self.agent.user_id}",
                json={"password": "not-allowed"},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.patch("/api/v1/admin/users/9999", json={"full_name": "Unknown"}).status_code,
            404,
        )

    def test_self_deactivation_and_demotion_are_rejected(self):
        for patch_body in ({"is_active": False}, {"role": "agent"}):
            with self.subTest(patch_body=patch_body):
                response = self.client.patch(
                    f"/api/v1/admin/users/{self.admin.user_id}", json=patch_body
                )
                self.assertEqual(response.status_code, 409)
        self.assertEqual(self.audits(), [])

    def test_final_active_admin_cannot_be_deactivated_or_demoted(self):
        external_admin = SimpleAdmin(user_id=999, role="admin", is_active=True)
        self.app.dependency_overrides[get_current_user] = lambda: external_admin
        for patch_body in ({"is_active": False}, {"role": "agent"}):
            with self.subTest(patch_body=patch_body):
                response = self.client.patch(
                    f"/api/v1/admin/users/{self.admin.user_id}", json=patch_body
                )
                self.assertEqual(response.status_code, 409)

    def test_password_reset_hashes_and_audits_without_secret_material(self):
        with patch("app.services.admin_user_service.hash_password", return_value="new-hash") as hasher:
            response = self.client.post(
                f"/api/v1/admin/users/{self.agent.user_id}/reset-password",
                json={"new_password": "new-secret", "actor_user_id": 999},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "password_reset", "user_id": self.agent.user_id},
        )
        self.assertEqual(set(response.json()), {"status", "user_id"})
        self.assertNotIn("new_password", response.json())
        self.assertNotIn("password_hash", response.json())
        hasher.assert_called_once_with("new-secret")
        audit = self.audits()[-1]
        self.assertEqual(audit.user_id, self.admin.user_id)
        self.assertEqual(audit.entity_id, self.agent.user_id)
        self.assertEqual(audit.action, "user.password_reset")
        self.assertNotIn("new-secret", str(audit.method_json))
        self.assertNotIn("hash", str(audit.method_json).lower())


class SimpleAdmin:
    def __init__(self, user_id, role, is_active):
        self.user_id = user_id
        self.role = role
        self.is_active = is_active


if __name__ == "__main__":
    unittest.main()

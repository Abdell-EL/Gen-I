from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import logging
import unittest
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin_routes import invitation_provider, router as admin_router
from app.auth_dependencies import get_current_user
from app.auth_routes import router as auth_router
from app.config import AuthSettings, InvitationSettings, get_auth_settings, get_invitation_settings
from app.database import Base, get_db
from app.models import AuditLog, InvitationToken, User
from app.security import MAX_PASSWORD_BYTES, hash_password
from app.services.invitation_delivery import InvitationDeliveryResult


AUTH = AuthSettings(jwt_secret="x" * 64, jwt_issuer="tests", jwt_audience="tests", access_token_minutes=15)
INVITES = InvitationSettings(frontend_activation_url="http://frontend.test/activate",
    token_lifetime_minutes=60, email_provider_mode="capture", resend_cooldown_seconds=0,
    expose_activation_url=False)


class CapturingProvider:
    def __init__(self): self.urls = []
    def deliver(self, **kwargs):
        self.urls.append(kwargs["activation_url"])
        return InvitationDeliveryResult(status="sent", delivered=True)


class FailingProvider:
    def deliver(self, **_kwargs): raise RuntimeError("provider unavailable")


class InvitationActivationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.admin = self.add_user("Admin", "admin@example.com", "admin", "admin-password")
        self.agent = self.add_user("Agent", "agent@example.com", "agent", "agent-password")
        self.provider = CapturingProvider()
        app = FastAPI(); app.include_router(auth_router, prefix="/api/v1"); app.include_router(admin_router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_auth_settings] = lambda: AUTH
        app.dependency_overrides[get_invitation_settings] = lambda: INVITES
        app.dependency_overrides[get_current_user] = lambda: self.admin
        app.dependency_overrides[invitation_provider] = lambda: self.provider
        self.app = app; self.client = TestClient(app)

    def tearDown(self):
        self.db.close(); Base.metadata.drop_all(self.engine); self.engine.dispose()

    def add_user(self, name, email, role, password):
        user = User(full_name=name, email=email, role=role, is_active=True,
                    activation_status="active", password_hash=hash_password(password))
        self.db.add(user); self.db.commit(); self.db.refresh(user); return user

    def invite(self, email="new@example.com", role="agent"):
        response = self.client.post("/api/v1/admin/users", json={
            "full_name": " New User ", "email": email, "role": role,
        })
        return response

    def raw_token(self, index=-1):
        return parse_qs(urlparse(self.provider.urls[index]).query)["token"][0]

    def test_admin_creates_pending_agent_and_admin_without_secret_response(self):
        for index, role in enumerate(("agent", "admin")):
            response = self.invite(f"new{index}@example.com", role)
            self.assertEqual(response.status_code, 201)
            body = response.json(); self.assertEqual(body["activation_status"], "pending")
            self.assertTrue(body["is_active"]); self.assertEqual(body["role"], role)
            self.assertEqual(body["invitation_delivery"], {"status": "sent", "activation_url": None})
            self.assertNotIn("token", str(body).lower()); self.assertNotIn("password", str(body).lower())
        rows = self.db.execute(select(InvitationToken)).scalars().all()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(len(row.token_hash) == 64 for row in rows))
        self.assertTrue(all(self.raw_token(i) not in row.token_hash for i, row in enumerate(rows)))
        self.assertEqual([a.action for a in self.db.execute(select(AuditLog).order_by(AuditLog.audit_id)).scalars()],
                         ["user.invited", "user.invited"])

    def test_admin_access_duplicate_and_invited_signin(self):
        self.app.dependency_overrides[get_current_user] = lambda: self.agent
        self.assertEqual(self.invite().status_code, 403)
        del self.app.dependency_overrides[get_current_user]
        self.assertEqual(self.invite().status_code, 401)
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.assertEqual(self.invite("agent@example.com").status_code, 409)
        self.assertEqual(self.invite().status_code, 201)
        signin = self.client.post("/api/v1/auth/signin", json={"email": "new@example.com", "password": "anything"})
        self.assertEqual(signin.status_code, 401)

    def test_validate_activate_and_exactly_once(self):
        self.assertEqual(self.invite().status_code, 201); token = self.raw_token()
        valid = self.client.post("/api/v1/auth/activation/validate", json={"token": token})
        self.assertEqual(valid.status_code, 200); self.assertTrue(valid.json()["valid"])
        mismatch = self.client.post("/api/v1/auth/activation/complete", json={
            "token": token, "password": "new-password", "password_confirmation": "different"})
        self.assertEqual(mismatch.status_code, 422)
        oversized = "é" * (MAX_PASSWORD_BYTES // 2 + 1)
        self.assertEqual(self.client.post("/api/v1/auth/activation/complete", json={
            "token": token, "password": oversized, "password_confirmation": oversized}).status_code, 422)
        activated = self.client.post("/api/v1/auth/activation/complete", json={
            "token": token, "password": "new-password", "password_confirmation": "new-password"})
        self.assertEqual(activated.status_code, 200)
        self.assertNotIn(token, str(activated.json()))
        self.assertNotIn("new-password", str(activated.json()))
        self.assertEqual(self.client.post("/api/v1/auth/activation/complete", json={
            "token": token, "password": "new-password", "password_confirmation": "new-password"}).status_code, 400)
        user = self.db.execute(select(User).where(User.email == "new@example.com")).scalar_one()
        row = self.db.execute(select(InvitationToken).where(InvitationToken.user_id == user.user_id)).scalar_one()
        self.assertEqual(user.activation_status, "active"); self.assertIsNotNone(row.consumed_at)
        self.assertEqual(self.client.post("/api/v1/auth/signin", json={
            "email": user.email, "password": "new-password"}).status_code, 200)

    def test_expired_and_resend_invalidates_old_token(self):
        self.invite(); old = self.raw_token()
        row = self.db.execute(select(InvitationToken)).scalar_one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); self.db.commit()
        self.assertEqual(self.client.post("/api/v1/auth/activation/validate", json={"token": old}).status_code, 400)
        row.expires_at = datetime.now(timezone.utc) + timedelta(hours=1); self.db.commit()
        resend = self.client.post(f"/api/v1/admin/users/{row.user_id}/resend-invitation")
        self.assertEqual(resend.status_code, 200); new = self.raw_token()
        self.assertNotEqual(old, new)
        self.assertEqual(self.client.post("/api/v1/auth/activation/validate", json={"token": old}).status_code, 400)
        self.assertEqual(self.client.post("/api/v1/auth/activation/validate", json={"token": new}).status_code, 200)
        actions = [audit.action for audit in self.db.execute(select(AuditLog)).scalars()]
        self.assertIn("invitation.resent", actions)

    def test_resend_activated_and_delivery_failure(self):
        self.assertEqual(self.client.post(f"/api/v1/admin/users/{self.agent.user_id}/resend-invitation").status_code, 409)
        self.app.dependency_overrides[invitation_provider] = lambda: FailingProvider()
        response = self.invite("failure@example.com")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["invitation_delivery"]["status"], "failed")
        user = self.db.execute(select(User).where(User.email == "failure@example.com")).scalar_one()
        token = self.db.execute(select(InvitationToken).where(InvitationToken.user_id == user.user_id)).scalar_one()
        self.assertEqual(user.activation_status, "pending"); self.assertIsNotNone(token.invalidated_at)
        audit = self.db.execute(select(AuditLog).order_by(AuditLog.audit_id.desc())).scalars().first()
        self.assertEqual(audit.action, "invitation.delivery_failed")
        self.assertNotIn("token", str(audit.method_json).lower())

    def test_resend_throttle_and_openapi_security(self):
        self.invite(); user = self.db.execute(select(User).where(
            User.email == "new@example.com")).scalar_one()
        throttled = InvitationSettings(
            frontend_activation_url=INVITES.frontend_activation_url,
            token_lifetime_minutes=60, email_provider_mode="capture",
            resend_cooldown_seconds=60, expose_activation_url=False,
        )
        self.app.dependency_overrides[get_invitation_settings] = lambda: throttled
        response = self.client.post(f"/api/v1/admin/users/{user.user_id}/resend-invitation")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "60")
        schema = self.app.openapi()
        self.assertNotIn("security", schema["paths"]["/api/v1/auth/activation/validate"]["post"])
        self.assertNotIn("security", schema["paths"]["/api/v1/auth/activation/complete"]["post"])
        self.assertTrue(schema["paths"][
            "/api/v1/admin/users/{user_id}/resend-invitation"
        ]["post"]["security"])

    def test_tokens_and_passwords_are_absent_from_logs(self):
        self.invite(); token = self.raw_token(); password = "private-activation-password"
        stream = io.StringIO(); handler = logging.StreamHandler(stream)
        root = logging.getLogger(); root.addHandler(handler)
        try:
            response = self.client.post("/api/v1/auth/activation/complete", json={
                "token": token, "password": password, "password_confirmation": password,
            })
        finally:
            root.removeHandler(handler)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(token, stream.getvalue())
        self.assertNotIn(password, stream.getvalue())

    def test_existing_active_user_signin_regression(self):
        response = self.client.post("/api/v1/auth/signin", json={
            "email": self.agent.email, "password": "agent-password"})
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__": unittest.main()

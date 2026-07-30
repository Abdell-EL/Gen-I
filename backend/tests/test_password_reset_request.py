from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import logging
import os
from urllib.parse import parse_qs, urlparse
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth_routes import password_reset_provider, router as auth_router
from app.config import (
    PasswordResetConfigurationError,
    PasswordResetSettings,
    get_password_reset_settings,
)
from app.database import Base, get_db
from app.models import AuditLog, PasswordResetToken, User
from app.security import hash_password
from app.services.password_reset_delivery import (
    NoopPasswordResetDeliveryProvider,
    PasswordResetDeliveryResult,
)
from app.services.password_reset_service import (
    FORGOT_PASSWORD_MESSAGE,
    token_digest,
)


BASE_SETTINGS = PasswordResetSettings(
    frontend_password_reset_url="http://frontend.test/reset-password",
    email_provider_mode="capture",
    expose_reset_url=False,
    token_ttl_minutes=30,
    resend_cooldown_seconds=60,
)


class CapturingResetProvider:
    def __init__(self) -> None:
        self.deliveries: list[dict[str, str]] = []

    def deliver(self, **kwargs):
        self.deliveries.append(dict(kwargs))
        return PasswordResetDeliveryResult(status="sent", delivered=True)


class FailingResetProvider:
    def __init__(self) -> None:
        self.calls = 0

    def deliver(self, **_kwargs):
        self.calls += 1
        raise RuntimeError("provider unavailable with secret reset URL")


class PasswordResetRequestTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.settings = BASE_SETTINGS
        self.provider = CapturingResetProvider()
        self.eligible = self.add_user(
            "Eligible User", "eligible@example.com", "eligible-password"
        )
        self.pending = self.add_user(
            "Pending User",
            "pending@example.com",
            "pending-password",
            activation_status="pending",
        )
        self.disabled = self.add_user(
            "Disabled User",
            "disabled@example.com",
            "disabled-password",
            is_active=False,
        )
        self.no_password = self.add_user(
            "No Password User",
            "nopassword@example.com",
            None,
        )
        self.other = self.add_user("Other User", "other@example.com", "other-password")

        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_password_reset_settings] = lambda: self.settings
        app.dependency_overrides[password_reset_provider] = lambda: self.provider
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def add_user(
        self,
        full_name: str,
        email: str,
        password: str | None,
        *,
        is_active: bool = True,
        activation_status: str = "active",
    ) -> User:
        user = User(
            full_name=full_name,
            email=email,
            role="agent",
            is_active=is_active,
            activation_status=activation_status,
            password_hash=hash_password(password) if password is not None else None,
            token_version=0,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def add_reset_token(
        self,
        *,
        user: User | None = None,
        raw_token: str | None = None,
        token_hash: str | None = None,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
        consumed_at: datetime | None = None,
        invalidated_at: datetime | None = None,
        delivery_status: str = "sent",
    ) -> PasswordResetToken:
        raw = raw_token or "test-token-with-enough-length-0123456789"
        token = PasswordResetToken(
            user_id=(user or self.eligible).user_id,
            token_hash=token_hash or token_digest(raw),
            delivery_status=delivery_status,
            created_at=created_at or datetime.now(timezone.utc),
            expires_at=expires_at or datetime.now(timezone.utc) + timedelta(hours=1),
            consumed_at=consumed_at,
            invalidated_at=invalidated_at,
        )
        self.db.add(token)
        self.db.commit()
        self.db.refresh(token)
        return token

    def forgot(self, email: str = "eligible@example.com"):
        return self.client.post(
            "/api/v1/auth/password/forgot",
            json={"email": email},
        )

    def validate_token(self, token: str):
        return self.client.post(
            "/api/v1/auth/password/reset/validate",
            json={"token": token},
        )

    def token_rows(self, user: User | None = None) -> list[PasswordResetToken]:
        user_id = (user or self.eligible).user_id
        return list(
            self.db.execute(
                select(PasswordResetToken)
                .where(PasswordResetToken.user_id == user_id)
                .order_by(PasswordResetToken.password_reset_token_id)
            ).scalars()
        )

    def audits(self, user: User | None = None) -> list[AuditLog]:
        user_id = (user or self.eligible).user_id
        return list(
            self.db.execute(
                select(AuditLog)
                .where(AuditLog.user_id == user_id)
                .order_by(AuditLog.audit_id)
            ).scalars()
        )

    def neutral_body(self):
        return {"message": FORGOT_PASSWORD_MESSAGE, "reset_url": None}

    def raw_token_from_delivery(self, index: int = -1) -> str:
        url = self.provider.deliveries[index]["reset_url"]
        return parse_qs(urlparse(url).query)["token"][0]

    def assert_no_secret_text(self, value: object, *secrets: str) -> None:
        text = str(value)
        for secret in secrets:
            self.assertNotIn(secret, text)

    def test_forgot_password_normal_responses_are_neutral(self):
        responses = []
        responses.append(self.forgot("  ELIGIBLE@example.com  "))
        responses.append(self.forgot("unknown@example.com"))
        responses.append(self.forgot("pending@example.com"))
        responses.append(self.forgot("disabled@example.com"))
        responses.append(self.forgot("nopassword@example.com"))
        responses.append(self.forgot("eligible@example.com"))
        self.provider = FailingResetProvider()
        self.app.dependency_overrides[password_reset_provider] = lambda: self.provider
        responses.append(self.forgot("other@example.com"))

        for response in responses:
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json(), self.neutral_body())
            self.assertEqual(set(response.json()), {"message", "reset_url"})

    def test_eligible_request_creates_hashed_token_expiry_and_safe_audit(self):
        before = datetime.now(timezone.utc)

        response = self.forgot()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), self.neutral_body())
        rows = self.token_rows()
        self.assertEqual(len(rows), 1)
        raw_token = self.raw_token_from_delivery()
        token = rows[0]
        self.assertRegex(token.token_hash, r"^[0-9a-f]{64}$")
        self.assertEqual(token.token_hash, token_digest(raw_token))
        self.assertNotEqual(token.token_hash, raw_token)
        self.assert_no_secret_text(token.__dict__, raw_token, self.provider.deliveries[0]["reset_url"])
        expires_at = token.expires_at.replace(tzinfo=timezone.utc) if token.expires_at.tzinfo is None else token.expires_at
        self.assertGreaterEqual(expires_at, before + timedelta(minutes=29))
        self.assertLessEqual(expires_at, datetime.now(timezone.utc) + timedelta(minutes=31))
        self.assertEqual(token.delivery_status, "sent")

        audit = self.audits()[-1]
        self.assertEqual(audit.action, "password_reset_requested")
        self.assertEqual(
            audit.method_json,
            {
                "provider_mode": "capture",
                "delivery_status": "sent",
                "ttl_minutes": 30,
                "cooldown_suppressed": False,
            },
        )
        self.assert_no_secret_text(
            audit.method_json,
            raw_token,
            self.provider.deliveries[0]["reset_url"],
            token.token_hash,
            "Authorization",
            "Bearer",
        )

    def test_replacement_invalidates_only_prior_outstanding_tokens(self):
        now = datetime.now(timezone.utc)
        old_created = now - timedelta(minutes=5)
        unused = self.add_reset_token(
            token_hash="a" * 64,
            created_at=old_created,
        )
        consumed_at = now - timedelta(minutes=4)
        consumed = self.add_reset_token(
            token_hash="b" * 64,
            created_at=old_created,
            consumed_at=consumed_at,
        )
        invalidated_at = now - timedelta(minutes=3)
        invalidated = self.add_reset_token(
            token_hash="c" * 64,
            created_at=old_created,
            invalidated_at=invalidated_at,
        )
        other = self.add_reset_token(
            user=self.other,
            token_hash="d" * 64,
            created_at=old_created,
        )

        response = self.forgot()

        self.assertEqual(response.status_code, 202)
        for row in (unused, consumed, invalidated, other):
            self.db.refresh(row)
        self.assertIsNotNone(unused.invalidated_at)
        self.assertEqual(consumed.consumed_at, consumed_at.replace(tzinfo=None))
        self.assertIsNone(consumed.invalidated_at)
        self.assertEqual(invalidated.invalidated_at, invalidated_at.replace(tzinfo=None))
        self.assertIsNone(other.invalidated_at)
        self.assertEqual(len(self.token_rows()), 4)

    def test_cooldown_does_not_create_invalidate_or_deliver(self):
        first = self.forgot()
        self.assertEqual(first.status_code, 202)
        token = self.token_rows()[0]
        first_url = self.provider.deliveries[0]["reset_url"]

        second = self.forgot()

        self.assertEqual(second.status_code, 202)
        rows = self.token_rows()
        self.assertEqual(len(rows), 1)
        self.db.refresh(token)
        self.assertIsNone(token.invalidated_at)
        self.assertEqual(len(self.provider.deliveries), 1)
        self.assertEqual(self.provider.deliveries[0]["reset_url"], first_url)
        self.assertTrue(self.audits()[-1].method_json["cooldown_suppressed"])

    def test_failed_delivery_invalidates_token_and_preserves_neutrality(self):
        self.provider = FailingResetProvider()
        self.app.dependency_overrides[password_reset_provider] = lambda: self.provider

        response = self.forgot()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), self.neutral_body())
        rows = self.token_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].delivery_status, "failed")
        self.assertIsNotNone(rows[0].invalidated_at)
        actions = [audit.action for audit in self.audits()]
        self.assertEqual(actions, ["password_reset_requested", "password_reset_delivery_failed"])

        self.provider = CapturingResetProvider()
        self.app.dependency_overrides[password_reset_provider] = lambda: self.provider
        retry = self.forgot()
        self.assertEqual(retry.status_code, 202)
        self.assertEqual(len(self.provider.deliveries), 1)

    def test_provider_url_exposure_guards(self):
        cases = [
            ("noop default", PasswordResetSettings(
                frontend_password_reset_url="http://frontend.test/reset-password",
                email_provider_mode="noop", expose_reset_url=False, token_ttl_minutes=30,
                resend_cooldown_seconds=60,
            ), NoopPasswordResetDeliveryProvider(), False),
            ("noop with mistaken exposure", PasswordResetSettings(
                frontend_password_reset_url="http://frontend.test/reset-password",
                email_provider_mode="noop", expose_reset_url=True, token_ttl_minutes=30,
                resend_cooldown_seconds=60,
            ), NoopPasswordResetDeliveryProvider(), False),
            ("capture without exposure", PasswordResetSettings(
                frontend_password_reset_url="http://frontend.test/reset-password",
                email_provider_mode="capture", expose_reset_url=False, token_ttl_minutes=30,
                resend_cooldown_seconds=60,
            ), CapturingResetProvider(), False),
            ("capture with exposure", PasswordResetSettings(
                frontend_password_reset_url="http://frontend.test/reset-password",
                email_provider_mode="capture", expose_reset_url=True, token_ttl_minutes=30,
                resend_cooldown_seconds=60,
            ), CapturingResetProvider(), True),
        ]
        for label, settings, provider, exposes in cases:
            with self.subTest(label=label):
                self.settings = settings
                self.provider = provider
                self.app.dependency_overrides[password_reset_provider] = lambda: self.provider
                self.db.query(PasswordResetToken).delete()
                self.db.query(AuditLog).delete()
                self.db.commit()

                response = self.forgot()

                self.assertEqual(response.status_code, 202)
                if exposes:
                    self.assertIsNotNone(response.json()["reset_url"])
                    self.assertEqual(response.json()["reset_url"], self.provider.deliveries[-1]["reset_url"])
                else:
                    self.assertIsNone(response.json()["reset_url"])

        self.settings = PasswordResetSettings(
            frontend_password_reset_url="http://frontend.test/reset-password",
            email_provider_mode="capture", expose_reset_url=True, token_ttl_minutes=30,
            resend_cooldown_seconds=60,
        )
        self.provider = CapturingResetProvider()
        self.app.dependency_overrides[password_reset_provider] = lambda: self.provider
        unknown = self.forgot("unknown@example.com")
        pending = self.forgot("pending@example.com")
        self.assertIsNone(unknown.json()["reset_url"])
        self.assertIsNone(pending.json()["reset_url"])
        self.assertEqual(self.provider.deliveries, [])

    def test_raw_token_and_url_do_not_appear_in_logs_or_audit_details(self):
        self.settings = PasswordResetSettings(
            frontend_password_reset_url="http://frontend.test/reset-password",
            email_provider_mode="capture", expose_reset_url=True, token_ttl_minutes=30,
            resend_cooldown_seconds=60,
        )
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            response = self.forgot()
        finally:
            root.removeHandler(handler)
        url = response.json()["reset_url"]
        raw_token = parse_qs(urlparse(url).query)["token"][0]
        audit_details = [audit.method_json for audit in self.audits()]
        self.assert_no_secret_text(audit_details, raw_token, url, "Authorization", "Bearer")
        self.assert_no_secret_text(stream.getvalue(), raw_token, url, "Authorization", "Bearer")

    def test_validate_valid_token_and_does_not_consume_or_expose_identity(self):
        self.settings = PasswordResetSettings(
            frontend_password_reset_url="http://frontend.test/reset-password",
            email_provider_mode="capture", expose_reset_url=True, token_ttl_minutes=30,
            resend_cooldown_seconds=60,
        )
        forgot = self.forgot()
        raw_token = parse_qs(urlparse(forgot.json()["reset_url"]).query)["token"][0]
        row = self.token_rows()[0]

        response = self.validate_token(raw_token)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["valid"], True)
        self.assertIn("expires_at", body)
        self.assertNotIn("user", str(body).lower())
        self.assertNotIn("email", str(body).lower())
        self.assertNotIn(row.token_hash, str(body))
        self.db.refresh(row)
        self.assertIsNone(row.consumed_at)
        self.assertIsNone(row.invalidated_at)

    def test_validate_invalid_malformed_expired_consumed_and_invalidated_tokens(self):
        now = datetime.now(timezone.utc)
        expired_raw = "expired-token-with-enough-length-0123456789"
        consumed_raw = "consumed-token-with-enough-length-0123456789"
        invalidated_raw = "invalidated-token-with-enough-length-0123456789"
        self.add_reset_token(
            raw_token=expired_raw,
            expires_at=now - timedelta(seconds=1),
        )
        self.add_reset_token(
            raw_token=consumed_raw,
            consumed_at=now - timedelta(minutes=1),
        )
        self.add_reset_token(
            raw_token=invalidated_raw,
            invalidated_at=now - timedelta(minutes=1),
        )
        cases = [
            ("unknown", "unknown-token-with-enough-length-0123456789", "invalid"),
            ("short", "short", "invalid"),
            ("large", "x" * 600, "invalid"),
            ("expired", expired_raw, "expired"),
            ("consumed", consumed_raw, "consumed"),
            ("invalidated", invalidated_raw, "invalid"),
        ]
        for label, raw_token, code in cases:
            with self.subTest(label=label):
                response = self.validate_token(raw_token)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json(),
                    {
                        "detail": {
                            "message": "Password reset link is not valid.",
                            "code": code,
                        }
                    },
                )
                self.assertNotIn("email", str(response.json()).lower())

    def test_database_failure_rolls_back_token_invalidation_and_audit(self):
        old = self.add_reset_token(
            token_hash="e" * 64,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )

        with patch.object(self.db, "commit", side_effect=RuntimeError("sql secret detail")):
            response = self.forgot()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Password reset request failed."})
        self.db.expire_all()
        old = self.db.get(PasswordResetToken, old.password_reset_token_id)
        self.assertIsNone(old.invalidated_at)
        self.assertEqual(len(self.token_rows()), 1)
        self.assertEqual(self.audits(), [])
        self.assert_no_secret_text(response.json(), "sql secret detail")

    def test_settings_fail_closed_for_unknown_provider_and_unsafe_bounds(self):
        cases = [
            {"PASSWORD_RESET_EMAIL_PROVIDER": "smtp"},
            {"PASSWORD_RESET_TOKEN_TTL_MINUTES": "0"},
            {"PASSWORD_RESET_RESEND_COOLDOWN_SECONDS": "0"},
            {"PASSWORD_RESET_TOKEN_TTL_MINUTES": "not-an-int"},
        ]
        for env in cases:
            with self.subTest(env=env):
                clean = {
                    "PASSWORD_RESET_EMAIL_PROVIDER": "noop",
                    "PASSWORD_RESET_TOKEN_TTL_MINUTES": "30",
                    "PASSWORD_RESET_RESEND_COOLDOWN_SECONDS": "60",
                    "PASSWORD_RESET_EXPOSE_URL": "false",
                }
                clean.update(env)
                with patch.dict(os.environ, clean, clear=False):
                    with self.assertRaises(PasswordResetConfigurationError):
                        get_password_reset_settings()

    def test_openapi_reset_routes_security_inventory(self):
        schema = self.app.openapi()
        paths = schema["paths"]
        self.assertIn("/api/v1/auth/password/forgot", paths)
        self.assertNotIn("security", paths["/api/v1/auth/password/forgot"]["post"])
        self.assertIn("/api/v1/auth/password/reset/validate", paths)
        self.assertNotIn("security", paths["/api/v1/auth/password/reset/validate"]["post"])
        self.assertIn("/api/v1/auth/password/change", paths)
        self.assertTrue(paths["/api/v1/auth/password/change"]["post"]["security"])
        self.assertIn("/api/v1/auth/signin", paths)
        self.assertNotIn("security", paths["/api/v1/auth/signin"]["post"])
        self.assertIn("/api/v1/auth/activation/validate", paths)
        self.assertNotIn("security", paths["/api/v1/auth/activation/validate"]["post"])
        self.assertIn("/api/v1/auth/activation/complete", paths)
        self.assertNotIn("security", paths["/api/v1/auth/activation/complete"]["post"])
        self.assertNotIn("/api/v1/auth/password/reset/complete", paths)


if __name__ == "__main__":
    unittest.main()

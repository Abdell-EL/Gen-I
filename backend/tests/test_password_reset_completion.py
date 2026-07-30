from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import logging
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin_routes import router as admin_router
from app.auth_routes import router as auth_router
from app.config import AuthSettings, get_auth_settings
from app.database import Base, get_db
from app.models import AuditLog, PasswordResetToken, User
from app.security import (
    MAX_PASSWORD_BYTES,
    create_access_token,
    decode_and_validate_access_token,
    hash_password,
    verify_password,
)
from app.services.password_reset_service import (
    PasswordResetPersistenceError,
    complete_password_reset,
    token_digest,
)


SIGNING_KEY = "reset-completion-test-key-0123456789abcdef0123456789abcdef0123456789"
SETTINGS = AuthSettings(
    jwt_secret=SIGNING_KEY,
    jwt_issuer="reset-completion-tests",
    jwt_audience="reset-completion-client",
    access_token_minutes=15,
)
SUCCESS_MESSAGE = "Mot de passe réinitialisé avec succès."
INVALID_RESET = {
    "detail": {
        "message": "Password reset link is not valid.",
        "code": "invalid",
    }
}


class PasswordResetCompletionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = self.add_user(
            "Reset User",
            "reset@example.com",
            "old-password",
            token_version=0,
        )
        self.other_user = self.add_user(
            "Other User",
            "other-reset@example.com",
            "other-password",
        )
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")
        app.include_router(admin_router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_auth_settings] = lambda: SETTINGS
        self.settings_patch = patch(
            "app.auth_dependencies.get_auth_settings", return_value=SETTINGS
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
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
        token_version: int = 0,
    ) -> User:
        user = User(
            full_name=full_name,
            email=email,
            role="agent",
            is_active=is_active,
            activation_status=activation_status,
            password_hash=hash_password(password) if password is not None else None,
            token_version=token_version,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def add_reset_token(
        self,
        *,
        user: User | None = None,
        raw_token: str = "valid-reset-token-with-enough-length-0123456789",
        token_hash: str | None = None,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
        consumed_at: datetime | None = None,
        invalidated_at: datetime | None = None,
        delivery_status: str = "sent",
    ) -> PasswordResetToken:
        token = PasswordResetToken(
            user_id=(user or self.user).user_id,
            token_hash=token_hash or token_digest(raw_token),
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

    def token_for(self, user: User | None = None, *, version: int | None = None) -> str:
        target = user or self.user
        return create_access_token(
            signing_key=SIGNING_KEY,
            issuer=SETTINGS.jwt_issuer,
            audience=SETTINGS.jwt_audience,
            lifetime=timedelta(minutes=5),
            subject=str(target.user_id),
            version=target.token_version if version is None else version,
        )

    def post_complete(
        self,
        raw_token: str,
        *,
        password: str = "new-password",
        confirmation: str | None = None,
    ):
        return self.client.post(
            "/api/v1/auth/password/reset/complete",
            json={
                "token": raw_token,
                "password": password,
                "password_confirmation": password if confirmation is None else confirmation,
            },
        )

    def audits(self, user: User | None = None) -> list[AuditLog]:
        return list(
            self.db.execute(
                select(AuditLog)
                .where(AuditLog.user_id == (user or self.user).user_id)
                .order_by(AuditLog.audit_id)
            ).scalars()
        )

    def assert_no_secret_text(self, value: object, *secrets: str) -> None:
        text = str(value)
        for secret in secrets:
            self.assertNotIn(secret, text)

    def test_success_replaces_password_consumes_token_versions_and_invalidates_sessions(self):
        raw_token = "successful-reset-token-with-enough-length-0123456789"
        used = self.add_reset_token(raw_token=raw_token)
        outstanding = self.add_reset_token(raw_token="other-outstanding-token-0123456789")
        consumed_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        consumed = self.add_reset_token(
            raw_token="already-consumed-token-0123456789",
            consumed_at=consumed_at,
        )
        invalidated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=4)
        invalidated = self.add_reset_token(
            raw_token="already-invalidated-token-0123456789",
            invalidated_at=invalidated_at,
        )
        other = self.add_reset_token(
            user=self.other_user,
            raw_token="other-user-token-0123456789",
        )
        old_hash = self.user.password_hash
        old_jwt = self.token_for(version=0)

        response = self.post_complete(raw_token, password="new-password")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "message": SUCCESS_MESSAGE,
                "reauthentication_required": True,
            },
        )
        self.assertNotIn("access_token", response.json())
        self.assertNotIn("user", response.json())
        self.db.refresh(self.user)
        for row in (used, outstanding, consumed, invalidated, other):
            self.db.refresh(row)
        self.assertNotEqual(self.user.password_hash, old_hash)
        self.assertFalse(verify_password("old-password", self.user.password_hash))
        self.assertTrue(verify_password("new-password", self.user.password_hash))
        self.assertEqual(self.user.token_version, 1)
        self.assertIsNotNone(used.consumed_at)
        self.assertIsNone(used.invalidated_at)
        self.assertIsNotNone(outstanding.invalidated_at)
        self.assertEqual(consumed.consumed_at, consumed_at)
        self.assertIsNone(consumed.invalidated_at)
        self.assertEqual(invalidated.invalidated_at, invalidated_at)
        self.assertIsNone(other.invalidated_at)

        audit_rows = self.audits()
        self.assertEqual(len(audit_rows), 1)
        audit = audit_rows[0]
        self.assertEqual(audit.action, "password_reset_completed")
        self.assertEqual(
            audit.method_json,
            {"credential_changed": True, "reauthentication_required": True},
        )
        self.assert_no_secret_text(
            audit.method_json,
            raw_token,
            used.token_hash,
            "new-password",
            self.user.password_hash,
            old_jwt,
            "Authorization",
            "Bearer",
            "reset-password",
        )

        stale = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {old_jwt}"},
        )
        self.assertEqual(stale.status_code, 401)
        old_signin = self.client.post(
            "/api/v1/auth/signin",
            json={"email": self.user.email, "password": "old-password"},
        )
        self.assertEqual(old_signin.status_code, 401)
        new_signin = self.client.post(
            "/api/v1/auth/signin",
            json={"email": self.user.email, "password": "new-password"},
        )
        self.assertEqual(new_signin.status_code, 200)
        claims = decode_and_validate_access_token(
            new_signin.json()["access_token"],
            signing_key=SIGNING_KEY,
            issuer=SETTINGS.jwt_issuer,
            audience=SETTINGS.jwt_audience,
        )
        self.assertEqual(claims["ver"], 1)

    def test_valid_unicode_password_is_preserved_without_trimming(self):
        raw_token = "unicode-reset-token-with-enough-length-0123456789"
        self.add_reset_token(raw_token=raw_token)
        unicode_password = "  nouveau mot de passe été 🔐  "

        response = self.post_complete(raw_token, password=unicode_password)

        self.assertEqual(response.status_code, 200)
        self.db.refresh(self.user)
        self.assertTrue(verify_password(unicode_password, self.user.password_hash))
        self.assertFalse(verify_password(unicode_password.strip(), self.user.password_hash))

    def test_password_validation_failures_do_not_mutate_state(self):
        cases = [
            (
                "confirmation mismatch",
                "mismatch-token-with-enough-length-0123456789",
                "new-password",
                "different-password",
                "Password confirmation does not match.",
            ),
            (
                "empty password",
                "empty-token-with-enough-length-0123456789",
                "",
                "",
                "Password must not be empty.",
            ),
            (
                "same password reuse",
                "reuse-token-with-enough-length-0123456789",
                "old-password",
                "old-password",
                "New password must be different from current password.",
            ),
        ]
        for label, raw_token, password, confirmation, expected_detail in cases:
            with self.subTest(label=label):
                token = self.add_reset_token(raw_token=raw_token)
                original_hash = self.user.password_hash
                response = self.post_complete(
                    raw_token,
                    password=password,
                    confirmation=confirmation,
                )

                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"], expected_detail)
                self.db.refresh(self.user)
                self.db.refresh(token)
                self.assertEqual(self.user.password_hash, original_hash)
                self.assertEqual(self.user.token_version, 0)
                self.assertIsNone(token.consumed_at)
                self.assertIsNone(token.invalidated_at)
                self.assertEqual(self.audits(), [])

    def test_oversized_utf8_password_is_rejected_without_secret_echo(self):
        raw_token = "oversized-reset-token-with-enough-length-0123456789"
        token = self.add_reset_token(raw_token=raw_token)
        oversized = "é" * (MAX_PASSWORD_BYTES // 2 + 1)
        original_hash = self.user.password_hash

        response = self.post_complete(raw_token, password=oversized)

        self.assertEqual(response.status_code, 422)
        self.assertIn(f"{MAX_PASSWORD_BYTES}-byte UTF-8 limit", response.json()["detail"])
        self.assert_no_secret_text(response.json(), oversized, raw_token)
        self.db.refresh(self.user)
        self.db.refresh(token)
        self.assertEqual(self.user.password_hash, original_hash)
        self.assertEqual(self.user.token_version, 0)
        self.assertIsNone(token.consumed_at)

    def test_invalid_expired_consumed_and_invalidated_tokens_fail_safely(self):
        now = datetime.now(timezone.utc)
        expired_raw = "expired-complete-token-with-enough-length-0123456789"
        consumed_raw = "consumed-complete-token-with-enough-length-0123456789"
        invalidated_raw = "invalidated-complete-token-with-enough-length-0123456789"
        self.add_reset_token(raw_token=expired_raw, expires_at=now - timedelta(seconds=1))
        self.add_reset_token(raw_token=consumed_raw, consumed_at=now - timedelta(minutes=1))
        self.add_reset_token(raw_token=invalidated_raw, invalidated_at=now - timedelta(minutes=1))
        cases = [
            ("unknown", "unknown-complete-token-with-enough-length-0123456789", "invalid"),
            ("short", "short", "invalid"),
            ("large", "x" * 600, "invalid"),
            ("expired", expired_raw, "expired"),
            ("consumed", consumed_raw, "consumed"),
            ("invalidated", invalidated_raw, "invalid"),
        ]
        original_hash = self.user.password_hash
        for label, raw_token, code in cases:
            with self.subTest(label=label):
                response = self.post_complete(raw_token, password="new-password")
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
        self.db.refresh(self.user)
        self.assertEqual(self.user.password_hash, original_hash)
        self.assertEqual(self.user.token_version, 0)
        self.assertEqual(self.audits(), [])

    def test_ineligible_user_state_does_not_consume_token_or_change_password(self):
        pending = self.add_user(
            "Pending", "pending-reset@example.com", "pending-password", activation_status="pending"
        )
        disabled = self.add_user(
            "Disabled", "disabled-reset@example.com", "disabled-password", is_active=False
        )
        no_password = self.add_user("No Password", "no-pw-reset@example.com", None)
        deleted = self.add_user("Deleted", "deleted-reset@example.com", "deleted-password")
        cases = [
            (pending, "pending-user-reset-token-with-enough-length-0123456789"),
            (disabled, "disabled-user-reset-token-with-enough-length-0123456789"),
            (no_password, "no-password-user-reset-token-with-enough-length-0123456789"),
            (deleted, "deleted-user-reset-token-with-enough-length-0123456789"),
        ]
        deleted_token = None
        for user, raw_token in cases:
            token = self.add_reset_token(user=user, raw_token=raw_token)
            if user is deleted:
                deleted_token = token
                self.db.delete(user)
                self.db.commit()
            response = self.post_complete(raw_token, password="new-password")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), INVALID_RESET)
            self.db.refresh(token)
            self.assertIsNone(token.consumed_at)
            self.assertIsNone(token.invalidated_at)
            if user is not deleted:
                self.db.refresh(user)
                self.assertEqual(user.token_version, 0)
        self.assertIsNotNone(deleted_token)

    def test_duplicate_sequential_use_only_succeeds_once(self):
        raw_token = "duplicate-use-reset-token-with-enough-length-0123456789"
        token = self.add_reset_token(raw_token=raw_token)

        first = self.post_complete(raw_token, password="new-password")
        second = self.post_complete(raw_token, password="another-password")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["detail"]["code"], "consumed")
        self.db.refresh(self.user)
        self.db.refresh(token)
        self.assertEqual(self.user.token_version, 1)
        self.assertTrue(verify_password("new-password", self.user.password_hash))
        self.assertIsNotNone(token.consumed_at)
        self.assertEqual(len(self.audits()), 1)

    def test_hashing_failure_rolls_back_all_state_and_has_safe_exception_text(self):
        raw_token = "hash-failure-reset-token-with-enough-length-0123456789"
        token = self.add_reset_token(raw_token=raw_token)
        original_hash = self.user.password_hash

        with patch(
            "app.services.password_reset_service.hash_password",
            side_effect=RuntimeError("hash failed with supplied password"),
        ):
            with self.assertRaises(PasswordResetPersistenceError) as context:
                complete_password_reset(
                    self.db,
                    raw_token=raw_token,
                    password="new-password",
                    password_confirmation="new-password",
                )

        self.assert_no_secret_text(str(context.exception), raw_token, "new-password")
        self.db.refresh(self.user)
        self.db.refresh(token)
        self.assertEqual(self.user.password_hash, original_hash)
        self.assertEqual(self.user.token_version, 0)
        self.assertIsNone(token.consumed_at)
        self.assertEqual(self.audits(), [])

    def test_audit_and_commit_failures_roll_back_without_false_success(self):
        cases = [
            ("audit", "audit-failure-reset-token-with-enough-length-0123456789"),
            ("commit", "commit-failure-reset-token-with-enough-length-0123456789"),
        ]
        for label, raw_token in cases:
            with self.subTest(label=label):
                token = self.add_reset_token(raw_token=raw_token)
                original_hash = self.user.password_hash
                if label == "audit":
                    manager = patch(
                        "app.services.password_reset_service._audit",
                        side_effect=RuntimeError("audit failed"),
                    )
                else:
                    manager = patch.object(self.db, "commit", side_effect=RuntimeError("sql failed"))
                with manager:
                    with self.assertRaises(PasswordResetPersistenceError) as context:
                        complete_password_reset(
                            self.db,
                            raw_token=raw_token,
                            password=f"{label}-new-password",
                            password_confirmation=f"{label}-new-password",
                        )
                self.assert_no_secret_text(str(context.exception), raw_token, f"{label}-new-password")
                self.db.expire_all()
                user = self.db.get(User, self.user.user_id)
                token = self.db.get(PasswordResetToken, token.password_reset_token_id)
                self.assertEqual(user.password_hash, original_hash)
                self.assertEqual(user.token_version, 0)
                self.assertIsNone(token.consumed_at)
                self.assertIsNone(token.invalidated_at)
                self.assertEqual(self.audits(), [])

    def test_api_responses_audits_and_logs_do_not_expose_secrets(self):
        raw_token = "secret-safety-reset-token-with-enough-length-0123456789"
        self.add_reset_token(raw_token=raw_token)
        password = "private-new-password"
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            response = self.post_complete(raw_token, password=password)
        finally:
            root.removeHandler(handler)

        self.assertEqual(response.status_code, 200)
        self.assert_no_secret_text(
            response.json(),
            raw_token,
            password,
            token_digest(raw_token),
            "password_hash",
            "Authorization",
            "Bearer",
        )
        self.assert_no_secret_text(
            stream.getvalue(),
            raw_token,
            password,
            token_digest(raw_token),
            "password_hash",
            "Authorization",
            "Bearer",
        )
        audit = self.audits()[0]
        self.assert_no_secret_text(
            audit.method_json,
            raw_token,
            password,
            token_digest(raw_token),
            self.user.password_hash,
            "reset-password",
            "Authorization",
            "Bearer",
        )

    def test_openapi_declares_public_reset_completion(self):
        schema = self.app.openapi()
        paths = schema["paths"]
        self.assertIn("/api/v1/auth/password/reset/complete", paths)
        self.assertNotIn("security", paths["/api/v1/auth/password/reset/complete"]["post"])
        self.assertIn("/api/v1/auth/password/forgot", paths)
        self.assertNotIn("security", paths["/api/v1/auth/password/forgot"]["post"])
        self.assertIn("/api/v1/auth/password/reset/validate", paths)
        self.assertNotIn("security", paths["/api/v1/auth/password/reset/validate"]["post"])
        self.assertIn("/api/v1/auth/password/change", paths)
        self.assertTrue(paths["/api/v1/auth/password/change"]["post"].get("security"))
        self.assertIn("/api/v1/admin/users/{user_id}/reset-password", paths)
        self.assertTrue(paths["/api/v1/admin/users/{user_id}/reset-password"]["post"].get("security"))


if __name__ == "__main__":
    unittest.main()

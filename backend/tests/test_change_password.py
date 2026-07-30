from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import logging
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
from app.services.password_change_service import (
    ChangePasswordPersistenceError,
    IncorrectCurrentPasswordError,
    change_own_password,
)


SIGNING_KEY = "change-password-test-key-0123456789abcdef0123456789abcdef0123456789abcdef"
SETTINGS = AuthSettings(
    jwt_secret=SIGNING_KEY,
    jwt_issuer="change-password-tests",
    jwt_audience="change-password-client",
    access_token_minutes=15,
)


class ChangePasswordTests(unittest.TestCase):
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
            "Change User",
            "change@example.com",
            "agent",
            "old-password",
            token_version=2,
        )
        self.other_user = self.add_user(
            "Other User",
            "other@example.com",
            "agent",
            "other-password",
        )
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")
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
        role: str,
        password: str,
        *,
        is_active: bool = True,
        activation_status: str = "active",
        token_version: int = 0,
    ) -> User:
        user = User(
            full_name=full_name,
            email=email,
            role=role,
            is_active=is_active,
            activation_status=activation_status,
            password_hash=hash_password(password),
            token_version=token_version,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

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

    def bearer(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.token_for()}"}

    def post_change(
        self,
        *,
        current_password: str = "old-password",
        new_password: str = "new-password",
        confirmation: str | None = None,
        token: str | None = None,
    ):
        return self.client.post(
            "/api/v1/auth/password/change",
            json={
                "current_password": current_password,
                "new_password": new_password,
                "new_password_confirmation": new_password if confirmation is None else confirmation,
            },
            headers=self.bearer(token),
        )

    def audits(self) -> list[AuditLog]:
        return list(self.db.execute(select(AuditLog).order_by(AuditLog.audit_id)).scalars())

    def add_reset_token(
        self,
        *,
        user: User | None = None,
        token_hash: str,
        consumed_at: datetime | None = None,
        invalidated_at: datetime | None = None,
    ) -> PasswordResetToken:
        row = PasswordResetToken(
            user_id=(user or self.user).user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            consumed_at=consumed_at,
            invalidated_at=invalidated_at,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def assert_no_secret_text(self, value: object, *secrets: str) -> None:
        text = str(value)
        for secret in secrets:
            self.assertNotIn(secret, text)

    def test_valid_password_change_forces_reauthentication_and_new_signin_version(self):
        old_token = self.token_for()
        response = self.post_change(token=old_token, new_password="new-password")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "message": "Mot de passe modifié avec succès.",
                "reauthentication_required": True,
            },
        )
        self.assertNotIn("access_token", response.json())
        self.assert_no_secret_text(response.json(), "old-password", "new-password")

        self.db.refresh(self.user)
        self.assertEqual(self.user.token_version, 3)
        self.assertFalse(verify_password("old-password", self.user.password_hash))
        self.assertTrue(verify_password("new-password", self.user.password_hash))

        stale = self.client.get("/api/v1/auth/me", headers=self.bearer(old_token))
        self.assertEqual(stale.status_code, 401)
        self.assertEqual(stale.json(), {"detail": "Not authenticated."})
        self.assertEqual(stale.headers.get("www-authenticate"), "Bearer")

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
        self.assertEqual(claims["ver"], 3)

    def test_success_invalidates_only_outstanding_reset_tokens_and_audits_safely(self):
        consumed_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        previous_invalidated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2)
        unused = self.add_reset_token(token_hash="a" * 64)
        consumed = self.add_reset_token(token_hash="b" * 64, consumed_at=consumed_at)
        invalidated = self.add_reset_token(
            token_hash="c" * 64,
            invalidated_at=previous_invalidated_at,
        )
        other = self.add_reset_token(user=self.other_user, token_hash="d" * 64)

        response = self.post_change(new_password="safe-new-password")

        self.assertEqual(response.status_code, 200)
        self.db.refresh(self.user)
        for row in (unused, consumed, invalidated, other):
            self.db.refresh(row)
        self.assertEqual(unused.invalidated_at, self.user.updated_at)
        self.assertEqual(consumed.consumed_at, consumed_at)
        self.assertIsNone(consumed.invalidated_at)
        self.assertEqual(invalidated.invalidated_at, previous_invalidated_at)
        self.assertIsNone(other.invalidated_at)

        audit = self.audits()[-1]
        self.assertEqual(audit.user_id, self.user.user_id)
        self.assertEqual(audit.entity_id, self.user.user_id)
        self.assertEqual(audit.action, "password_changed")
        self.assertEqual(audit.entity_type, "user")
        self.assertEqual(
            audit.method_json,
            {"credential_changed": True, "reauthentication_required": True},
        )
        self.assert_no_secret_text(
            audit.method_json,
            "old-password",
            "safe-new-password",
            "password_hash",
            "Authorization",
            "Bearer",
            "reset",
            "token",
            "url",
        )

    def test_valid_unicode_password_is_preserved_without_trimming(self):
        unicode_password = "  nouveau mot de passe été 🔐  "

        response = self.post_change(new_password=unicode_password)

        self.assertEqual(response.status_code, 200)
        self.db.refresh(self.user)
        self.assertTrue(verify_password(unicode_password, self.user.password_hash))
        self.assertFalse(verify_password(unicode_password.strip(), self.user.password_hash))

    def test_validation_failures_do_not_increment_version_or_invalidate_token(self):
        cases = [
            (
                "incorrect current password",
                {"current_password": "wrong-password", "new_password": "new-password"},
                400,
                "Current password is incorrect.",
            ),
            (
                "confirmation mismatch",
                {"new_password": "new-password", "confirmation": "different-password"},
                422,
                "New password confirmation does not match.",
            ),
            (
                "empty new password",
                {"new_password": "", "confirmation": ""},
                422,
                "New password must not be empty.",
            ),
            (
                "same password reuse",
                {"new_password": "old-password"},
                422,
                "New password must be different from current password.",
            ),
        ]
        for label, kwargs, expected_status, expected_detail in cases:
            with self.subTest(label=label):
                token = self.token_for()
                reset_token = self.add_reset_token(token_hash=(label[0] * 64)[:64])
                response = self.post_change(token=token, **kwargs)

                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json()["detail"], expected_detail)
                self.db.refresh(self.user)
                self.db.refresh(reset_token)
                self.assertEqual(self.user.token_version, 2)
                self.assertTrue(verify_password("old-password", self.user.password_hash))
                self.assertIsNone(reset_token.invalidated_at)
                self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.bearer(token)).status_code, 200)

    def test_oversized_utf8_password_is_rejected_without_secret_echo(self):
        oversized = "é" * (MAX_PASSWORD_BYTES // 2 + 1)

        response = self.post_change(new_password=oversized)

        self.assertEqual(response.status_code, 422)
        self.assertIn(f"{MAX_PASSWORD_BYTES}-byte UTF-8 limit", response.json()["detail"])
        self.assert_no_secret_text(response.json(), oversized, "old-password")
        self.db.refresh(self.user)
        self.assertEqual(self.user.token_version, 2)
        self.assertTrue(verify_password("old-password", self.user.password_hash))

    def test_pending_and_disabled_users_are_rejected_by_current_user_dependency(self):
        pending = self.add_user(
            "Pending User",
            "pending@example.com",
            "agent",
            "pending-password",
            activation_status="pending",
        )
        disabled = self.add_user(
            "Disabled User",
            "disabled@example.com",
            "agent",
            "disabled-password",
            is_active=False,
        )
        for user, password in ((pending, "pending-password"), (disabled, "disabled-password")):
            with self.subTest(user=user.email):
                response = self.client.post(
                    "/api/v1/auth/password/change",
                    json={
                        "current_password": password,
                        "new_password": "new-password",
                        "new_password_confirmation": "new-password",
                    },
                    headers=self.bearer(self.token_for(user)),
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": "Not authenticated."})
                self.db.refresh(user)
                self.assertEqual(user.token_version, 0)
                self.assertTrue(verify_password(password, user.password_hash))

    def test_hashing_failure_rolls_back_all_state_and_has_safe_exception_text(self):
        original_hash = self.user.password_hash
        token = self.add_reset_token(token_hash="e" * 64)

        with patch(
            "app.services.password_change_service.hash_password",
            side_effect=RuntimeError("hash failed"),
        ):
            with self.assertRaises(ChangePasswordPersistenceError) as context:
                change_own_password(
                    self.db,
                    user_id=self.user.user_id,
                    current_password="old-password",
                    new_password="new-password",
                )

        self.assert_no_secret_text(str(context.exception), "old-password", "new-password")
        self.db.refresh(self.user)
        self.db.refresh(token)
        self.assertEqual(self.user.password_hash, original_hash)
        self.assertEqual(self.user.token_version, 2)
        self.assertIsNone(token.invalidated_at)
        self.assertEqual(self.audits(), [])

    def test_commit_failure_rolls_back_all_state_and_no_false_success_audit(self):
        original_hash = self.user.password_hash
        token = self.add_reset_token(token_hash="f" * 64)

        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaises(ChangePasswordPersistenceError) as context:
                change_own_password(
                    self.db,
                    user_id=self.user.user_id,
                    current_password="old-password",
                    new_password="new-password",
                )

        self.assert_no_secret_text(str(context.exception), "old-password", "new-password")
        self.db.expire_all()
        user = self.db.get(User, self.user.user_id)
        reset_token = self.db.get(PasswordResetToken, token.password_reset_token_id)
        self.assertEqual(user.password_hash, original_hash)
        self.assertEqual(user.token_version, 2)
        self.assertIsNone(reset_token.invalidated_at)
        self.assertEqual(self.audits(), [])

    def test_repeated_service_call_with_old_password_fails_after_first_change(self):
        change_own_password(
            self.db,
            user_id=self.user.user_id,
            current_password="old-password",
            new_password="new-password-one",
        )

        with self.assertRaises(IncorrectCurrentPasswordError):
            change_own_password(
                self.db,
                user_id=self.user.user_id,
                current_password="old-password",
                new_password="new-password-two",
            )
        self.db.refresh(self.user)
        self.assertEqual(self.user.token_version, 3)
        self.assertTrue(verify_password("new-password-one", self.user.password_hash))

    def test_service_uses_for_update_before_password_verification(self):
        user = SimpleNamespace(
            user_id=1,
            is_active=True,
            activation_status="active",
            password_hash="old-hash",
            token_version=4,
        )

        class UserResult:
            def scalar_one_or_none(self):
                return user

        class TokenResult:
            def scalars(self):
                return []

        db = MagicMock()
        db.execute.side_effect = [UserResult(), TokenResult()]
        with (
            patch("app.services.password_change_service.verify_password", side_effect=[True, False]),
            patch("app.services.password_change_service.hash_password", return_value="new-hash"),
        ):
            change_own_password(
                db,
                user_id=user.user_id,
                current_password="old-password",
                new_password="new-password",
            )

        first_statement = db.execute.call_args_list[0].args[0]
        self.assertIsNotNone(first_statement._for_update_arg)
        self.assertEqual(user.password_hash, "new-hash")
        self.assertEqual(user.token_version, 5)
        db.commit.assert_called_once_with()

    def test_api_responses_audits_and_logs_do_not_expose_secrets(self):
        secret_current = "old-password"
        secret_new = "highly-secret-new-password"
        bearer = self.token_for()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            response = self.post_change(
                token=bearer,
                current_password="wrong-password",
                new_password=secret_new,
            )
        finally:
            root.removeHandler(handler)

        self.assertEqual(response.status_code, 400)
        self.assert_no_secret_text(
            response.json(),
            secret_current,
            secret_new,
            "wrong-password",
            bearer,
            "Authorization",
            "password_hash",
            "reset-token",
            "reset-password",
        )
        self.assert_no_secret_text(
            stream.getvalue(),
            secret_current,
            secret_new,
            "wrong-password",
            bearer,
            "Authorization",
            "password_hash",
            "reset-token",
            "reset-password",
        )
        self.assertEqual(self.audits(), [])

    def test_openapi_declares_authenticated_change_password_only_no_public_reset_flow(self):
        schema = self.app.openapi()
        paths = schema["paths"]
        self.assertIn("/api/v1/auth/password/change", paths)
        self.assertTrue(paths["/api/v1/auth/password/change"]["post"]["security"])
        self.assertIn("/api/v1/auth/signin", paths)
        self.assertIn("/api/v1/auth/activation/validate", paths)
        self.assertIn("/api/v1/auth/activation/complete", paths)
        forbidden = [
            path for path in paths
            if "forgot-password" in path.lower()
            or (
                "reset" in path.lower()
                and "/api/v1/admin/users/{user_id}/reset-password" not in path
            )
        ]
        self.assertEqual(forbidden, [])


if __name__ == "__main__":
    unittest.main()

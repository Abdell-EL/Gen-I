from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_routes import router as auth_router
from app.config import AuthSettings, get_auth_settings
from app.database import get_db
from app.security import create_access_token
from app.services.auth_service import (
    GENERIC_SIGNIN_ERROR,
    InvalidCredentialsError,
    authenticate_user,
    normalize_email,
)


SIGNING_KEY = "auth-route-test-key-0123456789abcdef0123456789abcdef0123456789abcdef"
SETTINGS = AuthSettings(
    jwt_secret=SIGNING_KEY,
    jwt_issuer="auth-test-issuer",
    jwt_audience="auth-test-audience",
    access_token_minutes=15,
)


def make_user(**overrides):
    values = {
        "user_id": 1,
        "full_name": "Test Admin",
        "email": "admin@example.com",
        "password_hash": "encoded-password-hash",
        "role": "admin",
        "is_active": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class AuthenticationServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.user = make_user()

    def test_successful_signin(self):
        with (
            patch("app.services.auth_service.find_user_by_email", return_value=self.user),
            patch("app.services.auth_service.verify_password", return_value=True),
            patch("app.services.auth_service.password_needs_rehash", return_value=False),
        ):
            result = authenticate_user(
                self.db,
                email="admin@example.com",
                password="correct-password",
            )

        self.assertIs(result, self.user)
        self.db.commit.assert_not_called()

    def test_wrong_password(self):
        with (
            patch("app.services.auth_service.find_user_by_email", return_value=self.user),
            patch("app.services.auth_service.verify_password", return_value=False),
        ):
            with self.assertRaises(InvalidCredentialsError) as context:
                authenticate_user(self.db, email=self.user.email, password="wrong")

        self.assertEqual(str(context.exception), GENERIC_SIGNIN_ERROR)

    def test_unknown_email(self):
        with patch("app.services.auth_service.find_user_by_email", return_value=None):
            with self.assertRaises(InvalidCredentialsError) as context:
                authenticate_user(self.db, email="unknown@example.com", password="wrong")

        self.assertEqual(str(context.exception), GENERIC_SIGNIN_ERROR)

    def test_missing_password_hash(self):
        user = make_user(password_hash=None)
        with patch("app.services.auth_service.find_user_by_email", return_value=user):
            with self.assertRaises(InvalidCredentialsError) as context:
                authenticate_user(self.db, email=user.email, password="password")

        self.assertEqual(str(context.exception), GENERIC_SIGNIN_ERROR)

    def test_inactive_user(self):
        user = make_user(is_active=False)
        with patch("app.services.auth_service.find_user_by_email", return_value=user):
            with self.assertRaises(InvalidCredentialsError) as context:
                authenticate_user(self.db, email=user.email, password="password")

        self.assertEqual(str(context.exception), GENERIC_SIGNIN_ERROR)

    def test_generic_identical_authentication_failure_behavior(self):
        errors = []
        cases = [
            (None, True),
            (make_user(password_hash=None), True),
            (make_user(is_active=False), True),
            (self.user, False),
        ]
        for user, password_valid in cases:
            with self.subTest(user=user, password_valid=password_valid):
                with (
                    patch("app.services.auth_service.find_user_by_email", return_value=user),
                    patch(
                        "app.services.auth_service.verify_password",
                        return_value=password_valid,
                    ),
                ):
                    with self.assertRaises(InvalidCredentialsError) as context:
                        authenticate_user(
                            self.db,
                            email="candidate@example.com",
                            password="candidate-password",
                        )
                errors.append((type(context.exception), str(context.exception)))

        self.assertEqual(
            errors,
            [(InvalidCredentialsError, GENERIC_SIGNIN_ERROR)] * len(cases),
        )

    def test_email_normalization(self):
        self.assertEqual(normalize_email("  User@Example.COM  "), "user@example.com")
        with (
            patch(
                "app.services.auth_service.find_user_by_email",
                return_value=self.user,
            ) as find_user,
            patch("app.services.auth_service.verify_password", return_value=True),
            patch("app.services.auth_service.password_needs_rehash", return_value=False),
        ):
            authenticate_user(
                self.db,
                email="  ADMIN@Example.COM  ",
                password="correct-password",
            )

        find_user.assert_called_once_with(self.db, "admin@example.com")

    def test_password_rehash_on_successful_login(self):
        with (
            patch("app.services.auth_service.find_user_by_email", return_value=self.user),
            patch("app.services.auth_service.verify_password", return_value=True),
            patch("app.services.auth_service.password_needs_rehash", return_value=True),
            patch("app.services.auth_service.hash_password", return_value="new-hash"),
        ):
            result = authenticate_user(
                self.db,
                email=self.user.email,
                password="correct-password",
            )

        self.assertIs(result, self.user)
        self.assertEqual(self.user.password_hash, "new-hash")
        self.db.add.assert_called_once_with(self.user)
        self.db.commit.assert_called_once_with()
        self.db.refresh.assert_called_once_with(self.user)


class AuthenticationRouteTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.user = make_user()
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_auth_settings] = lambda: SETTINGS
        self.settings_patch = patch(
            "app.auth_dependencies.get_auth_settings",
            return_value=SETTINGS,
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.client = TestClient(app)

    def create_token(self, *, lifetime=timedelta(minutes=5), subject="1"):
        return create_access_token(
            signing_key=SIGNING_KEY,
            issuer=SETTINGS.jwt_issuer,
            audience=SETTINGS.jwt_audience,
            lifetime=lifetime,
            subject=subject,
        )

    def test_successful_signin_and_no_password_hash_response(self):
        with patch("app.auth_routes.authenticate_user", return_value=self.user):
            response = self.client.post(
                "/api/v1/auth/signin",
                json={"email": "admin@example.com", "password": "correct-password"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["token_type"], "bearer")
        self.assertEqual(body["expires_in"], 900)
        self.assertEqual(
            body["user"],
            {
                "id": 1,
                "full_name": "Test Admin",
                "email": "admin@example.com",
                "role": "admin",
                "is_active": True,
            },
        )
        self.assertNotIn("password_hash", body)
        self.assertNotIn("password_hash", body["user"])

    def test_successful_me_and_no_password_hash_response(self):
        self.db.get.return_value = self.user
        response = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {self.create_token()}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.user.user_id)
        self.assertNotIn("password_hash", response.json())
        self.db.get.assert_called_once()

    def assert_generic_unauthorized(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Invalid or missing authentication credentials."},
        )
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_missing_bearer_token(self):
        self.assert_generic_unauthorized(self.client.get("/api/v1/auth/me"))

    def test_malformed_token(self):
        response = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer malformed-token"},
        )
        self.assert_generic_unauthorized(response)

    def test_expired_token(self):
        response = self.client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": (
                    f"Bearer {self.create_token(lifetime=timedelta(seconds=-1))}"
                )
            },
        )
        self.assert_generic_unauthorized(response)

    def test_deleted_or_nonexistent_user(self):
        self.db.get.return_value = None
        response = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {self.create_token()}"},
        )
        self.assert_generic_unauthorized(response)

    def test_inactive_user(self):
        self.db.get.return_value = make_user(is_active=False)
        response = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {self.create_token()}"},
        )
        self.assert_generic_unauthorized(response)


if __name__ == "__main__":
    unittest.main()

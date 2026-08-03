from __future__ import annotations

import math
import os
import unittest
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_routes import RATE_LIMITED_MESSAGE, auth_rate_limiter, router as auth_router
from app.config import AuthRateLimitSettings, AuthSettings, RateLimitPolicy
from app.database import get_db
from app.services.auth_rate_limit_service import AuthRateLimiter

os.environ.setdefault("AUTH_JWT_SECRET", "x" * 64)
os.environ.setdefault("AUTH_JWT_ISSUER", "tests")
os.environ.setdefault("AUTH_JWT_AUDIENCE", "tests")
os.environ.setdefault("AUTH_ACCESS_TOKEN_MINUTES", "15")


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, int] = {}
        self.ttl: dict[str, int] = {}

    def eval(self, script: str, numkeys: int, *args: Any) -> list[int]:
        keys = list(args[:numkeys])
        policy_args = list(args[numkeys:])
        retry_after = 0
        blocked_index = 0
        for index in range(len(keys)):
            key = keys[index]
            limit = int(policy_args[index * 2])
            window = int(policy_args[index * 2 + 1])
            current = self.data.get(key, 0)
            if current >= limit:
                ttl_ms = self.ttl.get(key, window)
                retry_after = max(1, math.ceil(ttl_ms / 1))
                blocked_index = index + 1
                return [0, retry_after, blocked_index]
        for index in range(len(keys)):
            key = keys[index]
            window = int(policy_args[index * 2 + 1])
            self.data[key] = self.data.get(key, 0) + 1
            self.ttl[key] = window
        return [1, 0, 0]

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.data:
                self.data.pop(key, None)
                self.ttl.pop(key, None)
                removed += 1
        return removed

    def close(self) -> None:
        return None


def make_settings(**overrides: Any) -> AuthRateLimitSettings:
    defaults = {
        "enabled": True,
        "redis_url": "redis://localhost:6379/0",
        "namespace": "test-auth-rate-limit",
        "hmac_secret": "test-auth-hmac-secret",
        "redis_failure_mode": "fail_open",
        "signin_account": RateLimitPolicy(limit=2, window_seconds=60),
        "signin_ip": RateLimitPolicy(limit=2, window_seconds=60),
        "signin_combined": RateLimitPolicy(limit=2, window_seconds=60),
        "signin_cooldown_seconds": 60,
        "forgot_account": RateLimitPolicy(limit=3, window_seconds=60),
        "forgot_ip": RateLimitPolicy(limit=3, window_seconds=60),
        "reset_validate_token": RateLimitPolicy(limit=3, window_seconds=60),
        "reset_validate_ip": RateLimitPolicy(limit=3, window_seconds=60),
        "reset_complete_token": RateLimitPolicy(limit=3, window_seconds=60),
        "reset_complete_ip": RateLimitPolicy(limit=3, window_seconds=60),
        "activation_validate_token": RateLimitPolicy(limit=3, window_seconds=60),
        "activation_validate_ip": RateLimitPolicy(limit=3, window_seconds=60),
        "activation_complete_token": RateLimitPolicy(limit=3, window_seconds=60),
        "activation_complete_ip": RateLimitPolicy(limit=3, window_seconds=60),
        "invitation_resend_actor": RateLimitPolicy(limit=3, window_seconds=60),
        "invitation_resend_target": RateLimitPolicy(limit=3, window_seconds=60),
    }
    defaults.update(overrides)
    return AuthRateLimitSettings(**defaults)


class AuthRateLimitingTests(unittest.TestCase):
    def test_signin_account_threshold_is_enforced(self):
        limiter = AuthRateLimiter(make_settings(), client=FakeRedis())

        first = limiter.reserve_signin("alice@example.com", "10.0.0.1")
        second = limiter.reserve_signin("alice@example.com", "10.0.0.1")
        third = limiter.reserve_signin("alice@example.com", "10.0.0.1")

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertFalse(third.allowed)
        self.assertEqual(third.limiter_category, "signin_account")

    def test_successful_signin_clears_only_account_and_combined_counters(self):
        client = FakeRedis()
        limiter = AuthRateLimiter(make_settings(), client=client)

        limiter.reserve_signin("alice@example.com", "10.0.0.1")
        limiter.clear_signin_account("alice@example.com", "10.0.0.1")

        self.assertEqual(client.data, {
            limiter.redis_key("signin_ip", "10.0.0.1"): 1,
        })

    def test_rate_limit_response_is_generic_and_retry_after_is_bounded(self):
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: None

        settings = AuthSettings(
            jwt_secret="x" * 64,
            jwt_issuer="tests",
            jwt_audience="tests",
            access_token_minutes=15,
        )
        app.dependency_overrides[auth_rate_limiter] = lambda: AuthRateLimiter(
            make_settings(signin_account=RateLimitPolicy(limit=1, window_seconds=60)),
            client=FakeRedis(),
        )

        # Force the limiter to block before authentication runs.
        original_overrides = dict(app.dependency_overrides)
        fake_limiter = AuthRateLimiter(
            make_settings(signin_account=RateLimitPolicy(limit=1, window_seconds=60)),
            client=FakeRedis(),
        )
        fake_limiter.reserve_signin("alice@example.com", "10.0.0.1")
        app.dependency_overrides[auth_rate_limiter] = lambda: fake_limiter
        app.dependency_overrides[get_db] = lambda: None

        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/auth/signin",
                    json={"email": "alice@example.com", "password": "secret"},
                )
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(original_overrides)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["detail"], RATE_LIMITED_MESSAGE)
        self.assertLessEqual(int(response.headers["retry-after"]), 3600)

    def test_redis_key_does_not_expose_raw_email_or_token(self):
        limiter = AuthRateLimiter(make_settings(), client=FakeRedis())
        email_key = limiter.redis_key("signin_account", "alice@example.com")
        token_key = limiter.redis_key("reset_validate_token", "raw-token-1234567890")

        self.assertNotIn("alice@example.com", email_key)
        self.assertNotIn("raw-token-1234567890", token_key)
        self.assertIn("auth-rate-limit", email_key)
        self.assertIn("auth-rate-limit", token_key)


if __name__ == "__main__":
    unittest.main()

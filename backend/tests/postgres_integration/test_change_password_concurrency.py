from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from queue import Queue
from threading import Barrier, Event, Lock, Thread
from time import monotonic, sleep
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.auth_routes import router as auth_router
from app.config import AuthSettings, get_auth_settings
from app.database import get_db
from app.models import AuditLog, PasswordResetToken, User
from app.security import (
    create_access_token,
    decode_and_validate_access_token,
    hash_password,
    verify_password,
)
from app.services import password_change_service
from app.services.password_change_service import (
    IncorrectCurrentPasswordError,
    change_own_password,
)


RUN_FLAG = "RUN_POSTGRES_INTEGRATION_TESTS"
DATABASE_URL_ENV = "POSTGRES_INTEGRATION_DATABASE_URL"
LIVE_DATABASE_NAMES = frozenset({"sogetrel_kb", "labia"})
LOCK_HOLD_SECONDS = 2.0
SIGNING_KEY = (
    "postgres-change-password-test-key-0123456789abcdef0123456789abcdef"
    "0123456789abcdef"
)
SETTINGS = AuthSettings(
    jwt_secret=SIGNING_KEY,
    jwt_issuer="postgres-change-password-tests",
    jwt_audience="postgres-change-password-client",
    access_token_minutes=15,
)


def _integration_enabled() -> bool:
    return os.getenv(RUN_FLAG, "").strip().lower() == "true"


def _postgres_integration_url() -> str:
    value = os.getenv(DATABASE_URL_ENV, "").strip()
    if not value:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} is required when {RUN_FLAG}=true."
        )
    url = make_url(value)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError(f"{DATABASE_URL_ENV} must use a PostgreSQL driver.")
    if url.database in LIVE_DATABASE_NAMES:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must not point at the live compose database "
            f"{url.database!r}."
        )
    return value


@unittest.skipUnless(
    _integration_enabled(),
    f"Set {RUN_FLAG}=true and {DATABASE_URL_ENV} to run PostgreSQL integration tests.",
)
class PostgresChangePasswordConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            _postgres_integration_url(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=0,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)

        with cls.engine.connect() as connection:
            if connection.dialect.name != "postgresql":
                raise RuntimeError("PostgreSQL integration test requires PostgreSQL.")

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.unique = f"phase5b1a2-{uuid4().hex}"
        self.email = f"{self.unique}@example.com"
        self.old_password = f"{self.unique}-current-🔐"
        self.new_passwords = {
            "candidate_a": f"{self.unique}-candidate-a-été",
            "candidate_b": f"{self.unique}-candidate-b-漢字",
        }
        self.reset_token_hash = uuid4().hex + uuid4().hex
        self.user_id: int | None = None
        self.reset_token_id: int | None = None

        with self.Session() as db:
            user = User(
                full_name="Phase 5B PostgreSQL Concurrency User",
                email=self.email,
                role="agent",
                is_active=True,
                activation_status="active",
                token_version=0,
                password_hash=hash_password(self.old_password),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            self.user_id = user.user_id
            reset_token = PasswordResetToken(
                user_id=user.user_id,
                token_hash=self.reset_token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.add(reset_token)
            db.commit()
            db.refresh(reset_token)
            self.reset_token_id = reset_token.password_reset_token_id

    def tearDown(self):
        if self.user_id is None:
            return
        with self.Session() as db:
            db.execute(delete(AuditLog).where(AuditLog.user_id == self.user_id))
            db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == self.user_id))
            db.execute(delete(User).where(User.user_id == self.user_id))
            db.commit()

    def _token_for_current_user(self, *, version: int = 0) -> str:
        if self.user_id is None:
            raise AssertionError("Test user was not created.")
        return create_access_token(
            signing_key=SIGNING_KEY,
            issuer=SETTINGS.jwt_issuer,
            audience=SETTINGS.jwt_audience,
            lifetime=timedelta(minutes=5),
            subject=str(self.user_id),
            version=version,
        )

    def _client(self) -> TestClient:
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")

        def override_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_auth_settings] = lambda: SETTINGS
        return TestClient(app)

    def _run_concurrent_change(self) -> tuple[list[dict[str, object]], bool]:
        if self.user_id is None:
            raise AssertionError("Test user was not created.")

        start_barrier = Barrier(2)
        outcomes: Queue[dict[str, object]] = Queue()
        first_hash_entered = Event()
        first_hash_finished = Event()
        first_hash_lock = Lock()
        first_hash_call = {"taken": False}
        original_hash_password = password_change_service.hash_password

        def delayed_first_hash(password: str) -> str:
            with first_hash_lock:
                is_first = not first_hash_call["taken"]
                if is_first:
                    first_hash_call["taken"] = True
            if is_first:
                first_hash_entered.set()
                sleep(LOCK_HOLD_SECONDS)
                first_hash_finished.set()
            return original_hash_password(password)

        def worker(label: str, new_password: str) -> None:
            db = self.Session()
            start_barrier.wait(timeout=10)
            started_at = monotonic()
            try:
                change_own_password(
                    db,
                    user_id=self.user_id,
                    current_password=self.old_password,
                    new_password=new_password,
                )
            except IncorrectCurrentPasswordError:
                outcomes.put(
                    {
                        "label": label,
                        "category": "incorrect_current_password",
                        "elapsed": monotonic() - started_at,
                    }
                )
            except Exception as error:
                outcomes.put(
                    {
                        "label": label,
                        "category": type(error).__name__,
                        "elapsed": monotonic() - started_at,
                    }
                )
            else:
                outcomes.put(
                    {
                        "label": label,
                        "category": "success",
                        "elapsed": monotonic() - started_at,
                    }
                )
            finally:
                db.close()

        with patch.object(
            password_change_service,
            "hash_password",
            side_effect=delayed_first_hash,
        ):
            threads = [
                Thread(
                    target=worker,
                    args=(label, new_password),
                    daemon=True,
                )
                for label, new_password in self.new_passwords.items()
            ]
            for thread in threads:
                thread.start()
            self.assertTrue(first_hash_entered.wait(timeout=10))
            for thread in threads:
                thread.join(timeout=30)
                self.assertFalse(thread.is_alive())

        results = [outcomes.get_nowait() for _ in range(outcomes.qsize())]
        categories = [result["category"] for result in results]
        self.assertEqual(categories.count("success"), 1)
        self.assertEqual(categories.count("incorrect_current_password"), 1)

        loser = next(
            result for result in results
            if result["category"] == "incorrect_current_password"
        )
        real_blocking_observed = bool(
            first_hash_finished.is_set()
            and float(loser["elapsed"]) >= LOCK_HOLD_SECONDS * 0.75
        )
        self.assertTrue(real_blocking_observed)
        return results, real_blocking_observed

    def test_concurrent_change_password_locks_current_user_row(self):
        pre_change_jwt = self._token_for_current_user(version=0)

        results, real_blocking_observed = self._run_concurrent_change()

        success = next(result for result in results if result["category"] == "success")
        loser = next(
            result for result in results
            if result["category"] == "incorrect_current_password"
        )
        self.assertNotEqual(success["label"], loser["label"])

        winning_password = self.new_passwords[str(success["label"])]
        losing_password = self.new_passwords[str(loser["label"])]
        with self.Session() as db:
            user = db.get(User, self.user_id)
            self.assertIsNotNone(user)
            self.assertEqual(user.token_version, 1)
            self.assertFalse(verify_password(self.old_password, user.password_hash))
            self.assertTrue(verify_password(winning_password, user.password_hash))
            self.assertFalse(verify_password(losing_password, user.password_hash))

            reset_token = db.get(PasswordResetToken, self.reset_token_id)
            self.assertIsNotNone(reset_token)
            self.assertIsNotNone(reset_token.invalidated_at)
            self.assertIsNone(reset_token.consumed_at)

            audit_rows = list(
                db.execute(
                    select(AuditLog)
                    .where(
                        AuditLog.user_id == self.user_id,
                        AuditLog.action == "password_changed",
                        AuditLog.entity_type == "user",
                        AuditLog.entity_id == self.user_id,
                    )
                    .order_by(AuditLog.audit_id)
                ).scalars()
            )
            self.assertEqual(len(audit_rows), 1)
            audit_details = str(audit_rows[0].method_json)
            forbidden_values = (
                self.old_password,
                winning_password,
                losing_password,
                user.password_hash,
                pre_change_jwt,
                self.reset_token_hash,
                f"https://example.com/reset?token={self.reset_token_hash}",
            )
            for forbidden_value in forbidden_values:
                self.assertNotIn(forbidden_value, audit_details)
            self.assertNotIn("Authorization", audit_details)
            self.assertNotIn("Bearer", audit_details)

            audit_count = db.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.user_id == self.user_id,
                    AuditLog.action == "password_changed",
                )
            ).scalar_one()
            self.assertEqual(audit_count, 1)

        with patch(
            "app.auth_dependencies.get_auth_settings",
            return_value=SETTINGS,
        ):
            client = self._client()
            stale = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {pre_change_jwt}"},
            )
            self.assertEqual(stale.status_code, 401)
            old_signin = client.post(
                "/api/v1/auth/signin",
                json={"email": self.email, "password": self.old_password},
            )
            self.assertEqual(old_signin.status_code, 401)
            winning_signin = client.post(
                "/api/v1/auth/signin",
                json={"email": self.email, "password": winning_password},
            )
            self.assertEqual(winning_signin.status_code, 200)
            claims = decode_and_validate_access_token(
                winning_signin.json()["access_token"],
                signing_key=SIGNING_KEY,
                issuer=SETTINGS.jwt_issuer,
                audience=SETTINGS.jwt_audience,
            )
            self.assertEqual(claims["ver"], 1)

        self.assertTrue(real_blocking_observed)


if __name__ == "__main__":
    unittest.main()

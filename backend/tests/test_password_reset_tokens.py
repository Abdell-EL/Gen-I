from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import PasswordResetToken, User
from app.services.password_reset_tokens import invalidate_outstanding_password_reset_tokens


class PasswordResetTokenHelperTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = self.add_user("helper@example.com")
        self.other_user = self.add_user("other-helper@example.com")

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def add_user(self, email: str) -> User:
        user = User(
            full_name=email,
            email=email,
            role="agent",
            is_active=True,
            activation_status="active",
            password_hash="unused",
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def add_token(
        self,
        *,
        user: User,
        token_hash: str,
        consumed_at: datetime | None = None,
        invalidated_at: datetime | None = None,
    ) -> PasswordResetToken:
        token = PasswordResetToken(
            user_id=user.user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            consumed_at=consumed_at,
            invalidated_at=invalidated_at,
        )
        self.db.add(token)
        self.db.commit()
        self.db.refresh(token)
        return token

    def test_invalidates_only_outstanding_tokens_and_does_not_commit(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        consumed_at = now - timedelta(minutes=3)
        previously_invalidated_at = now - timedelta(minutes=2)
        unused = self.add_token(user=self.user, token_hash="1" * 64)
        consumed = self.add_token(
            user=self.user,
            token_hash="2" * 64,
            consumed_at=consumed_at,
        )
        invalidated = self.add_token(
            user=self.user,
            token_hash="3" * 64,
            invalidated_at=previously_invalidated_at,
        )
        other = self.add_token(user=self.other_user, token_hash="4" * 64)

        invalidate_outstanding_password_reset_tokens(self.db, self.user.user_id, now=now)

        self.assertEqual(unused.invalidated_at, now)
        self.assertEqual(consumed.consumed_at, consumed_at)
        self.assertIsNone(consumed.invalidated_at)
        self.assertEqual(invalidated.invalidated_at, previously_invalidated_at)
        self.assertIsNone(other.invalidated_at)

        self.db.rollback()
        self.db.expire_all()
        self.assertIsNone(self.db.get(PasswordResetToken, unused.password_reset_token_id).invalidated_at)
        self.assertIsNone(self.db.get(PasswordResetToken, other.password_reset_token_id).invalidated_at)


if __name__ == "__main__":
    unittest.main()

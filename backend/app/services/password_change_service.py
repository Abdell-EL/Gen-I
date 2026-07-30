from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.security import PasswordTooLongError, hash_password, verify_password
from app.services.password_reset_tokens import invalidate_outstanding_password_reset_tokens


class ChangePasswordError(Exception):
    """Base exception for authenticated password-change failures."""


class ChangePasswordAuthenticationError(ChangePasswordError):
    pass


class IncorrectCurrentPasswordError(ChangePasswordError):
    pass


class PasswordReuseError(ChangePasswordError):
    pass


class ChangePasswordPersistenceError(ChangePasswordError):
    pass


def change_own_password(
    db: Session,
    *,
    user_id: int,
    current_password: str,
    new_password: str,
) -> User:
    """Atomically replace the current user's password and invalidate old credentials."""

    try:
        user = db.execute(
            select(User)
            .where(User.user_id == user_id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            user is None
            or not user.is_active
            or getattr(user, "activation_status", "active") != "active"
            or not user.password_hash
        ):
            raise ChangePasswordAuthenticationError("Not authenticated.")

        if not verify_password(current_password, user.password_hash):
            raise IncorrectCurrentPasswordError("Current password is incorrect.")
        if verify_password(new_password, user.password_hash):
            raise PasswordReuseError("New password must be different from current password.")

        now = datetime.now(timezone.utc)
        user.password_hash = hash_password(new_password)
        user.token_version = int(user.token_version or 0) + 1
        user.updated_at = now
        invalidate_outstanding_password_reset_tokens(db, user.user_id, now=now)
        db.add(user)
        db.add(
            AuditLog(
                user_id=user.user_id,
                action="password_changed",
                entity_type="user",
                entity_id=user.user_id,
                method_json={
                    "credential_changed": True,
                    "reauthentication_required": True,
                },
            )
        )
        db.commit()
        db.refresh(user)
        return user
    except (
        ChangePasswordAuthenticationError,
        IncorrectCurrentPasswordError,
        PasswordReuseError,
        PasswordTooLongError,
    ):
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        raise ChangePasswordPersistenceError("Password change failed.") from error

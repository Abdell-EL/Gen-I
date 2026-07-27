from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User
from app.security import (
    PasswordTooLongError,
    hash_password,
    password_needs_rehash,
    verify_password,
)


GENERIC_SIGNIN_ERROR = "Invalid email or password."


class InvalidCredentialsError(Exception):
    """Generic authentication failure that does not disclose account state."""

    def __init__(self) -> None:
        super().__init__(GENERIC_SIGNIN_ERROR)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_user_by_email(db: Session, normalized_email: str) -> User | None:
    statement = select(User).where(func.lower(User.email) == normalized_email)
    return db.execute(statement).scalar_one_or_none()


def authenticate_user(db: Session, *, email: str, password: str) -> User:
    normalized_email = normalize_email(email)
    user = find_user_by_email(db, normalized_email)

    if user is None or not user.password_hash or not user.is_active:
        raise InvalidCredentialsError()

    try:
        password_is_valid = verify_password(password, user.password_hash)
    except (PasswordTooLongError, TypeError):
        raise InvalidCredentialsError() from None

    if not password_is_valid:
        raise InvalidCredentialsError()

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.add(user)
        db.commit()
        db.refresh(user)

    return user

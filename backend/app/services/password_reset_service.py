from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from urllib.parse import quote

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.config import PasswordResetSettings
from app.models import AuditLog, PasswordResetToken, User
from app.services.auth_service import normalize_email
from app.services.password_reset_delivery import PasswordResetDeliveryProvider
from app.services.password_reset_tokens import invalidate_outstanding_password_reset_tokens


FORGOT_PASSWORD_MESSAGE = (
    "Si un compte éligible correspond à cette adresse, des instructions de "
    "réinitialisation seront envoyées."
)
TOKEN_BYTES = 32
MIN_RESET_TOKEN_LENGTH = 32
MAX_RESET_TOKEN_LENGTH = 512
GENERIC_RESET_TOKEN_ERROR = "Password reset link is not valid."


class PasswordResetError(Exception):
    """Base exception for password-reset request and validation failures."""


class InvalidPasswordResetTokenError(PasswordResetError):
    code = "invalid"


class ExpiredPasswordResetTokenError(InvalidPasswordResetTokenError):
    code = "expired"


class ConsumedPasswordResetTokenError(InvalidPasswordResetTokenError):
    code = "consumed"


class PasswordResetDeliveryFailure(PasswordResetError):
    pass


class PasswordResetPersistenceError(PasswordResetError):
    pass


@dataclass(frozen=True)
class ForgotPasswordResult:
    reset_url: str | None = None


def token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _eligible_user_statement(email: str):
    return (
        select(User)
        .where(
            func.lower(User.email) == email,
            User.is_active.is_(True),
            User.activation_status == "active",
            User.password_hash.is_not(None),
        )
        .with_for_update()
    )


def _latest_usable_token(db: Session, user_id: int) -> PasswordResetToken | None:
    return db.execute(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.invalidated_at.is_(None),
        )
        .order_by(
            desc(PasswordResetToken.created_at),
            desc(PasswordResetToken.password_reset_token_id),
        )
    ).scalars().first()


def _audit(
    db: Session,
    *,
    user_id: int,
    action: str,
    metadata: dict[str, object],
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type="user",
            entity_id=user_id,
            method_json=metadata,
        )
    )


def _new_reset_token(
    db: Session,
    *,
    user: User,
    settings: PasswordResetSettings,
    now: datetime,
) -> tuple[PasswordResetToken, str, str]:
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    token = PasswordResetToken(
        user_id=user.user_id,
        token_hash=token_digest(raw_token),
        delivery_status="pending",
        created_at=now,
        expires_at=now + timedelta(minutes=settings.token_ttl_minutes),
    )
    db.add(token)
    db.flush()
    reset_url = (
        f"{settings.frontend_password_reset_url}?token={quote(raw_token, safe='')}"
    )
    return token, raw_token, reset_url


def _public_reset_url(
    *,
    settings: PasswordResetSettings,
    delivery_status: str,
    reset_url: str,
) -> str | None:
    if (
        settings.email_provider_mode == "capture"
        and settings.expose_reset_url
        and delivery_status == "sent"
    ):
        return reset_url
    return None


def request_password_reset(
    db: Session,
    *,
    email: str,
    provider: PasswordResetDeliveryProvider,
    settings: PasswordResetSettings,
) -> ForgotPasswordResult:
    """Issue a reset token for eligible users while preserving public neutrality."""

    normalized_email = normalize_email(email)
    try:
        user = db.execute(_eligible_user_statement(normalized_email)).scalar_one_or_none()
        if user is None:
            db.rollback()
            return ForgotPasswordResult()

        now = _now()
        latest_token = _latest_usable_token(db, user.user_id)
        if latest_token is not None and (
            now - _aware(latest_token.created_at)
        ).total_seconds() < settings.resend_cooldown_seconds:
            _audit(
                db,
                user_id=user.user_id,
                action="password_reset_requested",
                metadata={
                    "provider_mode": settings.email_provider_mode,
                    "delivery_status": latest_token.delivery_status,
                    "ttl_minutes": settings.token_ttl_minutes,
                    "cooldown_suppressed": True,
                },
            )
            db.commit()
            return ForgotPasswordResult()

        invalidate_outstanding_password_reset_tokens(db, user.user_id, now=now)
        token, _raw_token, reset_url = _new_reset_token(
            db, user=user, settings=settings, now=now
        )
        try:
            delivery = provider.deliver(
                email=user.email,
                full_name=user.full_name,
                reset_url=reset_url,
            )
        except Exception:
            token.delivery_status = "failed"
            token.invalidated_at = now
            _audit(
                db,
                user_id=user.user_id,
                action="password_reset_requested",
                metadata={
                    "provider_mode": settings.email_provider_mode,
                    "delivery_status": "failed",
                    "ttl_minutes": settings.token_ttl_minutes,
                    "cooldown_suppressed": False,
                },
            )
            _audit(
                db,
                user_id=user.user_id,
                action="password_reset_delivery_failed",
                metadata={
                    "provider_mode": settings.email_provider_mode,
                    "delivery_status": "failed",
                    "ttl_minutes": settings.token_ttl_minutes,
                },
            )
            db.commit()
            return ForgotPasswordResult()

        token.delivery_status = delivery.status
        _audit(
            db,
            user_id=user.user_id,
            action="password_reset_requested",
            metadata={
                "provider_mode": settings.email_provider_mode,
                "delivery_status": delivery.status,
                "ttl_minutes": settings.token_ttl_minutes,
                "cooldown_suppressed": False,
            },
        )
        db.commit()
        return ForgotPasswordResult(
            reset_url=_public_reset_url(
                settings=settings,
                delivery_status=delivery.status,
                reset_url=reset_url,
            )
        )
    except PasswordResetPersistenceError:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        raise PasswordResetPersistenceError("Password reset request failed.") from error


def inspect_password_reset_token(db: Session, raw_token: str) -> PasswordResetToken:
    if not MIN_RESET_TOKEN_LENGTH <= len(raw_token) <= MAX_RESET_TOKEN_LENGTH:
        raise InvalidPasswordResetTokenError(GENERIC_RESET_TOKEN_ERROR)

    digest = token_digest(raw_token)
    try:
        token = db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == digest)
        ).scalar_one_or_none()
    except Exception as error:
        raise PasswordResetPersistenceError("Password reset validation failed.") from error

    if token is None or not hmac.compare_digest(token.token_hash, digest):
        raise InvalidPasswordResetTokenError(GENERIC_RESET_TOKEN_ERROR)
    if token.invalidated_at is not None:
        raise InvalidPasswordResetTokenError(GENERIC_RESET_TOKEN_ERROR)
    if token.consumed_at is not None:
        raise ConsumedPasswordResetTokenError(GENERIC_RESET_TOKEN_ERROR)
    if _aware(token.expires_at) <= _now():
        raise ExpiredPasswordResetTokenError(GENERIC_RESET_TOKEN_ERROR)
    return token

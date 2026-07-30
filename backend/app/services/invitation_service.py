from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from urllib.parse import quote

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import InvitationSettings
from app.models import AuditLog, InvitationToken, User
from app.security import hash_password
from app.services.auth_service import normalize_email
from app.services.invitation_delivery import InvitationDeliveryProvider

PURPOSE = "account_activation"
GENERIC_TOKEN_ERROR = "Invalid or expired activation token."


class InvitationError(Exception): pass
class InvitationConflictError(InvitationError): pass
class InvitationNotFoundError(InvitationError): pass
class InvitationThrottledError(InvitationError): pass
class InvalidActivationTokenError(InvitationError):
    code = "invalid"


class ExpiredActivationTokenError(InvalidActivationTokenError):
    code = "expired"


class ConsumedActivationTokenError(InvalidActivationTokenError):
    code = "consumed"


class InvalidatedActivationTokenError(InvalidActivationTokenError):
    code = "invalid"
class InvitationDeliveryError(InvitationError): pass


def token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _audit(db: Session, *, actor_user_id: int, action: str, target_user_id: int,
           metadata: dict | None = None) -> None:
    db.add(AuditLog(user_id=actor_user_id, action=action, entity_type="user",
                    entity_id=target_user_id, method_json=metadata or {}))


def _new_token(db: Session, *, user: User, actor_user_id: int,
               settings: InvitationSettings) -> tuple[InvitationToken, str, str]:
    raw_token = secrets.token_urlsafe(32)
    row = InvitationToken(
        user_id=user.user_id, created_by_user_id=actor_user_id,
        token_hash=token_digest(raw_token), purpose=PURPOSE,
        delivery_status="pending", created_at=_now(),
        expires_at=_now() + timedelta(minutes=settings.token_lifetime_minutes),
    )
    db.add(row)
    activation_url = f"{settings.frontend_activation_url}?token={quote(raw_token, safe='')}"
    return row, raw_token, activation_url


def _delivery_payload(settings: InvitationSettings, status: str, activation_url: str) -> dict:
    payload = {"status": status}
    if settings.expose_activation_url and settings.email_provider_mode == "capture":
        payload["activation_url"] = activation_url
    return payload


def _deliver(db: Session, *, token: InvitationToken, user: User, actor_user_id: int,
             activation_url: str, provider: InvitationDeliveryProvider,
             settings: InvitationSettings, action: str) -> dict:
    try:
        result = provider.deliver(email=user.email, full_name=user.full_name,
                                  activation_url=activation_url)
        token.delivery_status = result.status
        _audit(db, actor_user_id=actor_user_id, action=action,
               target_user_id=user.user_id, metadata={"delivery_status": result.status})
        db.commit()
        return _delivery_payload(settings, result.status, activation_url)
    except Exception:
        db.rollback()
        token = db.get(InvitationToken, token.invitation_token_id)
        if token is not None and token.consumed_at is None:
            token.invalidated_at = _now()
            token.delivery_status = "failed"
        _audit(db, actor_user_id=actor_user_id, action="invitation.delivery_failed",
               target_user_id=user.user_id, metadata={"provider_mode": settings.email_provider_mode})
        db.commit()
        return {"status": "failed"}


def create_invited_user(db: Session, *, actor_user_id: int, full_name: str, email: str,
                        role: str, provider: InvitationDeliveryProvider,
                        settings: InvitationSettings) -> tuple[User, dict]:
    normalized_email = normalize_email(email)
    if db.execute(select(User.user_id).where(func.lower(User.email) == normalized_email)).scalar_one_or_none():
        raise InvitationConflictError("A user with this email already exists.")
    user = User(full_name=full_name, email=normalized_email, role=role, is_active=True,
                activation_status="pending", password_hash=None)
    try:
        db.add(user)
        db.flush()
        token, _raw, activation_url = _new_token(
            db, user=user, actor_user_id=actor_user_id, settings=settings
        )
        db.commit()
        db.refresh(user); db.refresh(token)
    except IntegrityError:
        db.rollback()
        raise InvitationConflictError("A user with this email already exists.") from None
    except Exception:
        db.rollback()
        raise
    delivery = _deliver(db, token=token, user=user, actor_user_id=actor_user_id,
                        activation_url=activation_url, provider=provider,
                        settings=settings, action="user.invited")
    return user, delivery


def resend_invitation(db: Session, *, actor_user_id: int, target_user_id: int,
                      provider: InvitationDeliveryProvider,
                      settings: InvitationSettings) -> tuple[User, dict]:
    user = db.get(User, target_user_id)
    if user is None:
        raise InvitationNotFoundError("User not found.")
    if user.activation_status == "active":
        raise InvitationConflictError("Activated users cannot be reinvited.")
    now = _now()
    latest = db.execute(select(InvitationToken).where(
        InvitationToken.user_id == target_user_id,
        InvitationToken.purpose == PURPOSE,
    ).order_by(desc(InvitationToken.created_at), desc(InvitationToken.invitation_token_id))).scalars().first()
    if latest and settings.resend_cooldown_seconds and (
        now - _aware(latest.created_at)
    ).total_seconds() < settings.resend_cooldown_seconds:
        raise InvitationThrottledError("Invitation resend is temporarily unavailable.")
    for row in db.execute(select(InvitationToken).where(
        InvitationToken.user_id == target_user_id,
        InvitationToken.purpose == PURPOSE,
        InvitationToken.consumed_at.is_(None),
        InvitationToken.invalidated_at.is_(None),
    ).with_for_update()).scalars():
        row.invalidated_at = now
    token, _raw, activation_url = _new_token(
        db, user=user, actor_user_id=actor_user_id, settings=settings
    )
    db.commit(); db.refresh(token)
    delivery = _deliver(db, token=token, user=user, actor_user_id=actor_user_id,
                        activation_url=activation_url, provider=provider,
                        settings=settings, action="invitation.resent")
    return user, delivery


def _valid_token(db: Session, raw_token: str, *, lock: bool = False) -> InvitationToken:
    digest = token_digest(raw_token)
    statement = select(InvitationToken).where(
        InvitationToken.token_hash == digest,
        InvitationToken.purpose == PURPOSE,
    )
    if lock:
        statement = statement.with_for_update()
    row = db.execute(statement).scalar_one_or_none()
    if row is None or not hmac.compare_digest(row.token_hash, digest):
        raise InvalidActivationTokenError(GENERIC_TOKEN_ERROR)
    if row.consumed_at is not None:
        raise ConsumedActivationTokenError(GENERIC_TOKEN_ERROR)
    if row.invalidated_at is not None:
        raise InvalidatedActivationTokenError(GENERIC_TOKEN_ERROR)
    if _aware(row.expires_at) <= _now():
        raise ExpiredActivationTokenError(GENERIC_TOKEN_ERROR)
    return row


def inspect_activation_token(db: Session, raw_token: str) -> InvitationToken:
    return _valid_token(db, raw_token)


def complete_activation(db: Session, *, raw_token: str, password: str) -> User:
    try:
        token = _valid_token(db, raw_token, lock=True)
        user = db.execute(select(User).where(User.user_id == token.user_id).with_for_update()).scalar_one()
        if user.activation_status != "pending":
            raise InvalidActivationTokenError(GENERIC_TOKEN_ERROR)
        now = _now()
        user.password_hash = hash_password(password)
        user.activation_status = "active"
        user.updated_at = now
        token.consumed_at = now
        _audit(db, actor_user_id=user.user_id, action="activation.completed",
               target_user_id=user.user_id, metadata={"credential_changed": True})
        db.commit(); db.refresh(user)
        return user
    except InvalidActivationTokenError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

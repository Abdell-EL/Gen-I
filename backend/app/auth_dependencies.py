from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_auth_settings
from app.database import get_db
from app.models import User
from app.security import AccessTokenError, decode_and_validate_access_token


bearer_scheme = HTTPBearer(auto_error=False)
KNOWN_ROLES = frozenset({"admin", "agent"})


def unauthorized_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized_exception()

    settings = get_auth_settings()
    try:
        claims = decode_and_validate_access_token(
            credentials.credentials,
            signing_key=settings.jwt_secret,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        user_id = int(claims["sub"])
        if user_id <= 0 or str(user_id) != claims["sub"]:
            raise ValueError
    except (AccessTokenError, KeyError, TypeError, ValueError):
        raise unauthorized_exception() from None

    user = db.get(User, user_id)
    if user is None:
        raise unauthorized_exception()
    token_version = claims.get("ver", 0)
    current_version = int(getattr(user, "token_version", 0) or 0)
    if (
        not isinstance(token_version, int)
        or isinstance(token_version, bool)
        or token_version != current_version
    ):
        raise unauthorized_exception()
    if (user is None or not user.is_active
            or getattr(user, "activation_status", "active") != "active"):
        raise unauthorized_exception()

    return user


def insufficient_permissions_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions.",
    )


def require_authenticated_user(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


def _normalize_role(role: object) -> str | None:
    if not isinstance(role, str):
        return None
    normalized = role.strip().lower()
    return normalized or None


def require_any_role(*roles: str) -> Callable[..., User]:
    allowed_roles = frozenset(
        normalized
        for role in roles
        if (normalized := _normalize_role(role)) in KNOWN_ROLES
    )

    def role_dependency(
        current_user: User = Depends(get_current_user),
    ) -> User:
        current_role = _normalize_role(getattr(current_user, "role", None))
        if current_role is None or current_role not in allowed_roles:
            raise insufficient_permissions_exception()
        return current_user

    return role_dependency


def require_role(role: str) -> Callable[..., User]:
    return require_any_role(role)

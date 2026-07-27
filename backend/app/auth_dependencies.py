from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_auth_settings
from app.database import get_db
from app.models import User
from app.security import AccessTokenError, decode_and_validate_access_token


bearer_scheme = HTTPBearer(auto_error=False)


def unauthorized_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication credentials.",
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
    if user is None or not user.is_active:
        raise unauthorized_exception()

    return user

"""Isolated password and JWT access-token security primitives.

This module deliberately has no application configuration, database, network,
or environment dependencies. Callers must inject all token configuration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt
from jwt import exceptions as jwt_exceptions
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher


ACCESS_TOKEN_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"
MAX_PASSWORD_BYTES = 1024
REQUIRED_ACCESS_TOKEN_CLAIMS = (
    "sub",
    "iss",
    "aud",
    "iat",
    "nbf",
    "exp",
    "jti",
    "typ",
)


class SecurityError(Exception):
    """Base exception for failures in these security primitives."""


class PasswordTooLongError(SecurityError, ValueError):
    """Raised when a password exceeds the accepted UTF-8 byte length."""


class AccessTokenError(SecurityError):
    """Base exception for access-token validation failures."""


class AccessTokenExpiredError(AccessTokenError):
    """Raised when an access token has expired."""


class AccessTokenSignatureError(AccessTokenError):
    """Raised when an access-token signature is invalid."""


class AccessTokenClaimsError(AccessTokenError):
    """Raised when required access-token claims are invalid or missing."""


class AccessTokenAlgorithmError(AccessTokenError):
    """Raised when a token uses an unsupported signing algorithm."""


_ARGON2_HASHER = Argon2Hasher()
_PASSWORD_HASH = PasswordHash((_ARGON2_HASHER,))


def _validate_password_length(password: str) -> None:
    if not isinstance(password, str):
        raise TypeError("Password must be a string.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(
            f"Password exceeds the {MAX_PASSWORD_BYTES}-byte UTF-8 limit."
        )


def hash_password(password: str) -> str:
    """Hash a password with Argon2id after enforcing a byte-length limit."""

    _validate_password_length(password)
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return whether a password matches an encoded Argon2id hash."""

    _validate_password_length(password)
    if not isinstance(password_hash, str) or not password_hash:
        return False
    try:
        return _PASSWORD_HASH.verify(password, password_hash)
    except (TypeError, ValueError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Return whether a valid Argon2 hash should use the current parameters."""

    if not isinstance(password_hash, str) or not password_hash:
        return True
    try:
        if not _ARGON2_HASHER.identify(password_hash):
            return True
        return _ARGON2_HASHER.check_needs_rehash(password_hash)
    except (TypeError, ValueError):
        return True


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    *,
    signing_key: str,
    issuer: str,
    audience: str,
    lifetime: timedelta,
    subject: str,
    version: int = 0,
) -> str:
    """Create an HS256 JWT access token from explicitly injected settings."""

    if not isinstance(lifetime, timedelta) or lifetime.total_seconds() == 0:
        raise ValueError("Token lifetime must be a non-zero timedelta.")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ValueError("Token version must be a non-negative integer.")
    if not all(
        isinstance(value, str) and value
        for value in (signing_key, issuer, audience, subject)
    ):
        raise ValueError("Token settings and subject must be non-empty strings.")

    now = _utc_now()
    claims = {
        "sub": subject,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "jti": str(uuid4()),
        "typ": ACCESS_TOKEN_TYPE,
        "ver": version,
    }
    return jwt.encode(claims, signing_key, algorithm=ACCESS_TOKEN_ALGORITHM)


def decode_and_validate_access_token(
    token: str,
    *,
    signing_key: str,
    issuer: str,
    audience: str,
) -> dict[str, Any]:
    """Validate an injected HS256 access token and return its claims."""

    if not isinstance(token, str) or not token:
        raise AccessTokenClaimsError("Access token is malformed.")
    if not all(
        isinstance(value, str) and value
        for value in (signing_key, issuer, audience)
    ):
        raise ValueError("Token validation settings must be non-empty strings.")

    try:
        header = jwt.get_unverified_header(token)
    except jwt_exceptions.PyJWTError as error:
        raise AccessTokenClaimsError("Access token is malformed.") from error

    if header.get("alg") != ACCESS_TOKEN_ALGORITHM:
        raise AccessTokenAlgorithmError("Access token algorithm is unsupported.")

    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=[ACCESS_TOKEN_ALGORITHM],
            issuer=issuer,
            audience=audience,
            options={"require": list(REQUIRED_ACCESS_TOKEN_CLAIMS)},
        )
    except jwt_exceptions.ExpiredSignatureError as error:
        raise AccessTokenExpiredError("Access token has expired.") from error
    except jwt_exceptions.InvalidSignatureError as error:
        raise AccessTokenSignatureError("Access token signature is invalid.") from error
    except jwt_exceptions.InvalidAlgorithmError as error:
        raise AccessTokenAlgorithmError(
            "Access token algorithm is unsupported."
        ) from error
    except jwt_exceptions.PyJWTError as error:
        raise AccessTokenClaimsError("Access token claims are invalid.") from error

    if claims.get("typ") != ACCESS_TOKEN_TYPE:
        raise AccessTokenClaimsError("Access token type is invalid.")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise AccessTokenClaimsError("Access token subject is invalid.")
    if not isinstance(claims.get("jti"), str) or not claims["jti"]:
        raise AccessTokenClaimsError("Access token identifier is invalid.")

    return claims

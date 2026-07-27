import os
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy import URL

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("POSTGRES_USER", "kb_user"),
        password=os.getenv("POSTGRES_PASSWORD", "kb_password"),
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "15432")),
        database=os.getenv("POSTGRES_DB", "sogetrel_kb"),
    )

MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.getenv(
    "MILVUS_COLLECTION",
    "sogetrel_chunks",
)

MIN_ACCESS_TOKEN_MINUTES = 1
MAX_ACCESS_TOKEN_MINUTES = 1440


class AuthConfigurationError(RuntimeError):
    """Raised when authentication is invoked without valid settings."""


@dataclass(frozen=True)
class AuthSettings:
    jwt_secret: str
    jwt_issuer: str
    jwt_audience: str
    access_token_minutes: int


def get_auth_settings() -> AuthSettings:
    """Load and validate auth settings only when authentication is invoked."""

    secret = os.getenv("AUTH_JWT_SECRET", "")
    issuer = os.getenv("AUTH_JWT_ISSUER", "")
    audience = os.getenv("AUTH_JWT_AUDIENCE", "")
    lifetime_value = os.getenv("AUTH_ACCESS_TOKEN_MINUTES", "")

    if not secret:
        raise AuthConfigurationError("AUTH_JWT_SECRET is required.")
    if not issuer:
        raise AuthConfigurationError("AUTH_JWT_ISSUER is required.")
    if not audience:
        raise AuthConfigurationError("AUTH_JWT_AUDIENCE is required.")

    try:
        lifetime = int(lifetime_value)
    except (TypeError, ValueError) as error:
        raise AuthConfigurationError(
            "AUTH_ACCESS_TOKEN_MINUTES must be an integer."
        ) from error

    if not MIN_ACCESS_TOKEN_MINUTES <= lifetime <= MAX_ACCESS_TOKEN_MINUTES:
        raise AuthConfigurationError(
            "AUTH_ACCESS_TOKEN_MINUTES must be between "
            f"{MIN_ACCESS_TOKEN_MINUTES} and {MAX_ACCESS_TOKEN_MINUTES}."
        )

    return AuthSettings(
        jwt_secret=secret,
        jwt_issuer=issuer,
        jwt_audience=audience,
        access_token_minutes=lifetime,
    )

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


class PasswordResetConfigurationError(RuntimeError):
    """Raised when password-reset settings are unsafe or unsupported."""


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


@dataclass(frozen=True)
class InvitationSettings:
    frontend_activation_url: str
    token_lifetime_minutes: int
    email_provider_mode: str
    resend_cooldown_seconds: int
    expose_activation_url: bool


@dataclass(frozen=True)
class PasswordResetSettings:
    frontend_password_reset_url: str
    email_provider_mode: str
    expose_reset_url: bool
    token_ttl_minutes: int
    resend_cooldown_seconds: int


def get_invitation_settings() -> InvitationSettings:
    mode = os.getenv("INVITATION_EMAIL_PROVIDER", "noop").strip().lower() or "noop"
    if mode not in {"noop", "capture"}:
        mode = "noop"
    return InvitationSettings(
        frontend_activation_url=(os.getenv(
            "FRONTEND_ACTIVATION_URL", "http://localhost:5173/activate"
        ).strip() or "http://localhost:5173/activate"),
        token_lifetime_minutes=_bounded_int("INVITATION_TOKEN_LIFETIME_MINUTES", 1440, 5, 10080),
        email_provider_mode=mode,
        resend_cooldown_seconds=_bounded_int("INVITATION_RESEND_COOLDOWN_SECONDS", 60, 0, 86400),
        expose_activation_url=_env_bool("INVITATION_EXPOSE_ACTIVATION_URL", False),
    )


def _strict_bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        value = default
    else:
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as error:
            raise PasswordResetConfigurationError(
                f"{name} must be an integer."
            ) from error
    if not minimum <= value <= maximum:
        raise PasswordResetConfigurationError(
            f"{name} must be between {minimum} and {maximum}."
        )
    return value


def get_password_reset_settings() -> PasswordResetSettings:
    mode = (
        os.getenv("PASSWORD_RESET_EMAIL_PROVIDER", "noop").strip().lower()
        or "noop"
    )
    if mode not in {"noop", "capture"}:
        raise PasswordResetConfigurationError(
            "PASSWORD_RESET_EMAIL_PROVIDER must be one of: noop, capture."
        )
    frontend_url = (
        os.getenv(
            "FRONTEND_PASSWORD_RESET_URL",
            "http://localhost:5173/reset-password",
        ).strip()
        or "http://localhost:5173/reset-password"
    )
    return PasswordResetSettings(
        frontend_password_reset_url=frontend_url,
        email_provider_mode=mode,
        expose_reset_url=_env_bool("PASSWORD_RESET_EXPOSE_URL", False),
        token_ttl_minutes=_strict_bounded_int(
            "PASSWORD_RESET_TOKEN_TTL_MINUTES", 30, 5, 1440
        ),
        resend_cooldown_seconds=_strict_bounded_int(
            "PASSWORD_RESET_RESEND_COOLDOWN_SECONDS", 60, 1, 86400
        ),
    )


@dataclass(frozen=True)
class CacheSettings:
    redis_url: str
    enabled: bool
    namespace: str
    default_ttl_seconds: int
    search_ttl_seconds: int
    embedding_ttl_seconds: int
    version: str


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def get_cache_settings() -> CacheSettings:
    return CacheSettings(
        redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        enabled=_env_bool("CACHE_ENABLED", True),
        namespace=os.getenv("CACHE_NAMESPACE", "lab-ia-genius").strip() or "lab-ia-genius",
        default_ttl_seconds=_bounded_int("CACHE_DEFAULT_TTL_SECONDS", 300, 1, 86400),
        search_ttl_seconds=_bounded_int("CACHE_SEARCH_TTL_SECONDS", 300, 1, 86400),
        embedding_ttl_seconds=_bounded_int("CACHE_EMBEDDING_TTL_SECONDS", 3600, 1, 604800),
        version=os.getenv("CACHE_VERSION", "v1").strip() or "v1",
    )


@dataclass(frozen=True)
class OllamaSettings:
    url: str
    model: str
    fast_model: str
    use_fast_model: bool
    keep_alive: str
    num_ctx: int
    num_predict: int
    temperature: float
    request_timeout_seconds: float
    max_context_chars: int

    @property
    def selected_model(self) -> str:
        return self.fast_model if self.use_fast_model else self.model


def get_ollama_settings() -> OllamaSettings:
    return OllamaSettings(
        url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
        model=os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip() or "llama3.2:3b",
        fast_model=os.getenv("OLLAMA_FAST_MODEL", "llama3.2:1b").strip() or "llama3.2:1b",
        use_fast_model=_env_bool("OLLAMA_USE_FAST_MODEL", False),
        keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "10m").strip() or "10m",
        num_ctx=_bounded_int("OLLAMA_NUM_CTX", 4096, 512, 32768),
        num_predict=_bounded_int("OLLAMA_NUM_PREDICT", 350, 1, 2048),
        temperature=_bounded_float("OLLAMA_TEMPERATURE", 0.1, 0.0, 2.0),
        request_timeout_seconds=_bounded_float(
            "OLLAMA_REQUEST_TIMEOUT_SECONDS", 120.0, 1.0, 600.0
        ),
        max_context_chars=_bounded_int("OLLAMA_MAX_CONTEXT_CHARS", 12000, 1000, 100000),
    )

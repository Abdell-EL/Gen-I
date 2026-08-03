from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import ipaddress
import logging
import threading
from typing import Any, Sequence

from starlette.requests import Request

from app.config import (
    AuthRateLimitSettings,
    RateLimitPolicy,
    get_auth_rate_limit_settings,
)

try:
    import redis
except ImportError:  # Rate limiting fails open when Redis support is absent.
    redis = None


logger = logging.getLogger(__name__)
RATE_LIMITED_MESSAGE = "Trop de tentatives. Reessayez plus tard."
MAX_RETRY_AFTER_SECONDS = 3600
_KEY_VERSION = "v1"
_CLIENT: Any | None = None
_CLIENT_LOCK = threading.Lock()

_RESERVE_SCRIPT = """
for i = 1, #KEYS do
  local limit = tonumber(ARGV[(i * 2) - 1])
  local window = tonumber(ARGV[i * 2])
  local raw = redis.call('get', KEYS[i])
  local current = tonumber(raw)
  if current == nil then
    current = 0
  end
  if current >= limit then
    local ttl = redis.call('pttl', KEYS[i])
    if ttl < 0 then
      ttl = window * 1000
    end
    local retry = math.ceil(ttl / 1000)
    if retry < 1 then
      retry = 1
    end
    return {0, retry, i}
  end
end
for i = 1, #KEYS do
  local window = tonumber(ARGV[i * 2])
  local count = redis.call('incr', KEYS[i])
  if count == 1 then
    redis.call('expire', KEYS[i], window)
  else
    local ttl = redis.call('ttl', KEYS[i])
    if ttl < 0 then
      redis.call('expire', KEYS[i], window)
    end
  end
end
return {1, 0, 0}
"""


@dataclass(frozen=True)
class LimitKey:
    category: str
    key: str
    policy: RateLimitPolicy


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0
    redis_available: bool = True
    limiter_category: str | None = None


def _bounded_retry_after(seconds: int) -> int:
    return max(1, min(int(seconds or 1), MAX_RETRY_AFTER_SECONDS))


def normalize_client_host(host: str | None) -> str:
    if not host:
        return "unknown"
    candidate = host.strip()
    if not candidate:
        return "unknown"
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        return candidate.lower()[:255]


def client_host_from_request(request: Request) -> str:
    client = getattr(request, "client", None)
    return normalize_client_host(getattr(client, "host", None))


def _get_client(settings: AuthRateLimitSettings | None = None):
    global _CLIENT
    settings = settings or get_auth_rate_limit_settings()
    if not settings.enabled or redis is None:
        return None
    if _CLIENT is not None:
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=0.05,
                socket_timeout=0.1,
                health_check_interval=30,
            )
    return _CLIENT


def close_auth_rate_limit_client() -> None:
    global _CLIENT
    with _CLIENT_LOCK:
        client, _CLIENT = _CLIENT, None
    if client is None:
        return
    try:
        client.close()
    except Exception:
        logger.warning("auth_rate_limit_client_close_failed", exc_info=True)


def log_auth_event(
    event: str,
    *,
    action: str,
    decision: RateLimitDecision | None = None,
    actor_user_id: int | None = None,
) -> None:
    metadata: dict[str, object] = {
        "action": action,
        "redis_protection_available": (
            decision.redis_available if decision is not None else None
        ),
    }
    if decision is not None and decision.limiter_category is not None:
        metadata["limiter_category"] = decision.limiter_category
    if decision is not None and decision.retry_after_seconds:
        metadata["retry_after_seconds"] = decision.retry_after_seconds
    if actor_user_id is not None:
        metadata["actor_user_id"] = int(actor_user_id)
    logger.info(event, extra=metadata)


class AuthRateLimiter:
    def __init__(
        self,
        settings: AuthRateLimitSettings,
        *,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        self._client = client

    def reserve_signin(self, normalized_email: str, client_host: str) -> RateLimitDecision:
        return self.reserve(
            self.signin_limits(normalized_email, client_host),
            action="signin",
        )

    def clear_signin_account(self, normalized_email: str, client_host: str) -> None:
        combined = f"{normalized_email}\0{client_host}"
        keys = [
            self._limit("signin_account", normalized_email, self.settings.signin_account).key,
            self._limit("signin_combined", combined, self.settings.signin_combined).key,
        ]
        self.clear(keys, action="signin")

    def reserve_forgot_password(
        self, normalized_email: str, client_host: str
    ) -> RateLimitDecision:
        return self.reserve(
            [
                self._limit("forgot_account", normalized_email, self.settings.forgot_account),
                self._limit("forgot_ip", client_host, self.settings.forgot_ip),
            ],
            action="password_forgot",
        )

    def reserve_reset_validation(
        self, raw_token: str, client_host: str
    ) -> RateLimitDecision:
        return self.reserve(
            [
                self._limit(
                    "reset_validate_token",
                    raw_token,
                    self.settings.reset_validate_token,
                ),
                self._limit(
                    "reset_validate_ip", client_host, self.settings.reset_validate_ip
                ),
            ],
            action="password_reset_validate",
        )

    def reserve_reset_completion(
        self, raw_token: str, client_host: str
    ) -> RateLimitDecision:
        return self.reserve(
            [
                self._limit(
                    "reset_complete_token",
                    raw_token,
                    self.settings.reset_complete_token,
                ),
                self._limit(
                    "reset_complete_ip", client_host, self.settings.reset_complete_ip
                ),
            ],
            action="password_reset_complete",
        )

    def reserve_activation_validation(
        self, raw_token: str, client_host: str
    ) -> RateLimitDecision:
        return self.reserve(
            [
                self._limit(
                    "activation_validate_token",
                    raw_token,
                    self.settings.activation_validate_token,
                ),
                self._limit(
                    "activation_validate_ip",
                    client_host,
                    self.settings.activation_validate_ip,
                ),
            ],
            action="activation_validate",
        )

    def reserve_activation_completion(
        self, raw_token: str, client_host: str
    ) -> RateLimitDecision:
        return self.reserve(
            [
                self._limit(
                    "activation_complete_token",
                    raw_token,
                    self.settings.activation_complete_token,
                ),
                self._limit(
                    "activation_complete_ip",
                    client_host,
                    self.settings.activation_complete_ip,
                ),
            ],
            action="activation_complete",
        )

    def reserve_invitation_resend(
        self, *, actor_user_id: int, target_user_id: int
    ) -> RateLimitDecision:
        return self.reserve(
            [
                self._limit(
                    "invitation_resend_actor",
                    str(actor_user_id),
                    self.settings.invitation_resend_actor,
                ),
                self._limit(
                    "invitation_resend_target",
                    str(target_user_id),
                    self.settings.invitation_resend_target,
                ),
            ],
            action="invitation_resend",
        )

    def signin_limits(self, normalized_email: str, client_host: str) -> list[LimitKey]:
        combined = f"{normalized_email}\0{client_host}"
        return [
            self._limit("signin_account", normalized_email, self.settings.signin_account),
            self._limit("signin_ip", client_host, self.settings.signin_ip),
            self._limit("signin_combined", combined, self.settings.signin_combined),
        ]

    def reserve(
        self, limits: Sequence[LimitKey], *, action: str
    ) -> RateLimitDecision:
        if not self.settings.enabled:
            return RateLimitDecision(allowed=True, redis_available=False)
        if not limits:
            return RateLimitDecision(allowed=True, redis_available=True)
        client = self._client or _get_client(self.settings)
        if client is None:
            self._log_redis_unavailable(action)
            return RateLimitDecision(allowed=True, redis_available=False)
        args: list[int] = []
        for item in limits:
            args.extend([item.policy.limit, item.policy.window_seconds])
        try:
            raw_result = client.eval(
                _RESERVE_SCRIPT,
                len(limits),
                *[item.key for item in limits],
                *args,
            )
        except Exception:
            self._log_redis_unavailable(action)
            return RateLimitDecision(allowed=True, redis_available=False)

        allowed = bool(int(raw_result[0]))
        if allowed:
            return RateLimitDecision(allowed=True, redis_available=True)
        retry_after = _bounded_retry_after(int(raw_result[1]))
        index = max(0, min(int(raw_result[2]) - 1, len(limits) - 1))
        return RateLimitDecision(
            allowed=False,
            retry_after_seconds=retry_after,
            redis_available=True,
            limiter_category=limits[index].category,
        )

    def clear(self, keys: Sequence[str], *, action: str) -> None:
        if not self.settings.enabled or not keys:
            return
        client = self._client or _get_client(self.settings)
        if client is None:
            self._log_redis_unavailable(action)
            return
        try:
            client.delete(*keys)
        except Exception:
            self._log_redis_unavailable(action)

    def _limit(
        self, category: str, identifier: str, policy: RateLimitPolicy
    ) -> LimitKey:
        key_material = str(identifier)
        return LimitKey(
            category=category,
            key=self.redis_key(category, key_material),
            policy=policy,
        )

    def redis_key(self, category: str, identifier: str) -> str:
        key_material = str(identifier).encode("utf-8", errors="surrogateescape")
        digest = hmac.new(
            self.settings.hmac_secret.encode("utf-8"),
            f"auth-rate-limit:{category}:".encode("utf-8") + key_material,
            hashlib.sha256,
        ).hexdigest()
        return ":".join(
            (
                self.settings.namespace,
                _KEY_VERSION,
                "auth-rate-limit",
                category,
                digest[:32],
            )
        )

    def _log_redis_unavailable(self, action: str) -> None:
        logger.warning(
            "auth_rate_limit_unavailable",
            extra={"action": action, "redis_protection_available": False},
        )


def get_auth_rate_limiter(
    settings: AuthRateLimitSettings | None = None,
) -> AuthRateLimiter:
    return AuthRateLimiter(settings or get_auth_rate_limit_settings())

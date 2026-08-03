# Authentication Rate Limiting Security Notes

Status: IMPLEMENTED for application-level auth throttling; production approval still required for Redis deployment, secrets, and trusted proxy configuration.

## Scope

This repository implements Redis-backed rate limiting for the authentication, password reset, activation, and invitation resend flows. The limiter is designed to be privacy-safe, fail-open when Redis is unavailable, and generic in public responses.

## Exact rate-limit policies

The defaults are configured in `backend/app/config.py` and the example environment is in `backend/.env.example`.

- `signin_account`: 5 requests / 900 seconds
- `signin_ip`: 20 requests / 900 seconds
- `signin_combined`: 5 requests / 900 seconds
- `forgot_account`: 3 requests / 900 seconds
- `forgot_ip`: 10 requests / 900 seconds
- `reset_validate_token`: 10 requests / 900 seconds
- `reset_validate_ip`: 30 requests / 900 seconds
- `reset_complete_token`: 5 requests / 900 seconds
- `reset_complete_ip`: 20 requests / 900 seconds
- `activation_validate_token`: 10 requests / 900 seconds
- `activation_validate_ip`: 30 requests / 900 seconds
- `activation_complete_token`: 5 requests / 900 seconds
- `activation_complete_ip`: 20 requests / 900 seconds
- `invitation_resend_actor`: 10 requests / 900 seconds
- `invitation_resend_target`: 5 requests / 900 seconds

All limits and windows are strictly positive and bounded at settings construction time; invalid values raise configuration errors.

## Redis dependency and lifecycle

- Redis is required for enforcement of the distributed counters.
- The limiter uses a single Lua script to atomically read and increment counts.
- Each key is assigned a bounded TTL via Redis `expire` or by falling back to the configured window when the key is already present.
- Redis connection failures are treated as `fail_open`: the request is allowed through and the warning is logged, but no HTTP 500 is raised.
- The shared client is closed on application shutdown via `close_auth_rate_limit_client()`.

## Privacy-safe key derivation

Redis keys never include raw email addresses, IP addresses, password values, reset tokens, activation tokens, JWTs, Authorization headers, or bearer secrets.

The key material is derived as:

- namespace + version + `auth-rate-limit` + category + HMAC-SHA256 digest over the domain-separated payload
- the payload is composed as `auth-rate-limit:{category}:<identifier>`
- the HMAC secret is derived from `AUTH_RATE_LIMIT_HMAC_SECRET` when set, otherwise the code intentionally falls back to `AUTH_JWT_SECRET` only in local/test-only conditions

This ensures deterministic, domain-separated, privacy-safe keys without storing sensitive values in Redis.

## HTTP responses and retry behavior

- Public responses are intentionally generic: `Trop de tentatives. Reessayez plus tard.`
- `Retry-After` is capped at 3600 seconds and emitted only for a true throttle decision.
- `request.client.host` is used for client identity; forwarded headers are not trusted.
- Successful sign-ins clear only the account-specific and combined account+IP counters. The shared IP counter remains intact so global IP protection continues to work.
- Failed sign-ins do not clear limiter state.
- Blocked forgot-password and reset/activation requests do not create or consume valid tokens, and do not invoke email providers after a Redis abuse block.

## Operational diagnostics and safe handling

- Redis failures are logged without raw keys or sensitive identifiers.
- Operational teams should monitor log entries for the `auth_rate_limit_unavailable`, `auth_signin_failed`, and `auth_signin_succeeded` events.
- Safe limiter-state clearing guidance: clear only account-related limiter keys after a verified successful sign-in; do not clear the IP bucket because it protects the broader environment.
- Session revocation remains a separate Phase 8B.2 concern.
- Proxy, trusted-host, and security-header enforcement remain a separate Phase 8B.3 concern.

## Production guidance

Production environments should use a dedicated `AUTH_RATE_LIMIT_HMAC_SECRET` instead of reusing the JWT secret. This avoids cross-scope key reuse and keeps the limiter resilient to future token rotation and secret changes.

The example `.env.example` file documents the safer production requirement and the local/test fallback explicitly. Real production secrets must never be committed into the repository.

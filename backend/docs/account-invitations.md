# Account invitation foundation

Phase 5A.1 introduces a separate activation lifecycle. `is_active` remains the administrative enable/disable flag; `activation_status` controls whether credentials have been established.

Invitation resend throttling is persistence-backed. The latest invitation creation timestamp enforces `INVITATION_RESEND_COOLDOWN_SECONDS` across processes without Redis. It is intentionally bounded and can be set to zero in isolated tests.

Invitation state is committed before delivery. If delivery raises, the new token is immediately invalidated and a secret-free `invitation.delivery_failed` audit is committed. The pending user remains available for a later resend. The default `noop` provider performs no external I/O and never retains the activation URL. The `capture` provider and URL response exposure require explicit local/test configuration.

This first Alembic revision is a legacy-schema adoption migration: it expects the existing `users` table and adds the new column/table. Existing rows receive `activation_status=active`.


## Local end-to-end activation

Activation-link exposure is disabled by default. For an isolated local API process only, set:

```text
INVITATION_EMAIL_PROVIDER=capture
INVITATION_EXPOSE_ACTIVATION_URL=true
FRONTEND_ACTIVATION_URL=http://localhost:5173/activate
```

Sign in locally as an administrator, open **Administration → Utilisateurs**, invite a user (or resend a pending invitation), then use the one-time **Ouvrir le test local** action. The activation page removes the token from the visible URL immediately, validates it, and lets the invited user establish a password.

The API includes `invitation_delivery.activation_url` only when provider mode is exactly `capture` and exposure is explicitly enabled. Default `noop` mode, capture without the exposure flag, and production defaults return `null`. The URL is never listed later or logged. Restart without the exposure flag after local testing. Use only a disposable local database with the Phase 5A.1 schema; never apply or test this workflow against the live database.

## Password lifecycle foundation (Phase 5B.1a.1)

`users.token_version` is embedded as `ver` in newly issued access tokens. Legacy tokens without `ver` are treated as version zero only while the user remains at version zero; an actual credential replacement increments the version and invalidates prior sessions. Invitation activation and administrator password resets are credential replacements; opportunistic signin hash rehashing is maintenance only and does not change the version. `password_reset_tokens` stores one-time reset-token lifecycle rows. Public forgot-password token issuance and token validation are implemented in Phase 5B.1a.3a; reset completion remains deferred to Phase 5B.1a.3b.

### Password hash write-path token-version policy

Every application or operational path that writes `users.password_hash` has an explicit token-version policy:

- `app/services/invitation_service.py:create_invited_user` creates invited users with `password_hash=None`. This is not an established credential and does not increment `token_version`.
- `app/services/invitation_service.py:complete_activation` establishes the invited user's password. This is a credential replacement and increments `token_version` transactionally with activation and token consumption.
- `app/services/admin_user_service.py:reset_password` replaces an existing user's password. This increments `token_version` and invalidates outstanding unconsumed password-reset tokens in the same transaction.
- `app/services/auth_service.py:authenticate_user` may opportunistically rehash the same verified password during signin. This is maintenance only and does not increment `token_version`.
- `scripts/create_admin_user.py` creates a bootstrap administrator with the default initial `token_version` of zero. When run with `--update-existing`, it deliberately replaces that administrator's password and increments `token_version`.

## Authenticated change-own-password (Phase 5B.1a.2)

`POST /api/v1/auth/password/change` lets an already authenticated, active user replace their own password. The request requires the current password, the new password, and a matching confirmation. The endpoint does not issue a replacement access token; a successful response explicitly sets `reauthentication_required=true` so the client signs in again.

The flow reuses the existing password primitives: current-password verification, Argon2 password hashing, Unicode preservation, and the existing 1024-byte UTF-8 password limit. It rejects empty new passwords, confirmation mismatches, same-password reuse, and oversized passwords without adding a separate password-complexity policy or trimming password values.

The password-change service is the transaction owner. After the authenticated dependency validates the JWT and `ver`, the service re-queries the same user with `SELECT ... FOR UPDATE` before verifying the current password. On success, the same transaction replaces `users.password_hash`, increments `users.token_version` exactly once, updates `users.updated_at`, invalidates outstanding unconsumed and not-yet-invalidated `password_reset_tokens`, writes a secret-free `password_changed` audit event, and commits once. Any failure rolls back the password hash, token version, reset-token invalidations, and audit state.

Incrementing `users.token_version` makes the JWT used for the change request stale after the response completes. The next authenticated request with that old JWT receives the existing generic authentication failure. Signing in with the old password fails; signing in with the new password issues a JWT whose `ver` matches the incremented user version.

The PostgreSQL row lock is required so two simultaneous password-change requests using the same old password cannot both succeed: the first transaction locks and changes the credential, while the second waits and then verifies against the changed hash. SQLite tests validate the service flow and rollback behavior, but SQLite does not prove PostgreSQL row-lock semantics. The disposable PostgreSQL concurrency rehearsal validates the intended row-lock behavior outside SQLite.

Deferred work remains unchanged for the authenticated change-password UI: no frontend change-password page in this phase and no durable session/device management.

## Neutral forgot-password and reset-token validation (Phase 5B.1a.3a)

`POST /api/v1/auth/password/forgot` is public and returns a neutral `202 Accepted` response for every syntactically valid email address, including unknown users, pending users, disabled users, users without a password, cooldown-suppressed requests, and delivery failures. Eligible accounts must be active, have `activation_status=active`, and have a stored `password_hash`. The response does not expose account existence. Exact timing equality is not claimed; the implementation avoids unnecessary provider delivery and token work when the account is not eligible.

Eligible requests generate a cryptographically random reset token with `secrets.token_urlsafe(32)`. Only the SHA-256 digest is stored in `password_reset_tokens.token_hash`, which remains a 64-character hexadecimal value. The raw token and full reset URL are never persisted. Tokens expire according to `PASSWORD_RESET_TOKEN_TTL_MINUTES`, defaulting to 30 minutes with bounded positive configuration. Before issuing a replacement token, the service invalidates only outstanding unconsumed and not-yet-invalidated tokens for that same user; consumed, already invalidated, and other-user tokens are left unchanged.

Cooldown is database-backed per eligible account via `PASSWORD_RESET_RESEND_COOLDOWN_SECONDS`, defaulting to 60 seconds. During cooldown the service creates no token, invalidates no existing usable token, calls no provider, and returns the same neutral public response.

Password-reset delivery uses a dedicated abstraction with `noop` and `capture` providers. `PASSWORD_RESET_EMAIL_PROVIDER=noop` is the default and requires no mail credentials or external I/O. `capture` is for disposable development testing only. Public `reset_url` exposure is disabled by default and requires both `PASSWORD_RESET_EMAIL_PROVIDER=capture` and `PASSWORD_RESET_EXPOSE_URL=true`. This exposure is not enumeration-safe because eligible accounts can receive a usable URL; production configuration must keep `PASSWORD_RESET_EXPOSE_URL=false`. `noop` never exposes a URL, even if exposure is mistakenly enabled. Unknown provider values fail closed with a password-reset configuration error.

The password-reset request service is the transaction owner. For eligible non-cooldown requests it creates and flushes the token row, attempts the configured local provider, records delivery status, writes secret-free audit metadata, and commits once. If provider delivery fails, the token is marked `failed` and invalidated before commit so it cannot later be used unexpectedly, a safe `password_reset_delivery_failed` audit event is recorded, and the public response remains neutral. Database failures roll back token creation, prior-token invalidation, and audit state, and return only a generic service failure. Future real external email delivery may need an outbox/idempotency design; that architecture is not part of this checkpoint.

Audit events for eligible known users use `password_reset_requested` and, when provider delivery fails, `password_reset_delivery_failed`. Audit metadata is limited to safe status, provider mode, TTL, and cooldown suppression. It must not contain raw tokens, token hashes, reset URLs, passwords, JWTs, Authorization headers, or provider credentials.

`POST /api/v1/auth/password/reset/validate` is public and validates the supplied raw token by hashing it and comparing the stored digest. It returns `{"valid": true, "expires_at": ...}` for valid tokens. Invalid, expired, consumed, and invalidated tokens return the existing safe error shape with code `invalid`, `expired`, or `consumed`; invalidated tokens map to `invalid`. Validation does not consume the token, mutate timestamps, return user identity, return email, reveal token hashes, or reveal whether another valid token exists.

Deferred work for Phase 5B.1a.3b: reset completion, password replacement through reset tokens, `token_version` increment on reset completion, reset-token consumption, and post-reset signin behavior. Frontend reset pages, Microsoft Graph/SMTP delivery, Redis/IP rate limiting, MFA, refresh tokens, and durable session/device management also remain deferred.

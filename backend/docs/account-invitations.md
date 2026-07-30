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

`users.token_version` is embedded as `ver` in newly issued access tokens. Legacy tokens without `ver` are treated as version zero only while the user remains at version zero; an actual credential replacement increments the version and invalidates prior sessions. Invitation activation and administrator password resets are credential replacements; opportunistic signin hash rehashing is maintenance only and does not change the version. `password_reset_tokens` is schema-only in this checkpoint; public forgot/reset APIs are deferred to Phase 5B.1a.3.

### Password hash write-path token-version policy

Every application or operational path that writes `users.password_hash` has an explicit token-version policy:

- `app/services/invitation_service.py:create_invited_user` creates invited users with `password_hash=None`. This is not an established credential and does not increment `token_version`.
- `app/services/invitation_service.py:complete_activation` establishes the invited user's password. This is a credential replacement and increments `token_version` transactionally with activation and token consumption.
- `app/services/admin_user_service.py:reset_password` replaces an existing user's password. This increments `token_version` and invalidates outstanding unconsumed password-reset tokens in the same transaction.
- `app/services/auth_service.py:authenticate_user` may opportunistically rehash the same verified password during signin. This is maintenance only and does not increment `token_version`.
- `scripts/create_admin_user.py` creates a bootstrap administrator with the default initial `token_version` of zero. When run with `--update-existing`, it deliberately replaces that administrator's password and increments `token_version`.

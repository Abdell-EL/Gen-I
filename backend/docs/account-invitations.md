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

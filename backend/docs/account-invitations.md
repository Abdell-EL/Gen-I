# Account invitation foundation

Phase 5A.1 introduces a separate activation lifecycle. `is_active` remains the administrative enable/disable flag; `activation_status` controls whether credentials have been established.

Invitation resend throttling is persistence-backed. The latest invitation creation timestamp enforces `INVITATION_RESEND_COOLDOWN_SECONDS` across processes without Redis. It is intentionally bounded and can be set to zero in isolated tests.

Invitation state is committed before delivery. If delivery raises, the new token is immediately invalidated and a secret-free `invitation.delivery_failed` audit is committed. The pending user remains available for a later resend. The default `noop` provider performs no external I/O and never retains the activation URL. The `capture` provider and URL response exposure require explicit local/test configuration.

This first Alembic revision is a legacy-schema adoption migration: it expects the existing `users` table and adds the new column/table. Existing rows receive `activation_status=active`.

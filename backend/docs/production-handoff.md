# Production Handoff

Status labels used in this package:

- **IMPLEMENTED**: present in the repository/application.
- **VALIDATED**: covered by repository tests, CI workflow gates, or script checks.
- **REQUIRES IT / NOT YET VALIDATED**: needs company IT, infrastructure, security, tenant, or production-environment approval and validation.

## Purpose

Genius Services is an internal AI knowledge platform for FDE operational articles. It provides authenticated agent search/chat over DOCX knowledge articles, cited source navigation, original document download, administrator user management, document ingestion/version updates, feedback, and operational analytics.

## Audience

This handoff package is for the company IT, infrastructure, security, and deployment teams that will approve, configure, deploy, operate, recover, and evaluate the production platform. The project developer is not deploying the application.

## Current scope

| Status | Scope |
| --- | --- |
| IMPLEMENTED | Single-VM Docker Compose application model with FastAPI API, React/Vite static frontend build, PostgreSQL, Redis, Milvus, Ollama, MinIO, and etcd dependencies. |
| IMPLEMENTED | Manual GitHub Actions deployment workflow that SSHes to an existing VM and runs `scripts/deploy_vm.sh`. |
| VALIDATED | Quality, Security, and PostgreSQL Integration workflows are the expected deployment gates for the exact target Git SHA. |
| REQUIRES IT / NOT YET VALIDATED | Production hostname, DNS, TLS, Nginx/static hosting, firewall policy, GitHub production environment, secrets, VM sizing, monitoring, restore drills, and launch approval. |

Production deployment requires IT approval and IT-owned configuration before any live launch.

## Architecture summary

| Layer | Status | Details |
| --- | --- | --- |
| Frontend | IMPLEMENTED | React 19, TypeScript, Vite build under `backend/frontend`. Production deploy builds with `npm ci` and `npm run build`, then switches a static release symlink. |
| API | IMPLEMENTED | FastAPI app in `backend/app/main.py`, mounted under `/api/v1`; Docker image is built from `backend/Dockerfile`. |
| Database | IMPLEMENTED | PostgreSQL stores users, auth lifecycle state, document/version/chunk metadata, ingestion jobs, audit, retrieval, analytics, and feedback. |
| Cache | IMPLEMENTED | Redis stores bounded retrieval/cache data and is not the source of truth. |
| Vector store | IMPLEMENTED | Milvus stores derived BGE-M3 vector records in collection `sogetrel_chunks`. |
| Generation | IMPLEMENTED | Ollama generate API uses `llama3.2:3b` by default with a configured 1B fast-model option disabled by default. |
| Edge | REQUIRES IT / NOT YET VALIDATED | Nginx/TLS/static serving are not installed or configured by this repository. A template is provided in `deployment/nginx/lab-ia-genius.conf.template`. |

## Implemented capabilities

| Capability | Status | Evidence |
| --- | --- | --- |
| JWT signin and role-protected routes | IMPLEMENTED | `POST /api/v1/auth/signin`, `GET /api/v1/auth/me`, `require_any_role("admin", "agent")`, `require_role("admin")`. |
| Agent search/chat | IMPLEMENTED | `POST /api/v1/search`, `POST /api/v1/keyword-search`, `POST /api/v1/chat`, `POST /api/v1/chat/stream`. |
| Source navigation and downloads | IMPLEMENTED | `GET /api/v1/knowledge/articles/{source_document_id}`, `GET /api/v1/knowledge/documents/{source_document_id}/original`. |
| Admin user lifecycle | IMPLEMENTED | `/api/v1/admin/users`, invitation resend, admin password reset, activation, forgot/reset password, and change-own-password routes. |
| Document upload and versioning | IMPLEMENTED | `/api/v1/admin/ingestion/docx`, `/api/v1/admin/knowledge/documents/{source_document_id}/versions`. |
| Operational analytics | IMPLEMENTED | Admin analytics routes for users, questions, operations, feedback, and knowledge intelligence. |
| Health endpoint | IMPLEMENTED | `GET /api/v1/health` returns JSON with top-level `status`; deployment requires `status=healthy`. |
| CI gates | VALIDATED | `.github/workflows/quality.yml`, `security.yml`, and `postgres-integration.yml`. |
| Production deployment execution | REQUIRES IT / NOT YET VALIDATED | A hardened manual workflow exists, but this phase does not deploy. |

## Deployment model

The production path is a manual GitHub Actions workflow at `.github/workflows/deploy-vm.yml`. It requires the operator to type `DEPLOY`, verifies that required CI workflows passed for the same commit SHA, connects to the VM over SSH, copies `scripts/deploy_vm.sh`, and runs it on the VM.

The VM script checks the git worktree, checks out the exact SHA, validates Compose, builds the API image, builds frontend static assets, creates a pre-migration PostgreSQL backup, prints Alembic current/head, runs `alembic upgrade head`, recreates only the `api` service, verifies `/api/v1/health` JSON `status=healthy`, switches the frontend symlink, and verifies the frontend URL.

See [Deployment](deployment.md), [Deployment Checklist](deployment-checklist.md), and [GitHub Production Environment](github-production-environment.md).

## Security model

| Area | Status | Notes |
| --- | --- | --- |
| Authentication | IMPLEMENTED | Local email/password authentication with Argon2id password hashes and HS256 JWT access tokens. |
| Authorization | IMPLEMENTED | Application roles are `admin` and `agent`; admin-only routes use `require_role("admin")`. |
| Token invalidation | IMPLEMENTED | `users.token_version` is embedded in JWT claim `ver`; credential replacement increments it. This invalidates previously issued JWTs but is not a durable session/device revocation mechanism. |
| Password reset | IMPLEMENTED | One-time reset-token digests stored in PostgreSQL; raw tokens are not persisted. |
| Authentication rate limiting | IMPLEMENTED | Application-level Redis-backed rate limiting covers sign-in, activation, forgot/reset password, and invitation resend, with privacy-safe HMAC keys, generic responses, and fail-open behavior. Production Redis deployment, trusted proxy interpretation, and any global gateway/API-wide throttling still require IT/security validation. |
| Invitation delivery | IMPLEMENTED | `noop` and `capture` providers only; no real email provider is implemented. |
| CI security scans | VALIDATED | pip-audit policy, npm audit policy, Gitleaks, Trivy filesystem, and Trivy backend image scan are defined. |
| Entra ID / SSO | REQUIRES IT / NOT YET VALIDATED | Microsoft Entra ID is not implemented. |
| Outlook / Graph delivery | REQUIRES IT / NOT YET VALIDATED | Requires tenant approval and implementation; current provider modes do not send production email. |
| TLS and edge headers | REQUIRES IT / NOT YET VALIDATED | Template supplied, but production Nginx/TLS is IT-owned. |

## Data stores

| Store | Status | Production role |
| --- | --- | --- |
| PostgreSQL | IMPLEMENTED | Source of truth for application data, users, password lifecycle, document metadata, chunks, embeddings metadata, audits, retrievals, analytics, and feedback. |
| DOCX upload storage | IMPLEMENTED | Original uploaded DOCX files are stored under `KB_UPLOAD_ROOT`, default `data/uploads/kb_articles`; this path must be backed up outside Git. |
| Milvus | IMPLEMENTED | Derived vector index. It can be backed up directly or regenerated from PostgreSQL plus original DOCX inputs; IT must choose and rehearse a strategy. |
| Redis | IMPLEMENTED | Cache only; may be rebuilt. |
| Ollama model store | IMPLEMENTED | Local model files under the VM's Ollama volume; models may need re-pull/reinstall after recovery. |
| Frontend releases | IMPLEMENTED | Immutable static build folders and a `current` symlink; IT-owned web server serves the symlink. |

## External dependencies

| Dependency | Status | Notes |
| --- | --- | --- |
| GitHub Actions | IMPLEMENTED | Manual deploy workflow and CI workflows are defined. |
| Git repository access | REQUIRES IT / NOT YET VALIDATED | VM deployment user must be able to fetch the target SHA. |
| SSH to VM | REQUIRES IT / NOT YET VALIDATED | Requires approved deploy user, key, known-hosts, and optional port. |
| Docker Engine and Docker Compose v2 | REQUIRES IT / NOT YET VALIDATED | Required on the VM. |
| Node/npm | REQUIRES IT / NOT YET VALIDATED | Required on the VM for frontend production builds. |
| Nginx or approved static web server | REQUIRES IT / NOT YET VALIDATED | Required for frontend serving and `/api/` reverse proxy when using same-origin deployment. |
| TLS certificate authority | REQUIRES IT / NOT YET VALIDATED | Certificate issuance and renewal are IT-owned. |
| Package/model registries | REQUIRES IT / NOT YET VALIDATED | VM must reach Python/Node/Docker/model sources or use approved internal mirrors. |

## Operational documents

- [Deployment](deployment.md)
- [Deployment Checklist](deployment-checklist.md)
- [GitHub Production Environment](github-production-environment.md)
- [Backup and Restore Runbook](backup-restore-runbook.md)
- [Operations Runbook](operations-runbook.md)
- [Known Limitations](known-limitations.md)
- [Launch Readiness Checklist](launch-readiness-checklist.md)
- [Responsibility Matrix](responsibility-matrix.md)
- [Account Invitations and Password Lifecycle](account-invitations.md)
- [CI Quality, Security, and PostgreSQL Integration](ci.md)
- [Performance Benchmark Runbook](performance-benchmark.md)
- [Ollama Model Benchmark Runbook](ollama-model-benchmark.md)
- Nginx template: `deployment/nginx/lab-ia-genius.conf.template`

## Responsible team split

| Area | Status | Lead role |
| --- | --- | --- |
| Product code behavior | IMPLEMENTED | Application developer |
| CI workflow maintenance | IMPLEMENTED | Application developer, with IT review for deployment workflow |
| Production approval | REQUIRES IT / NOT YET VALIDATED | Management approver and IT/deployment team |
| VM, Docker, Nginx, TLS, DNS, firewall | REQUIRES IT / NOT YET VALIDATED | IT/deployment team |
| GitHub production secrets/environment | REQUIRES IT / NOT YET VALIDATED | IT/deployment team and security team |
| Identity/email provider approvals | REQUIRES IT / NOT YET VALIDATED | Security team and IT/deployment team |
| Knowledge article ownership | IMPLEMENTED | Business knowledge owner and platform administrator |
| Incident response and recovery | REQUIRES IT / NOT YET VALIDATED | IT/deployment team, security team, and platform administrator |

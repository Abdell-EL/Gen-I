# CI quality, security, and PostgreSQL integration

Phase 6A adds GitHub Actions workflows for launch hardening. These workflows are CI only: they do not deploy, publish images, mutate live databases, or start the complete Milvus/Ollama application stack.

## Workflow inventory

| Workflow | File | Purpose | Gate recommendation |
| --- | --- | --- | --- |
| Quality | `.github/workflows/quality.yml` | Backend, frontend, container config, repository hygiene | Required |
| Security | `.github/workflows/security.yml` | Dependency, secret, filesystem, and image scans | Scheduled and PR signal |
| PostgreSQL Integration | `.github/workflows/postgres-integration.yml` | Disposable PostgreSQL 17 migration and concurrency tests | Manual/weekly until runtime is known |

## Triggers

Quality runs on pull requests, manual dispatch, and pushes to `main`, `master`, `develop`, and the active development branch `phase-2-auth-security`. Security runs on pull requests, weekly schedule, and manual dispatch. PostgreSQL integration runs on weekly schedule and manual dispatch.

## Required gates

Recommended branch protection required checks:

- `backend-quality`
- `frontend-quality`
- `container-quality`
- `repository-hygiene`

Do not enable branch protection automatically from this repository change. Configure it in GitHub after the first successful Actions run confirms the check names.

## Backend quality checks

`backend-quality` uses Python 3.12 and performs:

- dependency installation from `backend/requirements.txt`;
- `python -m compileall app scripts tests`;
- full `unittest` discovery under `backend/tests`;
- OpenAPI generation plus critical route inventory verification;
- Alembic config load and single-head revision-chain check;
- migration-focused lifecycle tests.

The OpenAPI inventory intentionally covers authentication, chat, streaming, original document download, article preview, admin version update/history, feedback, and knowledge analytics routes.

## Frontend quality checks

`frontend-quality` uses Node 22, `npm ci`, and the locked package set from `backend/frontend/package-lock.json`. It runs:

- `npm test`;
- `npm run lint`;
- `npm run build`.

## Container and repository hygiene checks

`container-quality` builds the backend Docker image and runs `docker compose config --quiet` for both compose files. It does not start the full stack and does not pull/run Milvus or Ollama.

`repository-hygiene` fails on tracked `.env` files except approved examples, private key/certificate/database artifacts, frontend `dist`, Python caches, local virtual environments, token/reset artifacts, and JWT-like or private-key contents. It prints paths and rule names only, not matched values.

## Security thresholds

Security jobs use least-privilege `contents: read`. Current action references use stable tags rather than immutable SHAs; pinning all third-party actions to commit SHAs is a remaining supply-chain hardening item.

- `pip-audit`: produces JSON and applies the repository policy in `.github/scripts/pip_audit_policy.py`. High/critical findings fail. Lower or unscored findings are reported by count for triage because pip-audit severity metadata is not uniformly available across advisories.
- `npm audit`: runs in JSON mode and applies `.github/scripts/npm_audit_policy.py`. High/critical advisories fail by default; low/moderate advisories do not block.
- Gitleaks: scans with redaction enabled and fails on confirmed leaks.
- Trivy filesystem and backend image scans: fail on HIGH/CRITICAL findings where a fix is available (`ignore-unfixed: true`).

Avoid broad suppressions. Add an ignore only after documenting a verified false positive.

### Temporary npm audit exception

Temporary exception owner: Phase 6A security owner.

Advisory `GHSA-qwww-vcr4-c8h2` currently affects `react-router` and `react-router-dom` `7.18.2`. The reported issue is an RSC mode CSRF bypass for React Router action execution. This application is a client-rendered Vite SPA and does not use React Server Components, RSC server actions, or unstable RSC APIs, so the vulnerable execution path is considered unreachable in the current architecture.

The exception is package/advisory-specific in `.github/scripts/npm_audit_policy.py`: only `GHSA-qwww-vcr4-c8h2` for `react-router`, plus the corresponding `react-router-dom` transitive finding through that exact advisory, is accepted. Any other current or future high/critical npm advisory still fails CI.

`npm audit fix --force` is rejected for this finding because npm proposes moving to `react-router-dom@7.11.0`, which is an unsafe forced downgrade from the tested `7.18.2` lockfile state. The remediation target is a compatible patched React Router release after it is available and validated with `npm test`, `npm run lint`, and `npm run build`.

The exception expires after `2026-08-17`; CI fails automatically on `2026-08-18` if the advisory remains. Re-evaluate before expiry, either by upgrading to a tested compatible patched React Router release or by removing the exception if the application starts using RSC APIs.

## PostgreSQL bootstrap strategy

The Alembic chain adopts an existing schema. It cannot create a blank database from scratch because the first revisions alter the legacy `users` table and add lifecycle token tables.

The PostgreSQL integration workflow uses a disposable PostgreSQL 17 service database named `lab_ia_genius_ci`. Before migrations, `backend/scripts/ci_bootstrap_postgres_schema.py` creates only the minimal legacy schema needed by the migrations and integration tests:

- `departments`;
- legacy `users` without `activation_status` or `token_version`;
- `audit_logs`.

The bootstrap inserts no departments, users, emails, hashes, tokens, retrieval rows, audit rows, embeddings, or document content. It rejects PostgreSQL URLs that point to known live databases (`labia`, `sogetrel_kb`) and requires the disposable database name to contain `ci`. After bootstrap, CI runs `alembic upgrade head`, verifies `alembic_version`, required lifecycle tables/columns/indexes, and zero product rows before running guarded integration tests.

The guarded tests require:

- `RUN_POSTGRES_INTEGRATION_TESTS=true`;
- `POSTGRES_INTEGRATION_DATABASE_URL=<disposable PostgreSQL URL>`.

They currently cover concurrent own-password changes and concurrent reset completion. Add future PostgreSQL-only version-update concurrency tests under `backend/tests/postgres_integration` with the same guard.

## Local equivalents

Run the non-destructive local quality helper from the repository root:

```bash
scripts/ci_local.sh
```

The helper runs backend compile/tests/OpenAPI/Alembic checks, frontend install/test/lint/build, Docker build, compose config, and repository hygiene. It does not run PostgreSQL integration or mutate a live database.

To rehearse PostgreSQL integration manually, use a disposable database only:

```bash
cd backend
export RUN_POSTGRES_INTEGRATION_TESTS=true
export POSTGRES_INTEGRATION_DATABASE_URL=postgresql+psycopg2://kb_user:kb_password@127.0.0.1:5432/lab_ia_genius_ci
export DATABASE_URL="$POSTGRES_INTEGRATION_DATABASE_URL"
python scripts/ci_bootstrap_postgres_schema.py
alembic -c alembic.ini upgrade head
python ../.github/scripts/verify_postgres_schema.py
python -m unittest discover -s tests/postgres_integration
```

Never run that sequence against `labia`, `sogetrel_kb`, or any database containing product rows.

## Expected runtime

Initial runs may be slower because Python, Node, Trivy, and Docker caches are cold. Expected ranges after caches warm:

- backend quality: 3-8 minutes, depending on Python dependency installation;
- frontend quality: 1-3 minutes;
- container quality: 2-6 minutes;
- security: 5-12 minutes;
- PostgreSQL integration: 3-8 minutes.

## Failure interpretation

- Backend unit failures are product regressions unless they are deterministic CI environment issues.
- OpenAPI route failures mean a critical contract was renamed or removed and needs an explicit review.
- Alembic failures mean the migration chain or bootstrap assumption changed.
- Repository hygiene failures usually indicate generated or sensitive files were accidentally staged.
- Security failures need dependency triage or a documented false-positive decision.
- PostgreSQL integration failures usually indicate row-locking, migration, or cleanup behavior changed.

## First remote-run expectations

The first GitHub-hosted run may expose workflow-only defects not visible locally: action version changes, dependency resolver slowness, Trivy database download issues, or Gitleaks rule differences. Do not call CI complete until the GitHub Actions runs pass on the remote branch.

## Deferred work

Deferred from Phase 6A:

- deployment/CD, registry publishing, cloud infrastructure, Kubernetes, and production rollout;
- Milvus/Ollama live integration in CI;
- dependency-update automation such as Dependabot/Renovate;
- full third-party action SHA pinning;
- branch protection enablement through GitHub settings.

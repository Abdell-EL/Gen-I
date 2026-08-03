# Deployment Checklist

Use this checklist for a controlled production deployment by the company IT/deployment team. Do not deploy unless every go/no-go item is explicitly resolved.

Status labels:

- **IMPLEMENTED**: present in the repository/application.
- **VALIDATED**: covered by repository checks or an operator check.
- **REQUIRES IT / NOT YET VALIDATED**: requires IT-owned production configuration, approval, or verification.

## Pre-deployment

| Item | Status | Evidence or validation |
| --- | --- | --- |
| Approved production hostname | REQUIRES IT / NOT YET VALIDATED | IT-approved hostname, for example `<app-hostname.example.internal>`. |
| DNS record | REQUIRES IT / NOT YET VALIDATED | Hostname resolves to the production VM or approved load balancer. |
| TLS certificate | REQUIRES IT / NOT YET VALIDATED | Valid certificate/key paths approved by IT; no certificate material is stored in Git. |
| Firewall policy | REQUIRES IT / NOT YET VALIDATED | Public ingress limited to approved HTTP/HTTPS ports; internal service ports are not exposed externally. |
| Linux VM requirements | REQUIRES IT / NOT YET VALIDATED | Ubuntu or approved Linux VM with sufficient CPU/RAM/disk for PostgreSQL, Milvus, Ollama, Redis, API, and static frontend. |
| Docker Engine | REQUIRES IT / NOT YET VALIDATED | `docker version` works for the deployment user. |
| Docker Compose v2 | REQUIRES IT / NOT YET VALIDATED | `docker compose version` succeeds; `scripts/deploy_vm.sh` requires Compose v2. |
| Node/npm | REQUIRES IT / NOT YET VALIDATED | `node --version` and `npm --version` available on the VM; Vite build uses `npm ci` and `npm run build`. |
| Git repository access | REQUIRES IT / NOT YET VALIDATED | VM can `git fetch --prune origin` and read the exact target SHA. |
| SSH deployment user | REQUIRES IT / NOT YET VALIDATED | Least-privilege user can access Docker and frontend release paths. |
| Disk/storage requirements | REQUIRES IT / NOT YET VALIDATED | Persistent mounts exist for `/data/postgres`, `/data/milvus`, `/data/ollama`, `/data/huggingface`, `backend/data`, backups, and frontend releases or IT-approved equivalents. |
| Backup directory | REQUIRES IT / NOT YET VALIDATED | `DEPLOY_BACKUP_DIR` exists or can be created; deployment script sets mode `700` and backup files mode `600`. |
| File permissions | REQUIRES IT / NOT YET VALIDATED | Deploy user can write `DEPLOY_BACKUP_DIR`, `DEPLOY_FRONTEND_RELEASES_PATH`, and parent of `DEPLOY_FRONTEND_CURRENT_PATH`. |
| GitHub production environment | REQUIRES IT / NOT YET VALIDATED | Environment named `production` exists with approval configured. |
| Required secrets and variables | REQUIRES IT / NOT YET VALIDATED | See [GitHub Production Environment](github-production-environment.md). |
| Exact target Git SHA | REQUIRES IT / NOT YET VALIDATED | Operator records immutable SHA; workflow deploys `${{ github.sha }}`. |
| Clean VM worktree | VALIDATED | Script refuses to deploy when tracked local changes exist. |
| Quality workflow green | VALIDATED | `.github/workflows/quality.yml` completed successfully for the exact SHA. |
| Security workflow green | VALIDATED | `.github/workflows/security.yml` completed successfully for the exact SHA. |
| PostgreSQL Integration workflow green | VALIDATED | `.github/workflows/postgres-integration.yml` completed successfully for the exact SHA. |
| Nginx/static frontend serving | REQUIRES IT / NOT YET VALIDATED | Configure from `deployment/nginx/lab-ia-genius.conf.template` or approved equivalent before deployment. |

## Deployment sequence

1. Confirm the target Git SHA and production approval.
2. In GitHub Actions, run `Deploy VM` for the target ref and type `DEPLOY`.
3. Let the workflow verify required CI runs for that exact SHA.
4. The workflow configures SSH with `DEPLOY_SSH_PRIVATE_KEY` and `DEPLOY_KNOWN_HOSTS`.
5. The workflow copies `scripts/deploy_vm.sh` to `/tmp/lab-ia-genius-deploy.sh` on the VM.
6. The VM script changes to `DEPLOY_PATH`.
7. The VM script validates that `DEPLOY_PATH` is a Git worktree and `DEPLOY_COMPOSE_FILE` exists.
8. The VM script validates frontend release configuration: `DEPLOY_FRONTEND_RELEASES_PATH`, `DEPLOY_FRONTEND_CURRENT_PATH`, `DEPLOY_FRONTEND_HEALTH_URL`, `VITE_API_BASE_URL`, and `VITE_AUTH_MODE=backend`.
9. The VM script validates a clean tracked worktree with `git diff --quiet` and `git diff --cached --quiet`.
10. The VM script records the previous Git ref.
11. The VM script fetches and checks out the exact target SHA in detached HEAD.
12. The VM script validates Compose with `docker compose -f "$DEPLOY_COMPOSE_FILE" config --quiet`.
13. The VM script builds the API image with `docker compose -f "$DEPLOY_COMPOSE_FILE" build api`.
14. The VM script builds the frontend from `backend/frontend` using `npm ci` and `npm run build`.
15. The VM script prepares a timestamped immutable frontend release directory but does not switch it yet.
16. The VM script creates a PostgreSQL custom-format backup through the `postgres` service:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" exec -T "$DEPLOY_DB_SERVICE" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' >"$backup_file"
```

17. The VM script verifies that the backup file is non-empty.
18. The VM script prints current Alembic revision:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" run --rm --no-deps api alembic -c alembic.ini current
```

19. The VM script prints target Alembic head:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" run --rm --no-deps api alembic -c alembic.ini heads
```

20. The VM script runs:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" run --rm --no-deps api alembic -c alembic.ini upgrade head
```

21. The VM script replaces only the API service:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" up -d --no-deps api
```

22. The VM script checks `DEPLOY_HEALTH_URL` until the response JSON has top-level `"status": "healthy"`. HTTP 200 alone is not sufficient.
23. The VM script atomically switches `DEPLOY_FRONTEND_CURRENT_PATH` to the prepared release.
24. The VM script verifies `DEPLOY_FRONTEND_HEALTH_URL` with an HTTP success response.

## Rollback behavior

| Condition | Behavior |
| --- | --- |
| Failure before API replacement | Script restores the previous Git checkout. Running API container is not replaced. |
| API health failure after replacement | Script checks out previous ref, rebuilds `api`, and recreates only `api`. Database schema is not downgraded. |
| Frontend health failure after symlink switch | Script restores prior frontend symlink, then rolls API code back. Database schema is not downgraded. |
| Rollback health failure | Workflow exits failed and manual VM intervention is required. |

Rollback restores application code and frontend symlink only. It does not automatically restore PostgreSQL and does not run Alembic downgrade.

## Nginx template validation

The tracked template is `deployment/nginx/lab-ia-genius.conf.template`. IT must copy it to an approved Nginx sites path, replace only `__HOSTNAME__`, `__TLS_CERTIFICATE_PATH__`, and `__TLS_CERTIFICATE_KEY_PATH__`, and leave internal services bound to localhost.

Validate syntax before reload:

```bash
sudo nginx -t
```

Reload without restarting active connections:

```bash
sudo systemctl reload nginx
```

Curl checks:

```bash
curl --fail --silent --show-error http://<hostname>/healthz
curl --fail --silent --show-error https://<hostname>/healthz
curl --fail --silent --show-error https://<hostname>/ >/dev/null
curl --fail --silent --show-error https://<hostname>/api/v1/health
```

Expected API health is JSON with top-level `"status":"healthy"`.

Rollback config procedure:

1. Before changing Nginx, copy the currently active approved config to a timestamped backup outside the repository.
2. Apply the new config and run `sudo nginx -t`.
3. If syntax validation fails, restore the prior config file and rerun `sudo nginx -t`.
4. If reload succeeds but runtime checks fail, restore the prior config file, run `sudo nginx -t`, then `sudo systemctl reload nginx`.
5. Do not restart Nginx unless IT accepts the connection impact and reload is insufficient.

## Post-deployment verification

| Check | Status | Expected result |
| --- | --- | --- |
| Signin test | REQUIRES IT / NOT YET VALIDATED | Approved test user signs in through frontend; `/api/v1/auth/me` returns user identity. |
| Agent question test | REQUIRES IT / NOT YET VALIDATED | Agent asks a known knowledge-base question and receives answer plus sources. |
| Source download | REQUIRES IT / NOT YET VALIDATED | Original DOCX download succeeds from `/api/v1/knowledge/documents/{source_document_id}/original`. |
| Admin analytics | REQUIRES IT / NOT YET VALIDATED | Admin dashboard loads user/question/operations/knowledge analytics. |
| Invitation/password lifecycle | REQUIRES IT / NOT YET VALIDATED | Approved email/provider mode supports invitation/reset flow, or accepted risk is recorded for `noop`. |
| Document upload | REQUIRES IT / NOT YET VALIDATED | Admin uploads a disposable approved DOCX in production only if business owner approves creating a real version. |
| API logs | REQUIRES IT / NOT YET VALIDATED | `docker compose -f "$DEPLOY_COMPOSE_FILE" logs --tail=200 api` shows no repeated errors. |
| Backup existence | VALIDATED | Backup exists in `DEPLOY_BACKUP_DIR`, is non-empty, and has restrictive permissions. |
| Monitoring confirmation | REQUIRES IT / NOT YET VALIDATED | IT monitoring observes frontend, API health, disk, PostgreSQL, Redis, Milvus, Ollama, and container status. |

## Go/no-go criteria

Go only when:

- Required Quality, Security, and PostgreSQL Integration workflows are green for the exact target SHA.
- GitHub `production` environment approval is complete.
- VM, DNS, TLS, firewall, Nginx/static serving, secrets, variables, and backups are approved by IT.
- `DEPLOY_HEALTH_URL` returns JSON `status=healthy` after deployment.
- Frontend verification succeeds.
- Post-deployment signin, agent question, source download, admin analytics, logs, backup, and monitoring checks pass or have formally accepted non-blocking risk.

No-go when:

- Any required CI workflow is missing, running, failed, cancelled, or for a different SHA.
- Production GitHub secrets/variables are incomplete or unapproved.
- Nginx/TLS/DNS/firewall are not ready.
- The VM worktree has tracked local changes.
- PostgreSQL backup fails, is empty, or cannot be retained securely.
- Alembic `upgrade head` fails.
- API health is not JSON `status=healthy`.
- Frontend verification fails.
- Rollback does not restore API health.
- Security, identity, data, or compliance owners do not approve launch.

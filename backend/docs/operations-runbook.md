# Operations Runbook

Run commands from the VM repository directory unless noted:

```bash
cd "$DEPLOY_PATH"
```

Use `DEPLOY_COMPOSE_FILE=docker-compose.yml` unless IT configured another file. Avoid `docker compose down` during incidents because it stops dependencies and can increase outage duration.

Status labels:

- **IMPLEMENTED**: supported by repository code/script.
- **VALIDATED**: checked by repository or workflow behavior.
- **REQUIRES IT / NOT YET VALIDATED**: requires production setup or operator verification.

## Common operations

| Operation | Command | Expected output |
| --- | --- | --- |
| Check all containers | `docker compose -f "$DEPLOY_COMPOSE_FILE" ps` | `api`, `postgres`, `redis`, `milvus`, `ollama`, `etcd`, and `minio` are running; `pgadmin` may be present if enabled. |
| API health | `curl --fail --silent --show-error "$DEPLOY_HEALTH_URL"` | JSON top-level `"status":"healthy"` for deploy go/no-go. |
| PostgreSQL readiness | `docker compose -f "$DEPLOY_COMPOSE_FILE" exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'` | Accepting connections. |
| Redis ping | `docker compose -f "$DEPLOY_COMPOSE_FILE" exec -T redis redis-cli ping` | `PONG`. |
| Milvus health | `curl --fail --silent --show-error http://127.0.0.1:9091/healthz` | HTTP success from Milvus health endpoint. |
| Ollama models | `docker compose -f "$DEPLOY_COMPOSE_FILE" exec -T ollama ollama list` | `llama3.2:3b` listed. |
| Ollama generation | `docker compose -f "$DEPLOY_COMPOSE_FILE" exec -T ollama ollama run llama3.2:3b "Reply with ok"` | Short generated response. |
| Nginx config test | `sudo nginx -t` | Syntax is ok and test is successful. |
| Nginx health | `curl --fail --silent --show-error https://<hostname>/healthz` | `ok`. |
| Frontend health | `curl --fail --silent --show-error "$DEPLOY_FRONTEND_HEALTH_URL" >/dev/null` | HTTP success. |
| API logs | `docker compose -f "$DEPLOY_COMPOSE_FILE" logs --tail=200 api` | No repeated tracebacks or dependency failures. |
| Failed ingestion logs | `docker compose -f "$DEPLOY_COMPOSE_FILE" logs --tail=500 api | grep -i ingestion` | Failed jobs or ingestion errors are visible for triage. |
| Deployment logs | GitHub Actions `Deploy VM` run log | CI gate, SSH, backup, migration, health, and frontend steps visible without secret values. |
| Disk usage | `df -h` | Root, `/data`, backup, and frontend release filesystems have safe free space. |
| Docker disk usage | `docker system df` | Image/build cache usage understood before cleanup. |
| Restart API only | `docker compose -f "$DEPLOY_COMPOSE_FILE" up -d --no-deps api` | Only `api` is recreated. Verify `/api/v1/health`. |
| Restart PostgreSQL | `docker compose -f "$DEPLOY_COMPOSE_FILE" restart postgres` | Requires maintenance approval and a recent backup. |
| Restart Redis | `docker compose -f "$DEPLOY_COMPOSE_FILE" restart redis` | Cache is rebuilt after restart. |
| Restart Milvus stack | `docker compose -f "$DEPLOY_COMPOSE_FILE" restart etcd minio milvus` | Requires maintenance approval; verify Milvus and API health. |
| Restart Ollama | `docker compose -f "$DEPLOY_COMPOSE_FILE" restart ollama` | Verify `ollama list` and test generation. |

Safe service restart order after full host maintenance:

1. `postgres`
2. `redis`
3. `etcd`
4. `minio`
5. `milvus`
6. `ollama`
7. `api`
8. Nginx reload

Verify after each dependency restart and again after API restart.

## Incident: API unavailable

Symptoms: frontend API calls fail, `/api/v1/health` unreachable, `api` container exited or restarting.

Diagnostics:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" ps api
docker compose -f "$DEPLOY_COMPOSE_FILE" logs --tail=200 api
curl --fail --silent --show-error "$DEPLOY_HEALTH_URL"
```

Expected output: `api` running and health JSON present. Logs should not show repeated startup exceptions.

Safe first response: restart API only with `docker compose -f "$DEPLOY_COMPOSE_FILE" up -d --no-deps api`, then verify health.

Escalate when: health remains unreachable, logs show migration/schema/config errors, or rollback health failed.

Do not casually run: `docker compose down`, database restore, Alembic downgrade, or broad volume cleanup.

## Incident: Degraded health

Symptoms: `/api/v1/health` returns JSON `status=degraded`.

Diagnostics:

```bash
curl --silent --show-error "$DEPLOY_HEALTH_URL"
docker compose -f "$DEPLOY_COMPOSE_FILE" ps
```

Expected output: component statuses identify PostgreSQL or Milvus mismatch/unhealthy state.

Safe first response: identify the degraded component and follow its incident section.

Escalate when: vector count differs from PostgreSQL chunks after ingestion, PostgreSQL is unavailable, or the platform is in production launch window.

Do not casually ignore degraded status for deployment; the deploy script requires `healthy`.

## Incident: PostgreSQL failure

Symptoms: API health PostgreSQL component `unhealthy`, signin/search/admin routes fail, `pg_isready` fails.

Diagnostics:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" ps postgres
docker compose -f "$DEPLOY_COMPOSE_FILE" logs --tail=200 postgres
docker compose -f "$DEPLOY_COMPOSE_FILE" exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
df -h
```

Expected output: PostgreSQL running, accepting connections, disk not full.

Safe first response: if disk is full, stop non-destructive writes and escalate storage cleanup. If PostgreSQL process is unhealthy, use an approved maintenance window and recent backup before restart.

Escalate when: data directory errors, corruption, repeated crashes, backup failure, or restore consideration.

Strong warning: do not delete PostgreSQL volumes, run `pg_resetwal`, restore over production, or run destructive SQL without a verified backup and formal approval.

## Incident: Redis failure

Symptoms: cache status unavailable, higher latency, logs mention Redis connection failures.

Diagnostics:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" ps redis
docker compose -f "$DEPLOY_COMPOSE_FILE" logs --tail=100 redis
docker compose -f "$DEPLOY_COMPOSE_FILE" exec -T redis redis-cli ping
```

Expected output: `PONG`.

Safe first response: restart Redis if approved. Redis is cache only and can be rebuilt.

Escalate when: Redis repeatedly crashes or resource limits are exhausted.

Do not casually flush shared production cache unless the incident commander accepts latency and cache-warmup impact.

## Incident: Milvus failure

Symptoms: `/api/v1/health` Milvus component `unhealthy`, vector search fails, chat falls back or errors after retrieval failure.

Diagnostics:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" ps etcd minio milvus
docker compose -f "$DEPLOY_COMPOSE_FILE" logs --tail=200 milvus
curl --fail --silent --show-error http://127.0.0.1:9091/healthz
```

Expected output: etcd, minio, and milvus running; health endpoint succeeds.

Safe first response: restart Milvus dependencies in order during an approved maintenance window: `etcd`, `minio`, `milvus`; then verify `/api/v1/health`.

Escalate when: collection missing, vector count mismatch, volume errors, or MinIO/etcd corruption is suspected.

Strong warning: do not drop the Milvus collection or delete `/data/milvus` without verified PostgreSQL/DOCX backups and an approved regeneration plan.

## Incident: Ollama failure

Symptoms: chat generation errors, `generation_provider` may fall back to `rule_based_fallback`, streaming fails, Ollama container unhealthy or model missing.

Diagnostics:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" ps ollama
docker compose -f "$DEPLOY_COMPOSE_FILE" logs --tail=200 ollama
docker compose -f "$DEPLOY_COMPOSE_FILE" exec -T ollama ollama list
```

Expected output: `llama3.2:3b` listed and Ollama accepts generation requests.

Safe first response: restart `ollama`; if model is missing, re-pull from approved source.

Escalate when: model cannot be loaded, host memory/GPU/CPU limits are exhausted, or generation latency blocks operations.

Do not casually change `OLLAMA_MODEL`, `OLLAMA_USE_FAST_MODEL`, or generation settings in production without benchmark evidence and rollback plan.

## Incident: Frontend unavailable

Symptoms: browser cannot load app, Nginx returns 404/500, assets missing, routes fail refresh.

Diagnostics:

```bash
readlink "$DEPLOY_FRONTEND_CURRENT_PATH"
ls -la "$DEPLOY_FRONTEND_CURRENT_PATH"
sudo nginx -t
curl --fail --silent --show-error "$DEPLOY_FRONTEND_HEALTH_URL" >/dev/null
```

Expected output: current path is a symlink to an existing release with `index.html`.

Safe first response: restore prior known-good symlink target if available, then reload Nginx.

Escalate when: TLS/Nginx config invalid, release folder missing, or all releases are broken.

Do not serve with `npm run dev` in production.

## Incident: Failed deployment

Symptoms: GitHub `Deploy VM` workflow failed.

Diagnostics: inspect the GitHub Actions log for failed phase: CI gate, SSH, Git checkout, Compose config, API build, frontend build, backup, Alembic, API health, frontend health, rollback.

Expected output: no secrets in logs; failure phase is explicit.

Safe first response: if script rollback succeeded, keep service on prior code and fix root cause before retrying exact SHA or a new SHA.

Escalate when: rollback health failed, database migration partially applied, or backup is missing.

Do not rerun blindly after migration failure without understanding database state.

## Incident: Failed migration

Symptoms: deployment aborts at `alembic upgrade head`, API not replaced if failure occurred before replacement.

Diagnostics:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" run --rm --no-deps api alembic -c alembic.ini current
docker compose -f "$DEPLOY_COMPOSE_FILE" run --rm --no-deps api alembic -c alembic.ini heads
ls -lh "$DEPLOY_BACKUP_DIR"
```

Expected output: current/head identify migration state; backup exists.

Safe first response: stop deployment attempts, preserve backup and logs, and involve application developer plus DBA/IT.

Strong warning: no automatic schema rollback exists. Do not run Alembic downgrade or restore production without a reviewed recovery decision.

## Incident: Failed document ingestion

Symptoms: admin upload returns failed job, ingestion job status `failed`, Milvus cleanup warnings.

Diagnostics:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" logs --tail=500 api | grep -i ingestion
curl --silent --show-error "$DEPLOY_HEALTH_URL"
```

Expected output: API health remains healthy or degraded with clear component cause.

Safe first response: review job details in admin UI, verify file type/size/content, and avoid re-uploading until failure cause is known.

Escalate when: Milvus cleanup failed, vector count mismatch, storage path missing, or repeated embedding failures occur.

Do not manually delete document/version/chunk rows without backup and application developer review.

## Incident: User cannot sign in

Symptoms: signin returns 401, user reports session expired, `/auth/me` fails.

Diagnostics: admin user list for active status, activation status, role, and recent password lifecycle events.

Expected output: user is `is_active=true`, `activation_status=active`, has role `admin` or `agent`.

Safe first response: use approved invitation resend, admin reset password, or enable user workflow.

Escalate when: many users fail simultaneously, JWT settings changed, or audit suggests unauthorized access.

Do not expose passwords, reset tokens, invitation URLs, JWTs, or token hashes in tickets.

## Incident: Invitation/reset delivery unavailable

Symptoms: invitation or reset action records `not_sent` or `failed`; users do not receive email.

Diagnostics: check `INVITATION_EMAIL_PROVIDER` and `PASSWORD_RESET_EMAIL_PROVIDER` in approved VM environment configuration without printing secrets.

Expected output: current repository supports only `noop` and `capture`; no production email sender is implemented.

Safe first response: record accepted risk or block launch until IT approves and implements real provider delivery.

Escalate when: production requires self-service invitation/reset email.

Do not enable URL exposure in production as a substitute for real email delivery.

## Incident: Storage full

Symptoms: PostgreSQL errors, backup failure, Docker build failure, frontend release failure, Nginx 500, or `df -h` shows full filesystem.

Diagnostics:

```bash
df -h
du -sh "$DEPLOY_BACKUP_DIR" "$DEPLOY_FRONTEND_RELEASES_PATH" /data/* 2>/dev/null
docker system df
```

Expected output: identify largest consumers without deleting data.

Safe first response: stop deployment attempts, preserve database and uploaded DOCX files, and have IT expand storage or archive old approved backups/releases.

Strong warning: do not delete Docker volumes, PostgreSQL data, Milvus data, DOCX uploads, or recent backups casually. Prune Docker build cache only when IT confirms it is not needed for rollback/build diagnostics.

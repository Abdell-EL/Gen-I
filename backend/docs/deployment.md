# VM deployment workflow

Phase 7 adds a controlled deployment path for the existing single Ubuntu VM running Docker Compose. It does not introduce Kubernetes, Terraform, a container registry, or cloud infrastructure.

## Current architecture

Deployments are started manually from GitHub Actions through `.github/workflows/deploy-vm.yml`. The workflow deploys the exact commit SHA selected in GitHub Actions and refuses to continue unless the required CI workflows already succeeded for that same SHA:

- `quality.yml`;
- `security.yml`;
- `postgres-integration.yml`.

The workflow connects to the VM over SSH, copies `scripts/deploy_vm.sh` to `/tmp`, and runs it on the VM. The VM keeps the repository checked out at `DEPLOY_PATH`, builds from the exact commit SHA, validates Docker Compose, builds the API image, prepares the frontend static release, backs up PostgreSQL, runs Alembic migrations from the new API image, recreates only the `api` service, then validates API and frontend health.

## Required GitHub configuration

Create a `production` GitHub Environment and store deployment secrets there when possible. Enable production environment approval in GitHub before first live use.

Required secrets:

- `DEPLOY_HOST`: VM hostname or IP address;
- `DEPLOY_USER`: SSH user on the VM;
- `DEPLOY_SSH_PRIVATE_KEY`: private key for the deployment user;
- `DEPLOY_KNOWN_HOSTS`: verified SSH known-hosts entry for the VM.

Optional secret:

- `DEPLOY_PORT`: SSH port; defaults to `22`.

Required environment variables for a complete production deployment:

- `DEPLOY_FRONTEND_RELEASES_PATH`: directory where immutable frontend releases are stored, for example `/var/www/lab-ia-genius/releases`;
- `DEPLOY_FRONTEND_CURRENT_PATH`: symlink served by the production web server, for example `/var/www/lab-ia-genius/current`;
- `DEPLOY_FRONTEND_HEALTH_URL`: public or VM-local URL used to verify the frontend after switching the symlink;
- `VITE_API_BASE_URL`: production API base URL compiled into the Vite app, for example `https://example.internal/api/v1`;
- `VITE_AUTH_MODE`: must be `backend`.

Optional environment variables:

- `DEPLOY_PATH`: repository path on the VM; defaults to `/opt/lab-ia-genius`;
- `DEPLOY_COMPOSE_FILE`: compose file relative to `DEPLOY_PATH`; defaults to `docker-compose.yml`;
- `DEPLOY_DB_SERVICE`: PostgreSQL compose service name; defaults to `postgres`;
- `DEPLOY_BACKUP_DIR`: PostgreSQL backup directory; defaults to `$DEPLOY_PATH/backups/postgres`;
- `DEPLOY_HEALTH_URL`: API health URL checked from the VM; defaults to `http://127.0.0.1:8000/api/v1/health`;
- `DEPLOY_HEALTH_TIMEOUT_SECONDS`: API health timeout; defaults to `120`;
- `DEPLOY_FRONTEND_HEALTH_TIMEOUT_SECONDS`: frontend verification timeout; defaults to `60`.

Do not put access tokens in URLs. Do not disable SSH host-key checking. Generate `DEPLOY_KNOWN_HOSTS` from a trusted workstation and verify the fingerprint before storing it.

## VM prerequisites

The VM must already have:

- Ubuntu with Docker Engine and Docker Compose v2;
- `git`, `curl`, `python3`, `npm`, and `bash`;
- a checked-out repository at `DEPLOY_PATH`;
- a valid `.env` file on the VM;
- persistent data mounts used by `docker-compose.yml`;
- a PostgreSQL container with `pg_dump` available through the compose `postgres` service;
- access from the VM to any package registries needed for `docker compose build` and `npm ci`;
- a production web server that serves `DEPLOY_FRONTEND_CURRENT_PATH`;
- a deployment SSH user that can run Docker commands and update the configured frontend release directories.

The deployment user should have the least privileges practical for this VM. Prefer membership in the Docker group only when that matches the host security model.

## Frontend production serving

Repository audit found no tracked production frontend service, Nginx/Caddy config, frontend Dockerfile, or static web-server compose service. The only documented frontend runtime command is Vite development mode (`npm run dev`), which must not be used for production.

Therefore production deployment is blocked until the VM has an existing production static file server. The smallest suitable design for this single VM is:

1. Install and configure Nginx or reuse an already approved production web server.
2. Configure the server root to the symlink in `DEPLOY_FRONTEND_CURRENT_PATH`, for example `/var/www/lab-ia-genius/current`.
3. Route SPA paths to `index.html`.
4. Proxy `/api/` to the existing local API listener when the public frontend and API share one origin, or set `VITE_API_BASE_URL` to the existing API origin when they do not.
5. Let the deploy script run `npm ci`, `npm run build`, create an immutable release directory, atomically switch the `current` symlink, and verify `DEPLOY_FRONTEND_HEALTH_URL`.

The script intentionally fails if the frontend release paths or verification URL are missing. This prevents backend-only deployments from being mistaken for complete product deployments.

## Deployment flow

1. CI runs for a commit.
2. An operator opens the `Deploy VM` workflow in GitHub Actions.
3. The operator selects the deployable ref and enters `DEPLOY`.
4. The workflow verifies that Quality, Security, and PostgreSQL Integration succeeded for that exact commit SHA.
5. The workflow configures SSH using GitHub secrets and strict host-key checking.
6. The workflow copies `scripts/deploy_vm.sh` to the VM.
7. The VM script refuses to deploy if tracked local changes exist.
8. The VM script fetches the target commit and checks it out detached.
9. Docker Compose config is validated.
10. The new API image is built while the existing API container continues running.
11. Frontend dependencies are installed with `npm ci`, and static assets are built from the same Git SHA.
12. A timestamped PostgreSQL backup is created with `pg_dump` through the PostgreSQL compose service.
13. The backup file is verified as non-empty.
14. Current and target Alembic revisions are printed without database credentials.
15. `alembic upgrade head` runs from the new API image before API replacement.
16. If backup or migration fails, deployment aborts before replacing the running API container.
17. Only the `api` service is recreated with `docker compose up -d --no-deps api`.
18. The script checks `DEPLOY_HEALTH_URL` until JSON `status` is exactly `healthy` or the timeout expires.
19. If API health succeeds, the frontend `current` symlink is switched atomically.
20. The frontend is verified through `DEPLOY_FRONTEND_HEALTH_URL`.
21. If both checks succeed, the deployment is complete.

## Database migrations

Production deployments run forward-only Alembic migrations with:

```bash
alembic -c alembic.ini upgrade head
```

The command runs inside a one-off container based on the newly built API image. It uses the existing compose environment and does not restart PostgreSQL, Redis, Milvus, Ollama, MinIO, or etcd.

All production migrations must be backward-compatible and forward-only. The old API may briefly run against the migrated schema during deployment, and rollback restores application code only. Do not merge a production migration unless the previous deployed API can tolerate the upgraded schema for the duration of rollback.

Automatic Alembic downgrade is intentionally not implemented. Schema downgrade requires a separate, human-reviewed database recovery decision.

## Backup behavior

Before any live migration, the deployment script writes a timestamped custom-format PostgreSQL backup under `DEPLOY_BACKUP_DIR`, defaulting to:

```text
/opt/lab-ia-genius/backups/postgres
```

Backups are created through the PostgreSQL compose service using environment variables already present inside the container. Database credentials are not echoed into logs or passed in command-line URLs.

The deployment aborts before migration if the backup command fails or if the backup file is empty.

Recommended retention policy:

- keep all backups from the last 7 days;
- keep at least one weekly backup for the last 4 weeks;
- move older backups to encrypted offline storage before deletion;
- never delete recent backups automatically from the deployment script.

## Downtime behavior

The current single-VM Compose topology exposes one API container on a fixed local port, so full blue/green zero-downtime deployment is not available without introducing a local reverse proxy or a second service binding. The workflow minimizes downtime by building the new image before recreating the API container and by leaving PostgreSQL, Redis, Milvus, MinIO, etcd, and Ollama running.

Frontend switching is an atomic symlink update when the production web server is configured to serve `DEPLOY_FRONTEND_CURRENT_PATH`.

## Rollback behavior

Rollback is automatic only for failed deployment verification. The script records the previous git commit before checkout. If API health fails, the script restores the previous commit and recreates the API service from that version. If frontend verification fails, the script restores the previous frontend symlink and rolls API code back.

Checking out the prior commit does not roll back the database schema. The PostgreSQL backup exists for manual recovery, but the deployment script does not run Alembic downgrade or restore the database automatically.

If rollback health also fails, the workflow exits failed and manual VM intervention is required.

Manual application-code rollback can reuse the same script from the VM by setting `DEPLOY_REF` to a known-good commit:

```bash
cd /opt/lab-ia-genius
DEPLOY_REF=<known-good-sha> \
DEPLOY_FRONTEND_RELEASES_PATH=/var/www/lab-ia-genius/releases \
DEPLOY_FRONTEND_CURRENT_PATH=/var/www/lab-ia-genius/current \
DEPLOY_FRONTEND_HEALTH_URL=https://example.internal/ \
VITE_API_BASE_URL=https://example.internal/api/v1 \
VITE_AUTH_MODE=backend \
scripts/deploy_vm.sh
```

## Health checks

The default API health check is:

```text
http://127.0.0.1:8000/api/v1/health
```

The API response must be JSON with `status` exactly equal to `healthy`. HTTP 200 alone is not enough. If the application is intentionally running in a degraded state, fix the underlying dependency or update the deployment policy explicitly before deploying.

Frontend verification uses `DEPLOY_FRONTEND_HEALTH_URL` and currently requires an HTTP success response.

## CI gate

The deployment workflow uses `.github/scripts/verify_deploy_ci.py` and the built-in `GITHUB_TOKEN` with `actions: read` permission. It checks the latest run for each required workflow file on the target SHA. Missing, running, failed, or cancelled required workflows block deployment.

This means deployment from a branch or SHA where Security or PostgreSQL Integration did not run will fail safely. Run the missing workflow for that ref before deploying.

## Not included

This phase intentionally does not add:

- Kubernetes;
- Terraform;
- container registry publishing;
- cloud infrastructure;
- database restore automation;
- automatic Alembic downgrade;
- Nginx installation or web-server management;
- blue/green proxy routing.

Those can be added later if the single-VM Compose model becomes insufficient.

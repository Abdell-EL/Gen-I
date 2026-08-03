# GitHub Production Environment

Create a GitHub Environment named `production` for `.github/workflows/deploy-vm.yml`. Configure required reviewers/approval before first live use. Do not store real values in Git.

Status labels:

- **IMPLEMENTED**: expected by the workflow or script.
- **VALIDATED**: checked by the workflow or script.
- **REQUIRES IT / NOT YET VALIDATED**: must be supplied and approved by IT/security.

## Required secrets

| Name | Purpose | Secret? | Example placeholder | Expected format | Validation rule | Provider | IT approval |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `DEPLOY_HOST` | SSH host for the VM. | Secret | `<vm-hostname-or-ip>` | Hostname, IPv4, IPv6, or internal DNS name. | Workflow rejects empty values and unsupported characters outside `a-zA-Z0-9._:-`. | IT/deployment team | Required |
| `DEPLOY_USER` | SSH user used to run deployment on the VM. | Secret | `<deploy-user>` | Linux username with letters, numbers, dot, underscore, or hyphen. | Workflow rejects empty values and unsupported characters outside `a-zA-Z0-9._-`. | IT/deployment team | Required |
| `DEPLOY_SSH_PRIVATE_KEY` | Private key for the deployment user. | Secret | `<openssh-private-key>` | PEM/OpenSSH private key text. | Workflow checks only non-empty; security team must validate scope and storage. | IT/deployment team/security team | Required |
| `DEPLOY_KNOWN_HOSTS` | Verified SSH host-key entry for strict host checking. | Secret | `<hostname> ssh-ed25519 <public-key>` | Exact `known_hosts` line generated and verified from a trusted workstation. | Workflow checks only non-empty; SSH enforces strict host-key checking. | IT/deployment team/security team | Required |

## Optional secret

| Name | Purpose | Secret? | Example placeholder | Expected format | Validation rule | Provider | IT approval |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `DEPLOY_PORT` | SSH port. Defaults to `22` when omitted. | Secret | `<ssh-port>` | Numeric TCP port. | Workflow rejects empty non-default use and any non-numeric value. | IT/deployment team | Required if non-default |

## Variables

| Name | Purpose | Secret? | Example placeholder | Expected format | Validation rule | Provider | IT approval |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `DEPLOY_PATH` | Repository worktree path on the VM. Defaults to `/opt/lab-ia-genius`. | Non-secret | `/opt/lab-ia-genius` | Absolute Linux path. | Script requires it to be a Git worktree. | IT/deployment team | Required |
| `DEPLOY_COMPOSE_FILE` | Compose file relative to `DEPLOY_PATH`. Defaults to `docker-compose.yml`. | Non-secret | `docker-compose.yml` | Relative file path. | Script requires the file to exist and pass `docker compose config --quiet`. | IT/deployment team/application developer | Required |
| `DEPLOY_DB_SERVICE` | Compose service that runs PostgreSQL. Defaults to `postgres`. | Non-secret | `postgres` | Compose service name. | Backup command must run `pg_dump` through this service. | Application developer/IT deployment team | Required |
| `DEPLOY_BACKUP_DIR` | Directory for pre-deploy PostgreSQL backups. Defaults to `$DEPLOY_PATH/backups/postgres`. | Non-secret | `/opt/lab-ia-genius/backups/postgres` | Absolute Linux path. | Script creates it, applies mode `700`, and verifies backup file is non-empty. | IT/deployment team | Required |
| `DEPLOY_HEALTH_URL` | VM-local API health URL. Defaults to `http://127.0.0.1:8000/api/v1/health`. | Non-secret | `http://127.0.0.1:8000/api/v1/health` | HTTP(S) URL reachable from VM. | Script requires returned JSON top-level `status` exactly `healthy`. | IT/deployment team/application developer | Required |
| `DEPLOY_HEALTH_TIMEOUT_SECONDS` | API health wait timeout. Defaults to `120`. | Non-secret | `120` | Positive integer seconds. | Script uses shell arithmetic; choose numeric value. | IT/deployment team | Required |
| `DEPLOY_FRONTEND_RELEASES_PATH` | Directory for immutable frontend release folders. | Non-secret | `/var/www/lab-ia-genius/releases` | Absolute Linux path. | Script fails if empty and must be able to create/write releases. | IT/deployment team | Required |
| `DEPLOY_FRONTEND_CURRENT_PATH` | Symlink served by the production web server. | Non-secret | `/var/www/lab-ia-genius/current` | Absolute Linux symlink path. | Script fails if empty or if existing path is not a symlink. | IT/deployment team | Required |
| `DEPLOY_FRONTEND_HEALTH_URL` | Frontend URL checked after symlink switch. | Non-secret | `https://<app-hostname>/` | HTTP(S) URL reachable from VM. | Script requires HTTP success within timeout. | IT/deployment team | Required |
| `DEPLOY_FRONTEND_HEALTH_TIMEOUT_SECONDS` | Frontend health wait timeout. Defaults to `60`. | Non-secret | `60` | Positive integer seconds. | Script uses shell arithmetic; choose numeric value. | IT/deployment team | Required |
| `VITE_API_BASE_URL` | API base URL compiled into frontend static assets. | Non-secret | `https://<app-hostname>/api/v1` | Public browser-reachable API base URL, no trailing slash required. | Script fails if empty. Frontend trims trailing slashes. | IT/deployment team/application developer | Required |
| `VITE_AUTH_MODE` | Frontend auth mode for production. | Non-secret | `backend` | Exact string `backend`. | Script fails unless value is `backend`. | Application developer/IT deployment team | Required |

## Recommendations

- Require approval on the GitHub `production` environment.
- Restrict deployment to an approved branch or protected release process.
- Use least privilege for the SSH deploy user.
- Do not use shared personal credentials.
- Rotate `DEPLOY_SSH_PRIVATE_KEY` on a defined schedule and immediately after personnel or access changes.
- Generate `DEPLOY_KNOWN_HOSTS` from a trusted workstation and verify the fingerprint out of band.
- Keep `DEPLOY_HOST`, `DEPLOY_USER`, keys, and host keys in secrets, not variables.
- Do not place access tokens, database URLs with credentials, TLS keys, or private host details in repository docs or logs.

# Backup and Restore Runbook

This runbook describes recovery procedures only. Do not execute a restore against production without IT approval, an incident commander, and a verified backup target.

Status labels:

- **IMPLEMENTED**: supported by repository code/script.
- **VALIDATED**: checked by repository or deployment script behavior.
- **REQUIRES IT / NOT YET VALIDATED**: needs production approval, infrastructure setup, or restore rehearsal.

## Source-of-truth summary

| Data | Status | Source of truth |
| --- | --- | --- |
| Users, auth lifecycle, document metadata, chunks, audits, analytics, feedback | IMPLEMENTED | PostgreSQL |
| Original uploaded DOCX files | IMPLEMENTED | `KB_UPLOAD_ROOT`, default `data/uploads/kb_articles`, mounted from `./backend/data:/app/data` in root Compose |
| Milvus vectors | IMPLEMENTED | Derived from document/chunk inputs and embedding model; can be backed up directly or regenerated |
| Redis cache | IMPLEMENTED | Not source of truth; rebuildable |
| Ollama models | IMPLEMENTED | Local model files in `/data/ollama`; reinstall/re-pull may be required |
| Frontend static releases | IMPLEMENTED | `DEPLOY_FRONTEND_RELEASES_PATH` and `DEPLOY_FRONTEND_CURRENT_PATH` symlink |
| Environment/deployment config | REQUIRES IT / NOT YET VALIDATED | VM `.env`, GitHub environment secrets/variables, Nginx config, TLS material, firewall/DNS records |

## PostgreSQL backup

Manual backup command on the VM:

```bash
cd "$DEPLOY_PATH"
mkdir -p "$DEPLOY_BACKUP_DIR"
chmod 700 "$DEPLOY_BACKUP_DIR"
backup_file="$DEPLOY_BACKUP_DIR/$(date -u +%Y%m%dT%H%M%SZ)_manual.dump"
docker compose -f "$DEPLOY_COMPOSE_FILE" exec -T "$DEPLOY_DB_SERVICE" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' >"$backup_file"
chmod 600 "$backup_file"
test -s "$backup_file"
sha256sum "$backup_file" >"$backup_file.sha256"
```

Automated pre-deploy backup is **IMPLEMENTED** in `scripts/deploy_vm.sh`. It writes a timestamped custom-format dump under `DEPLOY_BACKUP_DIR`, applies restrictive permissions, and aborts before migration if backup creation fails or the file is empty.

Backup permissions:

- Directory: mode `700`, owned by the deployment/backup operator.
- Dump files: mode `600`.
- Off-VM copies: encrypted storage with restricted access.
- Do not print database credentials in commands or logs.

Retention recommendation:

- Keep every backup from the last 7 days.
- Keep at least one weekly backup for the last 4 weeks.
- Move older backups to encrypted offline or managed backup storage before deletion.
- Do not automate deletion in the deployment script.

Verification:

- Confirm non-empty file with `test -s "$backup_file"`.
- Record checksum with `sha256sum`.
- Compare expected size with prior comparable backups; a sharp drop requires investigation.
- A backup is not verified until it has been restored successfully.

## PostgreSQL restore procedure

Restore into a disposable database first. Do not overwrite production as the first restore attempt.

1. Provision an isolated PostgreSQL instance or database with no production traffic.
2. Copy the selected backup and `.sha256` file to the restore host.
3. Verify checksum:

```bash
sha256sum -c "<backup-file>.sha256"
```

4. Create a disposable restore database.
5. Restore with `pg_restore`:

```bash
pg_restore --clean --if-exists --no-owner --no-acl --dbname "<disposable-postgres-url>" "<backup-file>"
```

6. Verify Alembic state:

```bash
cd backend
DATABASE_URL="<disposable-postgres-url>" alembic -c alembic.ini current
DATABASE_URL="<disposable-postgres-url>" alembic -c alembic.ini heads
```

7. Compare restored Alembic current with repository head for the application version being recovered.
8. Run smoke queries against restored data:

```sql
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM source_documents;
SELECT COUNT(*) FROM document_versions;
SELECT COUNT(*) FROM chunks;
SELECT COUNT(*) FROM embeddings;
SELECT COUNT(*) FROM audit_logs;
SELECT COUNT(*) FROM retrieval_requests;
```

9. Validate user/document/audit checks in the disposable environment:

- At least one approved admin user exists.
- Active users have expected `activation_status`.
- Source documents and current document versions exist.
- Chunk and embedding metadata counts are plausible.
- Audit/retrieval history exists if expected for the recovery point.
- No raw reset, invitation, JWT, or password values are exposed.

10. Only after disposable restore success, follow IT's approved production restore/change process.

## Document files

Back up outside Git:

- Original uploaded DOCX files under `KB_UPLOAD_ROOT`.
- Versioned upload directories under `KB_UPLOAD_ROOT/<document_id>/<version_id>/`.
- Root Compose persistent mount `./backend/data:/app/data` or its production equivalent.
- Any seeded `backend/data/KB_Articles` files if production depends on them.
- `backend/data/processed` only if IT chooses to retain generated ingestion artifacts.

Risk: PostgreSQL may reference `DocumentVersion.storage_path` files. Restoring PostgreSQL without corresponding DOCX storage can leave original download and rebuild workflows incomplete.

## Frontend releases and deployment config

Back up outside Git:

- `DEPLOY_FRONTEND_RELEASES_PATH`.
- `DEPLOY_FRONTEND_CURRENT_PATH` symlink target.
- Production Nginx config derived from `deployment/nginx/lab-ia-genius.conf.template`.
- VM `.env` file.
- TLS certificate/key material through IT's certificate management process.
- GitHub Environment secrets/variables through IT/security procedures.
- Firewall, DNS, and hostname records.

## Milvus strategy

IT must choose and rehearse one of these strategies.

### Strategy A: Direct Milvus backup

Status: **REQUIRES IT / NOT YET VALIDATED**.

Back up Milvus persistent volumes and dependencies consistently:

- `/data/milvus/milvus`
- `/data/milvus/etcd`
- `/data/milvus/minio`

Risk: Direct volume backup consistency depends on Milvus/etcd/MinIO state and snapshot timing. Restore must preserve compatibility with the Milvus image version in `docker-compose.yml`.

Recovery outline:

1. Stop writes to ingestion/versioning.
2. Take an IT-approved consistent snapshot of Milvus, etcd, and MinIO volumes.
3. Restore volumes to a disposable environment first.
4. Start `etcd`, `minio`, then `milvus`.
5. Verify `curl --fail http://127.0.0.1:9091/healthz` on the VM or equivalent Milvus health endpoint.
6. Verify application `/api/v1/health` reports Milvus healthy and vector count matches PostgreSQL chunks.

### Strategy B: Regenerate Milvus

Status: **IMPLEMENTED** for insertion flows, **REQUIRES IT / NOT YET VALIDATED** for full production recovery rehearsal.

Milvus vectors are derived from PostgreSQL chunk/document metadata, original DOCX inputs, and the embedding model `BAAI/bge-m3`. Regeneration is acceptable if IT accepts longer recovery time and validates vector parity.

Recovery outline:

1. Restore PostgreSQL and DOCX storage first.
2. Ensure `BAAI/bge-m3` model/cache is available under `/data/huggingface` or can be downloaded from an approved source.
3. Recreate Milvus service/collection.
4. Reinsert vectors from restored chunks using an approved recovery script or validated ingestion rebuild process.
5. Verify Milvus entity count equals PostgreSQL `chunks` count.
6. Verify `/api/v1/health` returns `status=healthy`.
7. Run search/chat/source smoke tests.

Risk: If embedding model version/cache changes, retrieved rankings can change. Record model files and image versions during backup.

## Redis

Redis is a cache and is not the source of truth. After recovery, Redis may start empty. Do not block recovery solely on cache contents. Validate that API requests succeed and cache status is acceptable after warm traffic.

## Ollama

Ollama model files live in the VM Ollama volume, `/data/ollama` in root Compose. After host rebuild or data loss, IT must reinstall/re-pull required models from an approved source:

```bash
docker compose -f "$DEPLOY_COMPOSE_FILE" exec ollama ollama list
docker compose -f "$DEPLOY_COMPOSE_FILE" exec ollama ollama pull llama3.2:3b
```

The fast model `llama3.2:1b` is configured but disabled by default; pull it only if IT needs the optional profile.

## Recovery order

1. Infrastructure, storage, DNS/TLS/firewall, and VM access.
2. Git checkout and repository version.
3. Environment configuration and Compose validation.
4. PostgreSQL restore.
5. DOCX upload storage restore.
6. Milvus direct restore or regeneration.
7. Redis start.
8. Ollama model availability.
9. API start/replacement.
10. Frontend release or rebuild and symlink switch.
11. Nginx reload.
12. Health, signin, search/chat, source download, admin analytics, logs, and monitoring validation.

## Recovery time assumptions

| Scenario | Status | Assumption |
| --- | --- | --- |
| PostgreSQL restore only | REQUIRES IT / NOT YET VALIDATED | Depends on dump size, VM disk, and PostgreSQL performance. |
| Milvus direct volume restore | REQUIRES IT / NOT YET VALIDATED | Faster if snapshots are consistent and compatible. |
| Milvus regeneration | REQUIRES IT / NOT YET VALIDATED | Slower; depends on embedding model availability and document/chunk volume. |
| Ollama model re-pull | REQUIRES IT / NOT YET VALIDATED | Depends on network/model registry access and model size. |

## Validation checklist

- Backup checksum validates.
- Disposable PostgreSQL restore succeeds.
- Alembic current/head are understood for the recovered app version.
- Required tables have plausible row counts.
- DOCX files referenced by `document_versions.storage_path` exist.
- Milvus collection exists and vector count matches expected chunk count.
- Redis responds to ping or cache is intentionally disabled.
- Ollama lists `llama3.2:3b` and can generate a short response.
- API `/api/v1/health` returns JSON `status=healthy`.
- Frontend loads through HTTPS.
- Signin, agent question, source download, admin analytics, and document ingestion behavior are verified in the recovered environment.

Warning: a backup is not verified until it has been restored successfully.

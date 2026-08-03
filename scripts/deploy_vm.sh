#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/opt/lab-ia-genius}"
DEPLOY_REF="${DEPLOY_REF:?DEPLOY_REF is required}"
DEPLOY_COMPOSE_FILE="${DEPLOY_COMPOSE_FILE:-docker-compose.yml}"
DEPLOY_SERVICE="${DEPLOY_SERVICE:-api}"
DEPLOY_DB_SERVICE="${DEPLOY_DB_SERVICE:-postgres}"
DEPLOY_BACKUP_DIR="${DEPLOY_BACKUP_DIR:-$DEPLOY_PATH/backups/postgres}"
DEPLOY_HEALTH_URL="${DEPLOY_HEALTH_URL:-http://127.0.0.1:8000/api/v1/health}"
DEPLOY_HEALTH_TIMEOUT_SECONDS="${DEPLOY_HEALTH_TIMEOUT_SECONDS:-120}"
DEPLOY_FRONTEND_RELEASES_PATH="${DEPLOY_FRONTEND_RELEASES_PATH:-}"
DEPLOY_FRONTEND_CURRENT_PATH="${DEPLOY_FRONTEND_CURRENT_PATH:-}"
DEPLOY_FRONTEND_HEALTH_URL="${DEPLOY_FRONTEND_HEALTH_URL:-}"
DEPLOY_FRONTEND_HEALTH_TIMEOUT_SECONDS="${DEPLOY_FRONTEND_HEALTH_TIMEOUT_SECONDS:-60}"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-}"
VITE_AUTH_MODE="${VITE_AUTH_MODE:-backend}"

api_replaced=0
frontend_switched=0
previous_ref=""
previous_frontend_target=""
frontend_release_path=""
health_file=""

log() {
  printf '[deploy] %s\n' "$*"
}

restore_checkout_before_replacement() {
  if [[ "$api_replaced" == "0" && -n "$previous_ref" ]]; then
    log "restoring previous checkout because deployment failed before API replacement"
    git checkout --detach "$previous_ref" >/dev/null 2>&1 || true
  fi
}

fail() {
  printf '[deploy] %s\n' "$*" >&2
  restore_checkout_before_replacement
  exit 1
}

cleanup() {
  if [[ -n "$health_file" ]]; then
    rm -f "$health_file"
  fi
}

on_error() {
  restore_checkout_before_replacement
}

trap cleanup EXIT
trap on_error ERR

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "required command missing on VM: $1"
  fi
}

wait_for_api_health() {
  local deadline status
  health_file="$(mktemp)"
  deadline=$((SECONDS + DEPLOY_HEALTH_TIMEOUT_SECONDS))

  while (( SECONDS < deadline )); do
    if curl --fail --silent --show-error --max-time 5 "$DEPLOY_HEALTH_URL" >"$health_file"; then
      status="$(python3 - "$health_file" <<'PYCHECK'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
print(str(payload.get("status", "")).lower())
PYCHECK
)"
      if [[ "$status" == "healthy" ]]; then
        return 0
      fi
      log "API health endpoint returned status '$status'; waiting"
    fi
    sleep 5
  done

  return 1
}

wait_for_frontend_health() {
  local deadline
  deadline=$((SECONDS + DEPLOY_FRONTEND_HEALTH_TIMEOUT_SECONDS))

  while (( SECONDS < deadline )); do
    if curl --fail --silent --show-error --max-time 5 "$DEPLOY_FRONTEND_HEALTH_URL" >/dev/null; then
      return 0
    fi
    sleep 5
  done

  return 1
}

run_api_command() {
  docker compose -f "$DEPLOY_COMPOSE_FILE" run --rm --no-deps "$DEPLOY_SERVICE" "$@"
}

validate_frontend_config() {
  [[ -n "$DEPLOY_FRONTEND_RELEASES_PATH" ]] || fail "DEPLOY_FRONTEND_RELEASES_PATH is required for production frontend deployment"
  [[ -n "$DEPLOY_FRONTEND_CURRENT_PATH" ]] || fail "DEPLOY_FRONTEND_CURRENT_PATH is required for production frontend deployment"
  [[ -n "$DEPLOY_FRONTEND_HEALTH_URL" ]] || fail "DEPLOY_FRONTEND_HEALTH_URL is required for frontend verification"
  [[ -n "$VITE_API_BASE_URL" ]] || fail "VITE_API_BASE_URL is required for the production frontend build"
  [[ "$VITE_AUTH_MODE" == "backend" ]] || fail "VITE_AUTH_MODE must be backend for production deployment"
}

backup_postgres() {
  local timestamp backup_file
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$DEPLOY_BACKUP_DIR"
  chmod 700 "$DEPLOY_BACKUP_DIR"
  backup_file="$DEPLOY_BACKUP_DIR/${timestamp}_${DEPLOY_REF:0:12}.dump"

  log "creating PostgreSQL backup at $backup_file"
  if ! docker compose -f "$DEPLOY_COMPOSE_FILE" exec -T "$DEPLOY_DB_SERVICE" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' >"$backup_file"; then
    rm -f "$backup_file"
    fail "PostgreSQL backup failed; aborting before migration and API replacement"
  fi
  chmod 600 "$backup_file"

  if [[ ! -s "$backup_file" ]]; then
    rm -f "$backup_file"
    fail "PostgreSQL backup was empty; aborting before migration and API replacement"
  fi

  log "PostgreSQL backup verified as non-empty"
}

build_frontend_release() {
  local release_id release_tmp current_parent
  release_id="$(date -u +%Y%m%dT%H%M%SZ)-${DEPLOY_REF:0:12}"
  frontend_release_path="$DEPLOY_FRONTEND_RELEASES_PATH/$release_id"
  release_tmp="$frontend_release_path.tmp"
  current_parent="$(dirname "$DEPLOY_FRONTEND_CURRENT_PATH")"

  if [[ -e "$DEPLOY_FRONTEND_CURRENT_PATH" && ! -L "$DEPLOY_FRONTEND_CURRENT_PATH" ]]; then
    fail "DEPLOY_FRONTEND_CURRENT_PATH exists but is not a symlink: $DEPLOY_FRONTEND_CURRENT_PATH"
  fi

  mkdir -p "$DEPLOY_FRONTEND_RELEASES_PATH" "$current_parent"
  previous_frontend_target="$(readlink "$DEPLOY_FRONTEND_CURRENT_PATH" 2>/dev/null || true)"

  log "building frontend static assets for $DEPLOY_REF"
  (
    cd backend/frontend
    npm ci
    VITE_API_BASE_URL="$VITE_API_BASE_URL" VITE_AUTH_MODE="$VITE_AUTH_MODE" npm run build
  )

  rm -rf "$release_tmp"
  mkdir -p "$release_tmp"
  cp -a backend/frontend/dist/. "$release_tmp/"
  mv "$release_tmp" "$frontend_release_path"
  log "frontend release prepared at $frontend_release_path"
}

switch_frontend_release() {
  local next_link
  next_link="$DEPLOY_FRONTEND_CURRENT_PATH.next"
  ln -sfn "$frontend_release_path" "$next_link"
  mv -Tf "$next_link" "$DEPLOY_FRONTEND_CURRENT_PATH"
  frontend_switched=1
}

restore_frontend_release() {
  if [[ "$frontend_switched" != "1" ]]; then
    return 0
  fi

  if [[ -n "$previous_frontend_target" ]]; then
    log "restoring previous frontend release"
    ln -sfn "$previous_frontend_target" "$DEPLOY_FRONTEND_CURRENT_PATH.next"
    mv -Tf "$DEPLOY_FRONTEND_CURRENT_PATH.next" "$DEPLOY_FRONTEND_CURRENT_PATH"
  else
    log "removing frontend current symlink created by failed deployment"
    rm -f "$DEPLOY_FRONTEND_CURRENT_PATH"
  fi
}

rollback_api_code() {
  if [[ -z "$previous_ref" ]]; then
    return 0
  fi

  log "rolling API code back to $previous_ref"
  git checkout --detach "$previous_ref"
  docker compose -f "$DEPLOY_COMPOSE_FILE" config --quiet
  docker compose -f "$DEPLOY_COMPOSE_FILE" build "$DEPLOY_SERVICE"
  docker compose -f "$DEPLOY_COMPOSE_FILE" up -d --no-deps "$DEPLOY_SERVICE"
}

require_command git
require_command docker
require_command curl
require_command python3
require_command npm

if ! docker compose version >/dev/null 2>&1; then
  fail "Docker Compose v2 is required on the VM"
fi

cd "$DEPLOY_PATH"

git config --global --add safe.directory "$DEPLOY_PATH" >/dev/null 2>&1 || true

if [[ ! -d .git ]]; then
  fail "DEPLOY_PATH is not a git worktree: $DEPLOY_PATH"
fi

if [[ ! -f "$DEPLOY_COMPOSE_FILE" ]]; then
  fail "compose file not found: $DEPLOY_PATH/$DEPLOY_COMPOSE_FILE"
fi

validate_frontend_config

if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "tracked local changes exist on the VM; refusing to overwrite them"
fi

previous_ref="$(git rev-parse HEAD)"
log "previous ref: $previous_ref"
log "target ref: $DEPLOY_REF"

log "fetching target commit"
git fetch --prune origin
git cat-file -e "${DEPLOY_REF}^{commit}"

log "checking out target commit"
git checkout --detach "$DEPLOY_REF"

log "validating compose config"
docker compose -f "$DEPLOY_COMPOSE_FILE" config --quiet

log "building service while current container stays online"
docker compose -f "$DEPLOY_COMPOSE_FILE" build "$DEPLOY_SERVICE"

build_frontend_release

backup_postgres

log "current Alembic revision before migration"
run_api_command alembic -c alembic.ini current

log "target Alembic head from new image"
run_api_command alembic -c alembic.ini heads

log "running Alembic upgrade head before API replacement"
run_api_command alembic -c alembic.ini upgrade head

log "recreating service without restarting dependencies"
docker compose -f "$DEPLOY_COMPOSE_FILE" up -d --no-deps "$DEPLOY_SERVICE"
api_replaced=1

log "verifying API deployment health at $DEPLOY_HEALTH_URL"
if ! wait_for_api_health; then
  log "API health verification failed; rolling back application code only"
  rollback_api_code
  if wait_for_api_health; then
    fail "rollback API health verified; database schema was not downgraded"
  fi
  fail "rollback API health verification failed; manual intervention required"
fi

log "switching frontend release"
switch_frontend_release

log "verifying frontend at $DEPLOY_FRONTEND_HEALTH_URL"
if ! wait_for_frontend_health; then
  log "frontend verification failed; restoring previous frontend and rolling back application code only"
  restore_frontend_release
  rollback_api_code
  if wait_for_api_health; then
    fail "rollback API health verified after frontend failure; database schema was not downgraded"
  fi
  fail "rollback API health verification failed after frontend failure; manual intervention required"
fi

log "deployment verified"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

created_empty_env=0
cleanup() {
  if [[ "$created_empty_env" == "1" ]]; then
    rm -f .env
  fi
}
trap cleanup EXIT

section() {
  printf '\n==> %s\n' "$1"
}

section "Backend compile"
(
  cd backend
  python -m compileall app scripts tests
)

section "Backend tests"
(
  cd backend
  python -m unittest discover -s tests
)

section "OpenAPI contract"
(
  cd backend
  python ../.github/scripts/verify_openapi_contract.py
  python ../.github/scripts/check_alembic_chain.py
)

section "Frontend install/test/lint/build"
(
  cd backend/frontend
  npm ci
  npm test
  npm run lint
  npm run build
)

section "Backend Docker build"
docker build -t lab-ia-genius-api:ci-local backend

section "Compose config"
if [[ ! -f .env ]]; then
  : > .env
  created_empty_env=1
fi
docker compose -f docker-compose.yml config --quiet
docker compose -f backend/docker-compose.yml config --quiet

section "Repository hygiene"
python .github/scripts/repository_hygiene.py

section "Local CI checks complete"

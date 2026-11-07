#!/usr/bin/env bash
# Start the canonical local Compose runtime without changing credentials,
# clearing volumes, or attempting to provision external Supabase services.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail 'Docker is required.'
command -v curl >/dev/null 2>&1 || fail 'curl is required for local API liveness.'
command -v python3 >/dev/null 2>&1 || fail 'Python 3 is required for canonical local database identity validation.'
[[ -f .env ]] || fail 'Missing .env. Configure the canonical local runtime environment.'
[[ -f .env.local ]] || fail 'Missing .env.local, required by the existing Compose web service.'

# The root Compose stack contains redis, api, and web. PostgreSQL is the
# canonical external/local Supabase service, never a shadow Compose database.
# Validate first: do not stop a healthy stack to discover configuration errors.
docker compose -f docker-compose.yml config --quiet || fail 'Compose configuration is invalid.'
# Validate only the final resolved Compose API environment, never parse .env
# independently or echo connection strings or passwords into the logs.
docker compose -f docker-compose.yml config --format json \
  | python3 scripts/dev/verify_local_db_config.py \
  || fail 'Canonical Supabase connection configuration failed validation.'

printf 'Starting local Redis, API, and web through canonical Compose services.\n'
docker compose -f docker-compose.yml up -d --wait redis
docker compose -f docker-compose.yml up -d --wait api web

# The existing read-only status owner validates API liveness, the typed
# canonical first-run state and web ingress. Reuse it rather than treating any
# first-run HTTP 200 as proof of a valid bootstrap contract.
if ! bash scripts/dev/status.sh; then
  fail 'Local runtime is not ready; inspect Compose logs, canonical Supabase migrations and first-run state.'
fi

printf 'Local Compose ingress validated. This is not a model, chat or replay acceptance receipt.\n'

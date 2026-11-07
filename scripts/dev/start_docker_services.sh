#!/usr/bin/env bash
# Start the canonical local Compose runtime without changing credentials,
# clearing volumes, or attempting to provision external Supabase services.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "\${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail 'Docker is required.'
command -v curl >/dev/null 2>&1 || fail 'curl is required for local API liveness.'
[[ -f .env ]] || fail 'Missing .env. Configure the canonical local runtime environment.'
[[ -f .env.local ]] || fail 'Missing .env.local, required by the existing Compose web service.'

# The root Compose stack contains redis, api, and web. PostgreSQL is the
# canonical external/local Supabase service, never a shadow Compose database.
# Validate first: do not stop a healthy stack to discover configuration errors.
docker compose -f docker-compose.yml config --quiet || fail 'Compose configuration is invalid.'

printf 'Starting local Redis, API, and web through canonical Compose services.\n'
docker compose -f docker-compose.yml up -d --wait redis
docker compose -f docker-compose.yml up -d --wait api web

# Container health alone is insufficient to claim the API is reachable from
# the host. Do not disclose response bodies or auth/session information.
if ! curl --fail --silent --show-error --max-time 10 --output /dev/null \
  'http://127.0.0.1:8000/health/live'; then
  fail 'API liveness failed; inspect docker compose logs api and database connectivity.'
fi

printf 'Local API liveness passed. Checking canonical first-run state.\n'
if ! curl --fail --silent --show-error --max-time 10 --output /dev/null \
  'http://127.0.0.1:8000/api/auth/first-run'; then
  fail 'First-run state unavailable. Check canonical Supabase migrations and AuthService logs; do not create runtime tables.'
fi

printf 'Local Compose services are running and API first-run ingress is reachable.\n'
printf 'Frontend: http://localhost:8010 | API: http://localhost:8000\n'
printf 'This does not prove model generation, authenticated chat, replay, or browser acceptance.\n'

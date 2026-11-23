#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

EXPECTED_SHA="${1:?Usage: bash scripts/ci/kui-card-studio-local-cleanup.sh <40-character-SHA>}"
if [[ ! "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Expected SHA must contain 40 lowercase hexadecimal characters.' >&2
  exit 2
fi
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
PROJECT="kcard-${EXPECTED_SHA:0:12}"
DB_NAME="kcard_${EXPECTED_SHA:0:12}"
OUT="${KAREN_KCARD_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/ai-karen/kcard-local/$EXPECTED_SHA}"
ENV_FILE="$OUT/.env.production"

COMPOSE_PROJECT_NAME="$PROJECT" docker compose --env-file "$ENV_FILE" \
  -f docker-compose.yml -f deploy/compose/docker-compose.prod.yml \
  -f deploy/compose/docker-compose.local-card-studio.yml down --remove-orphans --volumes || true

python3 - "$DB_NAME" <<'PY'
import subprocess
import sys

db_name = sys.argv[1]
containers = subprocess.run(['docker', 'ps', '--format', '{{.Names}}\t{{.Ports}}'], check=False, capture_output=True, text=True)
match = [line.split('\t', 1)[0] for line in containers.stdout.splitlines()
         if '54322->5432/tcp' in line and line.startswith('supabase_db_')]
if len(match) != 1:
    raise SystemExit('Cannot safely identify canonical local Supabase PostgreSQL')
container = match[0]
result = subprocess.run(
    ['docker', 'exec', container, 'dropdb', '--if-exists', '-U', 'postgres', '--force', db_name],
    check=False, capture_output=True, text=True,
)
if result.returncode != 0:
    raise SystemExit('Disposable local Supabase database cleanup failed')
print('KCARD_SUPABASE_DATABASE_CLEANED')
PY

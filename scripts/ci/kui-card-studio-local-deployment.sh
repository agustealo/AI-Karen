#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

EXPECTED_SHA="${1:?Usage: bash scripts/ci/kui-card-studio-local-deployment.sh <40-character-SHA>}"
if [[ ! "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Expected SHA must contain 40 lowercase hexadecimal characters.' >&2
  exit 2
fi
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
ACTUAL_SHA="$(git rev-parse HEAD)"
if [[ "$ACTUAL_SHA" != "$EXPECTED_SHA" || -n "$(git status --porcelain)" ]]; then
  echo 'Refusing deployment: exact clean HEAD required.' >&2
  exit 2
fi

OUT="${KAREN_KCARD_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/ai-karen/kcard-local/$ACTUAL_SHA}"
mkdir -p "$OUT"
PROJECT="kcard-${ACTUAL_SHA:0:12}"
DB_NAME="kcard_${ACTUAL_SHA:0:12}"
ENV_FILE="$OUT/.env.production"

python3 - "$ENV_FILE" "$ACTUAL_SHA" "$DB_NAME" "$OUT" <<'PY'
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

env_file = Path(sys.argv[1])
sha = sys.argv[2]
db_name = sys.argv[3]
out = Path(sys.argv[4])
root = Path.cwd()

base = {}
for line in (root / '.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        key, value = line.split('=', 1)
        base[key.strip()] = value.strip().strip('"').strip("'")

host = base.get('DB_HOST', '127.0.0.1')
port = base.get('DB_PORT', '54322')
user = base.get('DB_USER') or base.get('POSTGRES_USER') or 'postgres'
password = base.get('DB_PASSWORD') or base.get('DATABASE_PASSWORD') or base.get('POSTGRES_PASSWORD')
if not password:
    raise SystemExit('Local Supabase DB_PASSWORD or DATABASE_PASSWORD is required')

containers = subprocess.run(
    ['docker', 'ps', '--format', '{{.Names}}\t{{.Ports}}'],
    check=False, capture_output=True, text=True,
)
if containers.returncode != 0:
    raise SystemExit('Docker is unavailable')
supabase_containers = []
for line in containers.stdout.splitlines():
    name, _, ports = line.partition('\t')
    if name.startswith('supabase_db_') and '54322->5432/tcp' in ports:
        supabase_containers.append(name)
if len(supabase_containers) != 1:
    raise SystemExit('Expected one running canonical local Supabase PostgreSQL on loopback port 54322')
container = supabase_containers[0]

exists = subprocess.run(
    ['docker', 'exec', container, 'psql', '-U', 'postgres', '-d', 'postgres', '-tAc',
     f"SELECT 1 FROM pg_database WHERE datname='{db_name}'"],
    check=False, capture_output=True, text=True,
)
if exists.returncode != 0:
    raise SystemExit('Could not inspect local Supabase PostgreSQL')
if exists.stdout.strip() != '1':
    created = subprocess.run(
        ['docker', 'exec', container, 'createdb', '-U', 'postgres', db_name],
        check=False, capture_output=True, text=True,
    )
    if created.returncode != 0:
        raise SystemExit('Could not create disposable local Supabase database')

for migration in sorted((root / 'supabase/migrations').glob('*.sql')):
    applied = subprocess.run(
        ['docker', 'exec', '-i', container, 'psql', '-U', 'postgres', '-d', db_name,
         '-v', 'ON_ERROR_STOP=1'],
        input=migration.read_text(encoding='utf-8'),
        check=False, capture_output=True, text=True,
    )
    if applied.returncode != 0:
        raise SystemExit(f'Canonical migration failed: {migration.name}')

for name in ('logs_data', 'backup_data'):
    pass

encoded_password = quote(password, safe='')
encoded_user = quote(user, safe='')
container_host = 'host.docker.internal'
database_urls = {
    'KCARD_DATABASE_URL': f'postgresql+asyncpg://{encoded_user}:{encoded_password}@{container_host}:{port}/{db_name}',
    'KCARD_POSTGRES_URL': f'postgresql://{encoded_user}:{encoded_password}@{container_host}:{port}/{db_name}',
    'KCARD_AUTH_DATABASE_URL': f'postgresql+asyncpg://{encoded_user}:{encoded_password}@{container_host}:{port}/{db_name}',
}
values = {
    'KAREN_DEPLOYED_COMMIT_SHA': sha,
    'REDIS_PASSWORD': secret(),
    'SECRET_KEY': secret(),
    'AUTH_SECRET_KEY': secret(),
    'AUTH_JWT_SECRET_KEY': secret(),
    'EXTENSION_SECRET_KEY': secret(),
    'EXTENSION_API_KEY': secret(),
    'GRAFANA_ADMIN_PASSWORD': secret(),
    'KARI_CORS_ORIGINS': 'http://127.0.0.1:8010,http://localhost:8010',
    'WEB_PUBLIC_SCHEME': 'http',
    'DATABASE_PASSWORD': password,
    'DB_PASSWORD': password,
    'DB_HOST': container_host,
    'DB_PORT': port,
    'DB_USER': user,
    'DB_NAME': db_name,
    'KCARD_DB_USER': user,
    'KCARD_DB_PASSWORD': password,
    'KCARD_DB_NAME': db_name,
    **database_urls,
    'KAREN_TEST_CARD_STUDIO_DATABASE_URL': database_urls['KCARD_DATABASE_URL'],
    'KAREN_TEST_CARD_STUDIO_AUTH_DATABASE_URL': database_urls['KCARD_AUTH_DATABASE_URL'],
    'KCARD_COMPOSE_PROJECT': f'kcard-{sha[:12]}',
    'KCARD_ACCEPTANCE_ENV_FILE': str(env_file),
}
env_file.write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
(out / 'supabase-container.txt').write_text(container + '\n', encoding='utf-8')
(out / 'supabase-database.txt').write_text(db_name + '\n', encoding='utf-8')
PY
chmod 600 "$ENV_FILE"

export COMPOSE_PROJECT_NAME="$PROJECT"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f deploy/compose/docker-compose.prod.yml -f deploy/compose/docker-compose.local-card-studio.yml)

"${COMPOSE[@]}" build --pull api web
echo 'built_sha='"$ACTUAL_SHA" >"$OUT/deployment.txt"
"${COMPOSE[@]}" up -d redis api web

python3 scripts/ci/verify_local_card_studio_acceptance.py \
  --sha "$ACTUAL_SHA" --project "$PROJECT" --base-url "${KAREN_BASE_URL:-http://127.0.0.1:8010}" \
  --env-file "$ENV_FILE" --evidence "$OUT/evidence.json"

printf 'KCARD_LOCAL_DEPLOYMENT_READY\nPROJECT=%s\nSUPABASE_DATABASE=%s\nEVIDENCE=%s\n' "$PROJECT" "$DB_NAME" "$OUT/evidence.json"

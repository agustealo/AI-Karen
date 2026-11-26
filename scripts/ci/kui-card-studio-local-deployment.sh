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

if [[ "${GITHUB_ACTIONS:-false}" == 'true' || -v VERCEL_AUTOMATION_BYPASS_SECRET ]]; then
  echo 'Disposable provisioning is local-only.' >&2
  exit 2
fi

OUT="${KAREN_KCARD_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/ai-karen/kcard-local/$ACTUAL_SHA}"
PROJECT="kcard-${ACTUAL_SHA:0:12}"
DB_NAME="kcard_${ACTUAL_SHA:0:12}"
ENV_FILE="$OUT/.env.production"

python3 - "$ENV_FILE" "$ACTUAL_SHA" "$DB_NAME" "$OUT" <<'PY'
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from scripts.ci.verify_local_card_studio_acceptance import (
    GuardError, local_supabase_database_config, local_supabase_database_container,
    require_local_docker, local_storage_origin, verify_local_storage_gateway,
)

sha = sys.argv[2]
db_name = sys.argv[3]
out_path = Path(sys.argv[4])
root = Path.cwd().resolve()
out = out_path.resolve()
env_file = Path(sys.argv[1]).resolve()
if (out.is_relative_to(root) or out_path.is_symlink()
        or env_file != out / '.env.production'):
    raise SystemExit('Private acceptance state must be outside the checkout')
if out.exists():
    raise SystemExit('Acceptance state directory already exists; use a fresh private directory')

base = {}
for line in (root / '.env').read_text(encoding='utf-8').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        key, value = line.split('=', 1)
        base[key.strip()] = value.strip().strip('"').strip("'")

try:
    local_project, configured_port = local_supabase_database_config(root / 'supabase/config.toml')
except GuardError as exc:
    raise SystemExit(str(exc)) from None
host = base.get('DB_HOST', '127.0.0.1')
port = base.get('DB_PORT', str(configured_port))
user = base.get('DB_USER') or base.get('POSTGRES_USER') or 'postgres'
password = base.get('DB_PASSWORD') or base.get('DATABASE_PASSWORD') or base.get('POSTGRES_PASSWORD')
if not password:
    raise SystemExit('Local Supabase DB_PASSWORD or DATABASE_PASSWORD is required')
if host not in {'127.0.0.1', 'localhost', 'host.docker.internal'} or port != str(configured_port):
    raise SystemExit('Disposable provisioning requires the canonical configured local Supabase database')
try:
    require_local_docker()
    container = local_supabase_database_container(local_project, configured_port)
except GuardError as exc:
    raise SystemExit(str(exc)) from None

# Optional read-only Content Intelligence fixtures use the same local Supabase
# project. Validate before creating a disposable DB or copying credentials.
local_storage_url = base.get("KCARD_LOCAL_STORAGE_URL", "")
local_storage_key = base.get("KCARD_LOCAL_STORAGE_SECRET_KEY", "")
if local_storage_url or local_storage_key:
    if not local_storage_url or not local_storage_key:
        raise SystemExit("Local Storage fixture URL and key must be supplied together")
    try:
        local_storage_origin(local_storage_url)
        verify_local_storage_gateway(container, local_storage_url)
    except GuardError:
        raise SystemExit("Local Storage fixture target is not the running local Supabase gateway") from None

def secret() -> str:
    return secrets.token_hex(32)


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
    'KCARD_DB_PORT': port,
    'KCARD_DB_USER': user,
    'KCARD_DB_PASSWORD': password,
    'KCARD_DB_NAME': db_name,
    **database_urls,
    # Compose interpolates base and production files before overlay merging.
    'DATABASE_URL': database_urls['KCARD_DATABASE_URL'],
    'POSTGRES_URL': database_urls['KCARD_POSTGRES_URL'],
    'AUTH_DATABASE_URL': database_urls['KCARD_AUTH_DATABASE_URL'],
    'KAREN_TEST_CARD_STUDIO_DATABASE_URL': database_urls['KCARD_DATABASE_URL'],
    'KAREN_TEST_CARD_STUDIO_AUTH_DATABASE_URL': database_urls['KCARD_AUTH_DATABASE_URL'],
    'KCARD_COMPOSE_PROJECT': f'kcard-{sha[:12]}',
    'KCARD_ACCEPTANCE_ENV_FILE': str(env_file),
}
if local_storage_url:
    values["KCARD_LOCAL_STORAGE_URL"] = local_storage_url
    values["KCARD_LOCAL_STORAGE_SECRET_KEY"] = local_storage_key

def dotenv_value(value: str) -> str:
    if "\n" in value or "\r" in value or "\x00" in value:
        raise SystemExit('Multiline or invalid acceptance configuration')
    if all(ch.isascii() and (ch.isalnum() or ch in "_./:@%+,-") for ch in value):
        return value
    return "'" + value.replace("'", "\\'") + "'"


env_content = ''.join(f'{key}={dotenv_value(value)}\n' for key, value in values.items())
try:
    migrations = [(path.name, path.read_text(encoding='utf-8'))
                  for path in sorted((root / 'supabase/migrations').glob('*.sql'))]
except (OSError, UnicodeError):
    raise SystemExit('Canonical migrations could not be read') from None
if not migrations:
    raise SystemExit('Canonical migration inventory is empty')

exists = subprocess.run(
    ['docker', 'exec', container, 'psql', '-U', 'postgres', '-d', 'postgres', '-tAc',
     f"SELECT 1 FROM pg_database WHERE datname='{db_name}'"],
    check=False, capture_output=True, text=True,
)
if exists.returncode != 0:
    raise SystemExit('Could not inspect local Supabase PostgreSQL')
if exists.stdout.strip() != '':
    raise SystemExit('Disposable database already exists or returned unexpected evidence; refusing to replay migrations')
try:
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
except OSError:
    raise SystemExit('Could not reserve fresh private acceptance state') from None
created = subprocess.run(
    ['docker', 'exec', container, 'createdb', '-U', 'postgres', db_name],
    check=False, capture_output=True, text=True,
)
if created.returncode != 0:
    raise SystemExit('Could not create disposable local Supabase database')

for migration_name, migration_sql in migrations:
    applied = subprocess.run(
        ['docker', 'exec', '-i', container, 'psql', '-U', 'postgres', '-d', db_name,
         '-v', 'ON_ERROR_STOP=1'],
        input=migration_sql,
        check=False, capture_output=True, text=True,
    )
    if applied.returncode != 0:
        raise SystemExit(f'Canonical migration failed: {migration_name}')

env_file.write_text(env_content, encoding='utf-8')
(out / 'supabase-container.txt').write_text(container + '\n', encoding='utf-8')
(out / 'supabase-database.txt').write_text(db_name + '\n', encoding='utf-8')
PY
chmod 600 "$ENV_FILE"

export COMPOSE_PROJECT_NAME="$PROJECT"
# Shell environment takes precedence over --env-file in Compose. Do not let
# inherited production DSNs or secret variables override the local file.
COMPOSE=(env -i "PATH=$PATH" "HOME=$HOME" "DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}" docker compose -p "$PROJECT" --env-file "$ENV_FILE" -f docker-compose.yml -f deploy/compose/docker-compose.prod.yml -f deploy/compose/docker-compose.local-card-studio.yml)

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build --pull api web
echo 'built_sha='"$ACTUAL_SHA" >"$OUT/deployment.txt"
"${COMPOSE[@]}" up -d redis api web

python3 scripts/ci/verify_local_card_studio_acceptance.py \
  --sha "$ACTUAL_SHA" --project "$PROJECT" --base-url "${KAREN_BASE_URL:-http://127.0.0.1:8010}" \
  --env-file "$ENV_FILE" --evidence "$OUT/evidence.json"

printf 'KCARD_LOCAL_DEPLOYMENT_READY\nPROJECT=%s\nSUPABASE_DATABASE=%s\nEVIDENCE=%s\n' "$PROJECT" "$DB_NAME" "$OUT/evidence.json"

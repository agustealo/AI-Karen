#!/usr/bin/env bash
set -euo pipefail

# Self-contained real-product presentation capture.
#
# Trusted workflow code owns orchestration. The candidate checkout supplies only
# the production application images and canonical migrations. Every credential,
# database, tenant, user, and container exists only for this runner invocation.

TARGET_ROOT="${KAREN_PRESENTATION_TARGET_ROOT:?KAREN_PRESENTATION_TARGET_ROOT is required}"
TARGET_REVISION="${KAREN_SHOWCASE_TARGET_REVISION:?KAREN_SHOWCASE_TARGET_REVISION is required}"
TRUSTED_ROOT="${KAREN_PRESENTATION_TRUSTED_ROOT:-$(pwd)}"
API_IMAGE="${KAREN_PRESENTATION_API_IMAGE:-ai-karen-presentation-api:candidate}"
WEB_IMAGE="${KAREN_PRESENTATION_WEB_IMAGE:-ai-karen-presentation-web:candidate}"
POSTGRES_IMAGE="${KAREN_PRESENTATION_POSTGRES_IMAGE:-pgvector/pgvector:pg16}"
REDIS_IMAGE="${KAREN_PRESENTATION_REDIS_IMAGE:-redis:7-alpine}"
API_PORT="${KAREN_PRESENTATION_API_PORT:-18000}"
WEB_PORT="${KAREN_PRESENTATION_WEB_PORT:-18010}"
RUN_ID="${GITHUB_RUN_ID:-local}-$$"
NETWORK="karen-presentation-${RUN_ID}"
POSTGRES_CONTAINER="karen-presentation-postgres-${RUN_ID}"
REDIS_CONTAINER="karen-presentation-redis-${RUN_ID}"
API_CONTAINER="karen-presentation-api-${RUN_ID}"
WEB_CONTAINER="karen-presentation-web-${RUN_ID}"
DB_NAME="karen_presentation"
DB_USER="postgres"
COOKIE_JAR="$(mktemp)"

random_token() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
}

DB_PASSWORD="$(random_token)"
REDIS_PASSWORD="$(random_token)"
JWT_SECRET="$(random_token)$(random_token)"
APP_SECRET="$(random_token)$(random_token)"
EXTENSION_SECRET="$(random_token)$(random_token)"
ADMIN_EMAIL="presentation-${RUN_ID//[^A-Za-z0-9]/-}@example.invalid"
ADMIN_PASSWORD="P!$(random_token)9z"
ADMIN_NAME="KAREN Presentation Operator"
API_BASE="http://127.0.0.1:${API_PORT}"
WEB_BASE="http://127.0.0.1:${WEB_PORT}"

cleanup() {
  rm -f "${COOKIE_JAR}"
  docker rm -f "${WEB_CONTAINER}" >/dev/null 2>&1 || true
  docker rm -f "${API_CONTAINER}" >/dev/null 2>&1 || true
  docker rm -f "${REDIS_CONTAINER}" >/dev/null 2>&1 || true
  docker rm -f "${POSTGRES_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_for() {
  local description="$1"
  local attempts="$2"
  shift 2
  for ((attempt=1; attempt<=attempts; attempt++)); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "timed out waiting for ${description}" >&2
  return 1
}

fail_with_logs() {
  echo "self-contained presentation runtime failed" >&2
  docker logs "${API_CONTAINER}" >&2 || true
  docker logs "${WEB_CONTAINER}" >&2 || true
  exit 1
}

if [[ ! "${TARGET_REVISION}" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "KAREN_SHOWCASE_TARGET_REVISION must be a full 40-character git SHA" >&2
  exit 1
fi
if [[ ! -d "${TARGET_ROOT}/supabase/migrations" ]]; then
  echo "candidate checkout is missing canonical migrations" >&2
  exit 1
fi

echo "[presentation] creating isolated network"
docker network create "${NETWORK}" >/dev/null

echo "[presentation] starting disposable PostgreSQL + pgvector"
docker run -d \
  --name "${POSTGRES_CONTAINER}" \
  --network "${NETWORK}" \
  -e POSTGRES_USER="${DB_USER}" \
  -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
  -e POSTGRES_DB="${DB_NAME}" \
  "${POSTGRES_IMAGE}" >/dev/null
wait_for PostgreSQL 45 docker exec "${POSTGRES_CONTAINER}" pg_isready -U "${DB_USER}" -d "${DB_NAME}"

echo "[presentation] starting disposable password-protected Redis"
docker run -d \
  --name "${REDIS_CONTAINER}" \
  --network "${NETWORK}" \
  "${REDIS_IMAGE}" redis-server --requirepass "${REDIS_PASSWORD}" >/dev/null
wait_for Redis 30 docker exec "${REDIS_CONTAINER}" redis-cli -a "${REDIS_PASSWORD}" ping

echo "[presentation] applying candidate canonical migrations"
while IFS= read -r migration; do
  docker exec -i "${POSTGRES_CONTAINER}" \
    psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${DB_NAME}" <"${migration}"
done < <(find "${TARGET_ROOT}/supabase/migrations" -maxdepth 1 -type f -name '*.sql' | sort)

api_env=(
  -e ENVIRONMENT=production
  -e DEBUG=false
  -e AUTH_DEV_MODE=false
  -e AUTH_ALLOW_DEV_LOGIN=false
  -e KARI_AUTH_BYPASS=false
  -e AUTH_ENABLE_SESSION_VALIDATION=true
  -e AUTH_AUTO_CREATE_TABLES=false
  -e AUTH_JWT_SECRET_KEY="${JWT_SECRET}"
  -e AUTH_SECRET_KEY="${APP_SECRET}"
  -e SECRET_KEY="${APP_SECRET}"
  -e EXTENSION_SECRET_KEY="${EXTENSION_SECRET}"
  -e EXTENSION_API_KEY="${EXTENSION_SECRET}"
  -e EXTENSION_DEV_BYPASS_ENABLED=false
  -e KARI_DUCKDB_PASSWORD="$(random_token)"
  -e KARI_JOB_ENC_KEY="YmV0YS1zbW9rZS1qb2ItZW5jLWtleS0zMi1ieXRlISE="
  -e KARI_JOB_SIGNING_KEY="$(random_token)$(random_token)"
  -e KARI_MODEL_SIGNING_KEY="$(random_token)$(random_token)"
  -e KARI_FAST_STARTUP=false
  -e KARI_SKIP_STARTUP_CHECK=false
  -e KARI_SKIP_AUTO_INIT=false
  -e KARI_DEFER_ROUTER_WIRING=false
  -e KAREN_BUILTIN_VLLM_ENABLED=false
  -e WARMUP_LLM=false
  -e DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${POSTGRES_CONTAINER}:5432/${DB_NAME}"
  -e POSTGRES_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${POSTGRES_CONTAINER}:5432/${DB_NAME}"
  -e AUTH_DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${POSTGRES_CONTAINER}:5432/${DB_NAME}"
  -e POSTGRES_HOST="${POSTGRES_CONTAINER}"
  -e POSTGRES_PORT=5432
  -e POSTGRES_USER="${DB_USER}"
  -e POSTGRES_PASSWORD="${DB_PASSWORD}"
  -e POSTGRES_DB="${DB_NAME}"
  -e DB_HOST="${POSTGRES_CONTAINER}"
  -e DB_PORT=5432
  -e DB_USER="${DB_USER}"
  -e DB_PASSWORD="${DB_PASSWORD}"
  -e DB_NAME="${DB_NAME}"
  -e DATABASE_PASSWORD="${DB_PASSWORD}"
  -e SSL_MODE=prefer
  -e REDIS_PASSWORD="${REDIS_PASSWORD}"
  -e REDIS_URL="redis://:${REDIS_PASSWORD}@${REDIS_CONTAINER}:6379/0"
  -e REDIS_HOST="${REDIS_CONTAINER}"
  -e REDIS_PORT=6379
)

echo "[presentation] booting exact candidate API image"
docker run -d \
  --name "${API_CONTAINER}" \
  --network "${NETWORK}" \
  -p "127.0.0.1:${API_PORT}:8000" \
  "${api_env[@]}" \
  "${API_IMAGE}" >/dev/null

if ! wait_for "candidate API liveness" 90 curl -fsS "${API_BASE}/health/live"; then
  fail_with_logs
fi
if ! wait_for "candidate auth readiness" 30 curl -fsS "${API_BASE}/api/auth/health"; then
  fail_with_logs
fi

echo "[presentation] creating disposable sanitized tenant owner through canonical first-run auth"
curl -fsS \
  -c "${COOKIE_JAR}" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\",\"confirm_password\":\"${ADMIN_PASSWORD}\",\"full_name\":\"${ADMIN_NAME}\"}" \
  "${API_BASE}/api/auth/first-run/setup" >/dev/null
curl -fsS -b "${COOKIE_JAR}" "${API_BASE}/api/auth/me" >/dev/null

echo "[presentation] creating real tenant-scoped automation state through public APIs"
job_json="$(curl -fsS \
  -b "${COOKIE_JAR}" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Morning Operations Brief","description":"Prepare the sanitized presentation workspace for the next operating review.","tasks":[],"trigger":"Scheduled"}' \
  "${API_BASE}/api/automation/jobs/")"
job_id="$(python3 - "${job_json}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
value=str(payload.get("id") or "").strip()
assert value, payload
print(value)
PY
)"

curl -fsS \
  -b "${COOKIE_JAR}" \
  -H 'Content-Type: application/json' \
  -d "{\"taskName\":\"Morning Operations Brief\",\"schedule\":\"0 9 * * *\",\"type\":\"Job\",\"targetId\":\"${job_id}\",\"enabled\":true,\"action\":\"enqueue\"}" \
  "${API_BASE}/api/automation/cron" >/dev/null

stats_json="$(curl -fsS -b "${COOKIE_JAR}" "${API_BASE}/api/automation/stats/")"
python3 - "${stats_json}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
assert str(payload.get("definedSequences")) == "1", payload
assert str(payload.get("nextJob") or "").strip().lower() not in {"", "none scheduled", "n/a"}, payload
assert str(payload.get("nextJobTime") or "").strip().lower() not in {"", "none scheduled", "n/a"}, payload
PY

echo "[presentation] booting exact candidate web image"
docker run -d \
  --name "${WEB_CONTAINER}" \
  --network "${NETWORK}" \
  -p "127.0.0.1:${WEB_PORT}:8010" \
  -e WEB_PUBLIC_SCHEME=http \
  -e KAREN_BACKEND_URL="http://${API_CONTAINER}:8000" \
  "${WEB_IMAGE}" >/dev/null

if ! wait_for "candidate web login" 60 curl -fsS "${WEB_BASE}/login"; then
  fail_with_logs
fi

echo "[presentation] capturing with trusted repository-owned Playwright harness"
cd "${TRUSTED_ROOT}/src/ui_launchers/Karen-AI-Theme"
KAREN_SHOWCASE_ALLOW_CAPTURE=true \
KAREN_SHOWCASE_ACCOUNT_KIND=sanitized-demo \
KAREN_SHOWCASE_BASE_URL="${WEB_BASE}" \
KAREN_SHOWCASE_EMAIL="${ADMIN_EMAIL}" \
KAREN_SHOWCASE_PASSWORD="${ADMIN_PASSWORD}" \
KAREN_SHOWCASE_TARGET_REVISION="${TARGET_REVISION}" \
GITHUB_SHA="${GITHUB_SHA:-}" \
npx playwright test --config=e2e/playwright.showcase.config.ts

echo "SELF-CONTAINED KAREN PRESENTATION CAPTURE PASSED"

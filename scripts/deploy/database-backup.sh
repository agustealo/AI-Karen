#!/usr/bin/env bash
set -euo pipefail

# Canonical production backup command for AI Karen's primary PostgreSQL store.
# This script intentionally does not back up Redis, Milvus, Elasticsearch, model
# artifacts, or external object storage. Those remain separate recovery domains.

: "${DATABASE_URL:?DATABASE_URL is required}"

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "error: pg_dump is required" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKUP_ROOT="${KAREN_BACKUP_ROOT:-./backups/postgres}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT}/${STAMP}"
BACKUP_FILE="${BACKUP_DIR}/ai-karen-postgres.dump"
CHECKSUM_FILE="${BACKUP_FILE}.sha256"
METADATA_FILE="${BACKUP_DIR}/metadata.txt"

mkdir -p "${BACKUP_DIR}"
umask 077

release_revision="${KAREN_RELEASE_REVISION:-${GITHUB_SHA:-}}"
if [[ -z "${release_revision}" ]] && command -v git >/dev/null 2>&1; then
  release_revision="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
fi
release_revision="${release_revision:-unknown}"

migration_revision="unknown"
if [[ -d "${REPO_ROOT}/supabase/migrations" ]]; then
  migration_revision="$({
    find "${REPO_ROOT}/supabase/migrations" -type f -print0 \
      | sort -z \
      | xargs -0 sha256sum
  } | sha256sum | awk '{print $1}')"
fi

pg_dump \
  --dbname="${DATABASE_URL}" \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file="${BACKUP_FILE}"

if [[ ! -s "${BACKUP_FILE}" ]]; then
  echo "error: backup artifact is empty" >&2
  exit 3
fi

sha256sum "${BACKUP_FILE}" > "${CHECKSUM_FILE}"
sha256sum --check "${CHECKSUM_FILE}" >/dev/null

cat > "${METADATA_FILE}" <<EOF
created_at_utc=${STAMP}
format=postgres_custom
schema_authority=supabase/migrations
release_revision=${release_revision}
migration_revision=${migration_revision}
backup_file=$(basename "${BACKUP_FILE}")
checksum_file=$(basename "${CHECKSUM_FILE}")
EOF

printf '%s\n' "${BACKUP_DIR}"

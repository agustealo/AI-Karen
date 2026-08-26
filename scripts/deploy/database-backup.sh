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

BACKUP_ROOT="${KAREN_BACKUP_ROOT:-./backups/postgres}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT}/${STAMP}"
BACKUP_FILE="${BACKUP_DIR}/ai-karen-postgres.dump"
CHECKSUM_FILE="${BACKUP_FILE}.sha256"
METADATA_FILE="${BACKUP_DIR}/metadata.txt"

mkdir -p "${BACKUP_DIR}"
umask 077

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
backup_file=$(basename "${BACKUP_FILE}")
checksum_file=$(basename "${CHECKSUM_FILE}")
EOF

printf '%s\n' "${BACKUP_DIR}"

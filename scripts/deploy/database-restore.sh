#!/usr/bin/env bash
set -euo pipefail

# Guarded restore command for AI Karen's primary PostgreSQL store.
# Restore is intentionally destructive and requires an explicit target URL and
# confirmation token. Never point RESTORE_DATABASE_URL at production casually.

: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required}"
: "${BACKUP_FILE:?BACKUP_FILE is required}"

if [[ "${CONFIRM_RESTORE:-}" != "I_UNDERSTAND_THIS_IS_DESTRUCTIVE" ]]; then
  echo "error: set CONFIRM_RESTORE=I_UNDERSTAND_THIS_IS_DESTRUCTIVE" >&2
  exit 2
fi

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "error: pg_restore is required" >&2
  exit 3
fi

if [[ ! -s "${BACKUP_FILE}" ]]; then
  echo "error: backup file does not exist or is empty: ${BACKUP_FILE}" >&2
  exit 4
fi

CHECKSUM_FILE="${BACKUP_FILE}.sha256"
if [[ ! -f "${CHECKSUM_FILE}" ]]; then
  echo "error: checksum file is required: ${CHECKSUM_FILE}" >&2
  exit 5
fi

sha256sum --check "${CHECKSUM_FILE}"

# Clean objects owned by the backup before restore. This should be executed only
# against an isolated recovery/staging database or under an approved runbook.
pg_restore \
  --dbname="${RESTORE_DATABASE_URL}" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --exit-on-error \
  "${BACKUP_FILE}"

echo "restore completed"

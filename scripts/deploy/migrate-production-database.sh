#!/usr/bin/env bash
set -euo pipefail

# Canonical production schema migration command.
# Authority: supabase/migrations
# Safety rule: take and verify a PostgreSQL backup before applying migrations.

: "${DATABASE_URL:?DATABASE_URL is required}"

if ! command -v supabase >/dev/null 2>&1; then
  echo "error: Supabase CLI is required" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ ! -d "${REPO_ROOT}/supabase/migrations" ]]; then
  echo "error: canonical migration directory is missing" >&2
  exit 3
fi

BACKUP_DIR="$(bash "${SCRIPT_DIR}/database-backup.sh")"
if [[ ! -d "${BACKUP_DIR}" ]]; then
  echo "error: pre-migration backup was not created" >&2
  exit 4
fi

BACKUP_FILE="${BACKUP_DIR}/ai-karen-postgres.dump"
sha256sum --check "${BACKUP_FILE}.sha256" >/dev/null

echo "pre-migration backup verified: ${BACKUP_DIR}"

cd "${REPO_ROOT}"
supabase migration list --db-url "${DATABASE_URL}"
supabase db push --db-url "${DATABASE_URL}" --include-all

echo "production migrations applied from supabase/migrations"

#!/usr/bin/env bash
set -euo pipefail

# Guarded restore command for AI Karen's primary PostgreSQL store.
# Restore is intentionally destructive and requires an explicit target URL and
# confirmation token. Never point RESTORE_DATABASE_URL at production casually.

: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required}"
: "${BACKUP_FILE:?BACKUP_FILE is required}"

if [ -d "/usr/lib/postgresql/17/bin" ]; then
  export PATH="/usr/lib/postgresql/17/bin:$PATH"
fi

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

# Verify the actual selected archive, not a path supplied by the sidecar.
# A relocated backup remains usable, but a checksum for unrelated bytes does not.
mapfile -t checksum_lines < "${CHECKSUM_FILE}"
if [[ "${#checksum_lines[@]}" -ne 1 ]]; then
  echo "error: expected one backup checksum record" >&2
  exit 5
fi
read -r expected_digest _ <<< "${checksum_lines[0]}"
actual_digest="$(sha256sum < "${BACKUP_FILE}")"
if [[ ! "${expected_digest}" =~ ^[[:xdigit:]]{64}$ ]] || \
   [[ "${expected_digest,,}" != "${actual_digest%% *}" ]]; then
  echo "error: selected backup checksum mismatch" >&2
  exit 5
fi

# Recovery must stage into a fresh, isolated database. Refuse to overwrite
# existing application relations, including the live consent/retirement ledger.
# This is an emptiness check, NOT proof of network isolation or an admission
# lease. Operators must keep the target exclusively offline until reconciled.
if ! command -v psql >/dev/null 2>&1; then
  echo "error: psql is required for restore target preflight" >&2
  exit 3
fi
target_empty="$(psql -X -qAt --set=ON_ERROR_STOP=1 \
  --dbname="${RESTORE_DATABASE_URL}" --command="
    SELECT NOT EXISTS (
      SELECT 1 FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
        AND c.relkind IN ('r','p','f','m','v','S')
    )
  ")"
if [[ "${target_empty}" != "t" ]]; then
  echo "error: restore target contains existing relations; use a fresh isolated database" >&2
  exit 6
fi

# A failed restore must not commit a partially loaded authority.
pg_restore \
  --dbname="${RESTORE_DATABASE_URL}" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --single-transaction \
  --exit-on-error \
  "${BACKUP_FILE}"

echo "restore staged; governed-memory recovery admission is not verified"

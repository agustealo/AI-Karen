#!/usr/bin/env bash
set -euo pipefail

# Capture a minimum physical WAL replay position from the authoritative primary.
# This is evidence collection, not a writer fence or recovery admission command.
# The receipt must be retained in a trusted external recovery inventory.

if [[ "${CONFIRM_SOURCE_FENCED:-}" != "I_HAVE_FENCED_SOURCE_WRITERS" ]]; then
  echo "error: fence and drain source writers; set CONFIRM_SOURCE_FENCED=I_HAVE_FENCED_SOURCE_WRITERS" >&2
  exit 2
fi
: "${DATABASE_URL:?DATABASE_URL is required for the authoritative source}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/postgres-recovery-client.sh"
select_postgres_recovery_client "${DATABASE_URL}" psql || exit 3

# The insert position includes previously committed asynchronous writes too.
# Require the observed flush position to cover it before emitting a receipt.
# Retry only an empty (not yet flushed) observation, never a database error.
for _ in $(seq 1 20); do
  receipt="$(psql -X -qAt --set=ON_ERROR_STOP=1 \
    --dbname="${DATABASE_URL}" --command="
      WITH cutoff AS MATERIALIZED (
        SELECT pg_current_wal_insert_lsn() AS required_lsn
        WHERE NOT pg_is_in_recovery()
      ), evidence AS MATERIALIZED (
        SELECT required_lsn, pg_current_wal_flush_lsn() AS flushed_lsn
        FROM cutoff
      )
      SELECT json_build_object(
        'schema_version', 1,
        'evidence_type', 'postgres_physical_wal_cutoff',
        'system_identifier', (pg_control_system()).system_identifier::text,
        'database_name', current_database(),
        'database_oid', (SELECT oid::text FROM pg_database WHERE datname = current_database()),
        'server_major', current_setting('server_version_num')::int / 10000,
        'timeline_hex', left(pg_walfile_name(required_lsn), 8),
        'required_lsn', required_lsn::text,
        'observed_flush_lsn', flushed_lsn::text,
        'captured_at', to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')
      )
      FROM evidence
      WHERE required_lsn IS NOT NULL AND flushed_lsn >= required_lsn
    ")" || exit 4
  if [[ -n "$receipt" ]]; then
    printf '%s\n' "$receipt"
    exit 0
  fi
  sleep 0.25
done
echo "error: no flushed primary WAL cutoff observed; recovery hold remains" >&2
exit 4

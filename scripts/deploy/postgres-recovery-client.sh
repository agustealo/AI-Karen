# Shared client compatibility boundary for PostgreSQL backup and restore.
# Source from an operator script running with set -euo pipefail.
# Match the connected server's major version; newer dump/restore clients can
# emit configuration statements that an older recovery server cannot parse.
select_postgres_recovery_client() {
  local database_url="$1"
  local tool="$2"
  local probe="psql" server_num server_major version version_major
  local client_dir="${KAREN_POSTGRES_BIN_DIR:-}"

  if [[ "$tool" != "pg_dump" && "$tool" != "pg_restore" ]]; then
    echo "error: unsupported PostgreSQL recovery client" >&2
    return 1
  fi
  if [[ -n "$client_dir" ]]; then
    probe="$client_dir/psql"
  fi
  if ! command -v "$probe" >/dev/null 2>&1; then
    echo "error: psql is required to identify the PostgreSQL server version" >&2
    return 1
  fi
  if ! server_num="$("$probe" -X -qAt --set=ON_ERROR_STOP=1 \
    --dbname="$database_url" --command='SHOW server_version_num')"; then
    echo "error: unable to determine PostgreSQL server version" >&2
    return 1
  fi
  if [[ ! "$server_num" =~ ^[1-9][0-9]{5}$ ]]; then
    echo "error: invalid or unsupported PostgreSQL server version" >&2
    return 1
  fi
  server_major=$((server_num / 10000))
  if [[ -z "$client_dir" && -x "/usr/lib/postgresql/$server_major/bin/$tool" ]]; then
    client_dir="/usr/lib/postgresql/$server_major/bin"
  fi
  if [[ -n "$client_dir" ]]; then
    if [[ ! -x "$client_dir/$tool" || ! -x "$client_dir/psql" ]]; then
      echo "error: configured PostgreSQL client directory is incomplete" >&2
      return 1
    fi
    export PATH="$client_dir:$PATH"
  fi
  # Check both the dump/restore binary and the preflight psql. Never fall
  # through to a different major when a matching client is unavailable.
  for tool in "$tool" psql; do
    if ! version="$("$tool" --version)" || \
       [[ ! "$version" =~ PostgreSQL\)\ ([0-9]+)\. ]]; then
      echo "error: cannot verify PostgreSQL client version: $tool" >&2
      return 1
    fi
    version_major="${BASH_REMATCH[1]}"
    if [[ "$version_major" != "$server_major" ]]; then
      echo "error: $tool major $version_major does not match PostgreSQL server major $server_major" >&2
      return 1
    fi
  done
  POSTGRES_RECOVERY_SERVER_MAJOR="$server_major"
}

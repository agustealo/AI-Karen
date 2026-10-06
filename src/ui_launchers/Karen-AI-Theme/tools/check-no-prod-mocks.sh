#!/usr/bin/env bash
set -euo pipefail

forbidden_regex='\b(mock|dummy|demo)\b|mock-up|conceptual placeholder|synthetic output'
grep_regex='(^|[^[:alnum:]_])(mock|dummy|demo)([^[:alnum:]_]|$)|mock-up|conceptual placeholder|synthetic output'

paths=(core api_routes services src/components src/lib src/app)
has_hits=0

scan_with_rg() {
  local path="$1"
  rg \
    -n -i "$forbidden_regex" \
    -g '!**/*.test.*' \
    -g '!**/tests/**' \
    -g '!**/test/**' \
    -g '!**/__mocks__/**' \
    -g '!**/plugin_repo_backups/**' \
    "$path"
}

scan_with_grep() {
  local path="$1"
  grep \
    -R -n -i -E "$grep_regex" \
    --exclude='*.test.*' \
    --exclude-dir='tests' \
    --exclude-dir='test' \
    --exclude-dir='__mocks__' \
    --exclude-dir='plugin_repo_backups' \
    "$path"
}

if command -v rg >/dev/null 2>&1; then
  scanner=scan_with_rg
elif command -v grep >/dev/null 2>&1; then
  scanner=scan_with_grep
else
  echo "No supported scanner is available; refusing to skip production mock detection." >&2
  exit 2
fi

for path in "\${paths[@]}"; do
  [[ -d "$path" ]] || continue

  set +e
  "$scanner" "$path"
  status=$?
  set -e

  case "$status" in
    0)
      has_hits=1
      ;;
    1)
      ;;
    *)
      echo "Production mock scan failed for $path with status $status." >&2
      exit "$status"
      ;;
  esac
done

if [[ "$has_hits" -ne 0 ]]; then
  echo "Forbidden mock/demo patterns found in production paths." >&2
  exit 1
fi

echo "No forbidden mock/demo patterns found in production paths."

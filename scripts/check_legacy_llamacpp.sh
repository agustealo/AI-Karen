#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-src}"

echo "Scanning for legacy local-backend references..."
legacy_a="llama"
legacy_b="cpp"
legacy_pattern="${legacy_a}${legacy_b}|${legacy_a}[._]${legacy_b}"
hits="$(grep -RInE \
  --exclude-dir=.git \
  --exclude-dir=.next \
  --exclude-dir=node_modules \
  --exclude-dir=__pycache__ \
  --exclude='*.md' \
  --exclude='*.txt' \
  --exclude='*.json' \
  "${legacy_pattern}" \
  "$ROOT" || true)"

if [[ -n "$hits" ]]; then
  echo "$hits"
  echo
  echo "FAIL: legacy local-backend references remain in active source."
  exit 1
fi

echo "PASS: no active legacy local-backend references found."

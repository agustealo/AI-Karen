#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-audit}"
ROOT="${ROOT:-$(pwd)}"
REPORT_DIR="${REPORT_DIR:-$ROOT/runtime_refactor_reports}"
STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT="$REPORT_DIR/runtime_refactor_$STAMP.md"

mkdir -p "$REPORT_DIR"
: > "$REPORT"

log() {
  printf '%s\n' "$*"
  printf '%s\n' "$*" >> "$REPORT"
}

section() {
  printf '\n## %s\n\n' "$*" >> "$REPORT"
  printf '\n== %s ==\n' "$*"
}

scan_hits() {
  local pattern="$1"
  grep -RInE \
    --include='*.py' \
    --include='*.sh' \
    --include='*.yml' \
    --include='*.yaml' \
    --include='*.json' \
    --include='*.md' \
    --exclude-dir=.git \
    --exclude-dir=.next \
    --exclude-dir=node_modules \
    --exclude-dir=__pycache__ \
    --exclude-dir=.venv \
    --exclude-dir=venv \
    --exclude-dir=scripts \
    --exclude-dir=tests \
    --exclude='*.pyc' \
    "$pattern" \
    "$ROOT/src" \
    "$ROOT/config_assets" \
    "$ROOT/models" \
    "$ROOT/docker" \
    "$ROOT/Dockerfile" \
    "$ROOT/docker-compose.yml" \
    "$ROOT/docker-compose.cuda.yml" \
    "$ROOT/deploy-cuda.sh" \
    "$ROOT/health-check-cuda.sh" \
    "$ROOT/status.sh" \
    "$ROOT/stop-cuda.sh" \
    "$ROOT/update-cuda.sh" \
    "$ROOT/.env.cuda" 2>/dev/null || true
}

audit_legacy_llamacpp() {
  section "Legacy llama.cpp References"
  local hits
  hits="$(scan_hits 'llamacpp|llama_cpp|llama\.cpp')"
  if [[ -n "$hits" ]]; then
    log "$hits"
    log ""
    log "FAIL: legacy llama.cpp references remain."
  else
    log "PASS: no llama.cpp references found in active paths."
  fi
}

audit_direct_provider_calls() {
  section "Direct Provider Call Sites"
  local hits
  hits="$(scan_hits 'provider\.(generate_text|generate_text_stream|stream_generate|generate_response|generate_chat|stream_chat)|call_openai|call_ollama|call_vllm')"
  if [[ -n "$hits" ]]; then
    log "$hits"
    log ""
    log "FAIL: direct provider call sites remain."
  else
    log "PASS: no direct provider call sites found."
  fi
}

audit_vllm_and_transformers() {
  section "Runtime Authority"
  if grep -n "class ModelManager" "$ROOT/src/ai_karen_engine/core/model_runtime/model_manager.py" >/dev/null 2>&1; then
    log "PASS: ModelManager present in core/model_runtime/model_manager.py"
  else
    log "FAIL: ModelManager missing from core/model_runtime/model_manager.py"
  fi

  if grep -n "class VLLMRuntime" "$ROOT/src/ai_karen_engine/inference/vllm_runtime.py" >/dev/null 2>&1; then
    log "PASS: VLLM runtime present in inference/vllm_runtime.py"
  else
    log "FAIL: VLLM runtime missing from inference/vllm_runtime.py"
  fi

  if grep -n "class TransformersRuntime" "$ROOT/src/ai_karen_engine/inference/transformers_runtime.py" >/dev/null 2>&1; then
    log "PASS: Transformers runtime present in inference/transformers_runtime.py"
  else
    log "FAIL: Transformers runtime missing from inference/transformers_runtime.py"
  fi
}

apply_cleanup() {
  section "Apply Cleanup"

  local remove_files=(
    "src/ai_karen_engine/core/reasoning/synthesis/llamacpp_client.py"
    "src/ai_karen_engine/inference/llamacpp_runtime.py"
    "src/ai_karen_engine/integrations/providers/llamacpp_provider.py"
    "src/ai_karen_engine/integrations/providers/llamacpp_provider_optimized.py"
  )

  for file in "${remove_files[@]}"; do
    if [[ -f "$ROOT/$file" ]]; then
      rm -f "$ROOT/$file"
      log "REMOVED: $file"
    else
      log "SKIP missing: $file"
    fi
  done
}

main() {
  log "# Runtime Authority Refactor Report"
  log ""
  log "Mode: $MODE"
  log "Root: $ROOT"
  log "Timestamp: $STAMP"

  audit_legacy_llamacpp
  audit_direct_provider_calls
  audit_vllm_and_transformers

  case "$MODE" in
    audit)
      log ""
      log "AUDIT ONLY: no files changed."
      ;;
    apply)
      apply_cleanup
      audit_legacy_llamacpp
      audit_direct_provider_calls
      ;;
    *)
      echo "Usage: scripts/refactor_runtime_authority.sh audit|apply" >&2
      exit 1
      ;;
  esac

  log ""
  log "Report written to: $REPORT"
}

main "$@"

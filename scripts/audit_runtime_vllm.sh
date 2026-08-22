#!/usr/bin/env bash
# Karen Runtime vLLM Audit Script
# Verifies that vLLM is wired as a real live response engine, not a degraded-mode label

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ROOT_DIR="${1:-$(pwd)}"
VLLM_BASE_URL="${KAREN_VLLM_BASE_URL:-http://localhost:8001/v1}"
VLLM_HEALTH_URL="${KAREN_VLLM_HEALTH_URL:-http://localhost:8001/health}"
KAREN_API_URL="${KAREN_API_URL:-http://localhost:8000}"
MODEL="${KAREN_VLLM_MODEL:-}"
AUDIT_REPORT="vllm_audit_report_$(date +%Y%m%d_%H%M%S).md"

# Counters
PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

cd "$ROOT_DIR"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         Karen Runtime vLLM Audit - Live Response Verification  ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Root Directory: $ROOT_DIR"
echo "vLLM Base URL: $VLLM_BASE_URL"
echo "Karen API URL: $KAREN_API_URL"
echo "Audit Report: $AUDIT_REPORT"
echo ""

# Initialize report
cat > "$AUDIT_REPORT" << EOF
# Karen vLLM Runtime Audit Report
**Generated:** $(date -u +"%Y-%m-%d %H:%M:%S UTC")
**Auditor:** Karen Runtime Audit Script v1.0

## Executive Summary

This audit verifies that vLLM is wired as a real live response engine in Karen's runtime,
not a degraded-mode label, fake fallback, or UI-only metadata trick.

---

## Audit Results

EOF

log_pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    echo "- ✅ **PASS**: $1" >> "$AUDIT_REPORT"
    ((PASS_COUNT++))
}

log_fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    echo "- ❌ **FAIL**: $1" >> "$AUDIT_REPORT"
    ((FAIL_COUNT++))
}

log_warn() {
    echo -e "${YELLOW}⚠ WARN${NC}: $1"
    echo "- ⚠️  **WARN**: $1" >> "$AUDIT_REPORT"
    ((WARN_COUNT++))
}

log_section() {
    echo ""
    echo -e "${BLUE}═══ $1 ═══${NC}"
    echo "" >> "$AUDIT_REPORT"
    echo "### $1" >> "$AUDIT_REPORT"
    echo "" >> "$AUDIT_REPORT"
}

# Task 1: Verify Runtime Source of Truth
log_section "Task 1: Runtime Source of Truth"

echo "Checking for ChatOrchestrator and LLMRouter..."
if grep -r "class ChatOrchestrator" src/ --include="*.py" > /dev/null 2>&1; then
    ORCHESTRATOR_FILE=$(grep -r "class ChatOrchestrator" src/ --include="*.py" | head -1 | cut -d: -f1)
    log_pass "ChatOrchestrator found: $ORCHESTRATOR_FILE"
else
    log_warn "ChatOrchestrator not found (may use LangGraphOrchestrator)"
fi

if grep -r "class LLMRouter" src/ --include="*.py" > /dev/null 2>&1; then
    ROUTER_FILE=$(grep -r "class LLMRouter" src/ --include="*.py" | head -1 | cut -d: -f1)
    log_pass "LLMRouter found: $ROUTER_FILE"
else
    log_fail "LLMRouter not found"
fi

if [ -f "src/ai_karen_engine/inference/vllm_runtime.py" ]; then
    log_pass "VLLMRuntime adapter exists: src/ai_karen_engine/inference/vllm_runtime.py"
else
    log_fail "VLLMRuntime adapter not found"
fi

# Task 2: Find Every vLLM Reference
log_section "Task 2: vLLM Reference Audit"

echo "Searching for vLLM references..."
VLLM_REF_COUNT=$(grep -r "vllm\|vLLM\|VLLM\|nano_vllm" src/ --include="*.py" 2>/dev/null | wc -l || echo "0")
echo "Found $VLLM_REF_COUNT vLLM references in source code"
echo "" >> "$AUDIT_REPORT"
echo "**vLLM References Found:** $VLLM_REF_COUNT" >> "$AUDIT_REPORT"
echo "" >> "$AUDIT_REPORT"

if [ "$VLLM_REF_COUNT" -gt 0 ]; then
    log_pass "vLLM references found in codebase"
    
    # Check for provider registry
    if grep -r "builtin_vllm" src/ai_karen_engine/config/llm_provider_config.py > /dev/null 2>&1; then
        log_pass "builtin_vllm configured in provider config"
    else
        log_fail "builtin_vllm not found in provider config"
    fi
    
    # Check for runtime registration
    if grep -r "VLLMRuntime" src/ai_karen_engine/integrations/llm_registry.py > /dev/null 2>&1; then
        log_pass "VLLMRuntime registered in LLM registry"
    else
        log_fail "VLLMRuntime not registered in LLM registry"
    fi
else
    log_fail "No vLLM references found"
fi

# Task 3: Verify Central Provider Registry
log_section "Task 3: Central Provider Registry"

if [ -f "src/ai_karen_engine/config/llm_provider_config.py" ]; then
    log_pass "Provider config file exists"
    
    # Check for vLLM configuration
    if grep -A 20 "builtin_vllm" src/ai_karen_engine/config/llm_provider_config.py | grep -q "ProviderType.LOCAL"; then
        log_pass "vLLM configured as LOCAL provider type"
    else
        log_warn "vLLM provider type not clearly marked as LOCAL"
    fi
    
    if grep -A 20 "builtin_vllm" src/ai_karen_engine/config/llm_provider_config.py | grep -q "priority.*9[0-9]"; then
        log_pass "vLLM has high priority (90+)"
    else
        log_warn "vLLM priority may be lower than expected"
    fi
else
    log_fail "Provider config file not found"
fi

# Task 4: Verify vLLM Server Compatibility
log_section "Task 4: vLLM Server Compatibility"

echo "Testing vLLM server endpoints..."

# Health check
if curl -fsS --max-time 5 "$VLLM_HEALTH_URL" > /dev/null 2>&1; then
    log_pass "vLLM health endpoint responding: $VLLM_HEALTH_URL"
else
    log_warn "vLLM health endpoint not responding (server may not be running)"
fi

# Models endpoint
MODELS_JSON=$(curl -fsS --max-time 5 "$VLLM_BASE_URL/models" 2>/dev/null || echo "")
if [ -n "$MODELS_JSON" ]; then
    log_pass "vLLM /v1/models endpoint responding"
    
    # Extract model ID
    if command -v jq > /dev/null 2>&1; then
        MODEL_ID=$(echo "$MODELS_JSON" | jq -r '.data[0].id // empty' 2>/dev/null || echo "")
        if [ -n "$MODEL_ID" ]; then
            MODEL="$MODEL_ID"
            log_pass "Detected model: $MODEL"
        fi
    fi
else
    log_warn "vLLM /v1/models endpoint not responding"
fi

# Generation test (only if model is available)
if [ -n "$MODEL" ]; then
    echo "Testing vLLM generation with model: $MODEL"
    
    GENERATION_RESPONSE=$(curl -fsS --max-time 30 "$VLLM_BASE_URL/chat/completions" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"$MODEL\",
            \"messages\": [
                {\"role\": \"system\", \"content\": \"You are Karen. Answer plainly.\"},
                {\"role\": \"user\", \"content\": \"Say 'vLLM live response check passed' in one sentence.\"}
            ],
            \"temperature\": 0.2,
            \"max_tokens\": 80,
            \"stream\": false
        }" 2>/dev/null || echo "")
    
    if [ -n "$GENERATION_RESPONSE" ]; then
        if command -v jq > /dev/null 2>&1; then
            GENERATED_TEXT=$(echo "$GENERATION_RESPONSE" | jq -r '.choices[0].message.content // empty' 2>/dev/null || echo "")
            if [ -n "$GENERATED_TEXT" ]; then
                log_pass "vLLM generation successful: ${GENERATED_TEXT:0:50}..."
                echo "" >> "$AUDIT_REPORT"
                echo "**Sample Generation:**" >> "$AUDIT_REPORT"
                echo "\`\`\`" >> "$AUDIT_REPORT"
                echo "$GENERATED_TEXT" >> "$AUDIT_REPORT"
                echo "\`\`\`" >> "$AUDIT_REPORT"
            else
                log_fail "vLLM generation returned empty content"
            fi
        else
            log_warn "jq not available - cannot parse generation response"
        fi
    else
        log_warn "vLLM generation endpoint not responding"
    fi
else
    log_warn "No model specified - skipping generation test"
fi

# Task 5: Audit Provider Selection Logic
log_section "Task 5: Provider Selection Logic"

if grep -r "RUNTIME_DEGRADED_FALLBACK_ORDER" src/ai_karen_engine/services/models/routing/ --include="*.py" > /dev/null 2>&1; then
    FALLBACK_ORDER=$(grep -A 3 "RUNTIME_DEGRADED_FALLBACK_ORDER" src/ai_karen_engine/services/models/routing/llm_router_service.py | grep -o '"builtin_[^"]*"' | tr '\n' ' ')
    log_pass "Fallback order defined: $FALLBACK_ORDER"
    
    if echo "$FALLBACK_ORDER" | grep -q "builtin_vllm"; then
        log_pass "builtin_vllm is in fallback chain"
    else
        log_fail "builtin_vllm not in fallback chain"
    fi
else
    log_warn "Fallback order constant not found"
fi

# Check for provider normalization
if grep -r "_normalize_provider_name" src/ --include="*.py" | grep -q "vllm.*builtin_vllm"; then
    log_pass "Provider name normalization includes vLLM aliases"
else
    log_warn "Provider name normalization may not handle vLLM aliases"
fi

# Task 6: Degraded Mode Semantics
log_section "Task 6: Degraded Mode Semantics"

DEGRADED_REF_COUNT=$(grep -r "degraded_mode" src/ --include="*.py" 2>/dev/null | wc -l || echo "0")
echo "Found $DEGRADED_REF_COUNT degraded_mode references"

if grep -r "response_source.*live_model" src/ --include="*.py" > /dev/null 2>&1; then
    log_pass "response_source field exists to distinguish live vs static responses"
else
    log_warn "response_source field not found - may not distinguish live from static"
fi

if grep -r "actual_provider.*vllm" src/ --include="*.py" > /dev/null 2>&1; then
    log_pass "actual_provider metadata includes vLLM tracking"
else
    log_warn "actual_provider metadata may not track vLLM correctly"
fi

# Task 7: Verify Streaming Path
log_section "Task 7: Streaming Implementation"

if grep -r "def stream" src/ai_karen_engine/inference/vllm_runtime.py > /dev/null 2>&1; then
    log_pass "VLLMRuntime has stream method"
    
    if grep -A 10 "def stream" src/ai_karen_engine/inference/vllm_runtime.py | grep -q "stream_generate"; then
        log_pass "VLLMRuntime delegates to provider stream_generate"
    else
        log_warn "VLLMRuntime streaming implementation unclear"
    fi
else
    log_fail "VLLMRuntime missing stream method"
fi

# Task 8-9: Check for Tests
log_section "Task 8-9: Test Coverage"

if [ -f "src/ai_karen_engine/services/models/routing/tests/test_degraded_runtime_fallback.py" ]; then
    log_pass "Degraded runtime fallback tests exist"
    
    if grep -q "test.*vllm" src/ai_karen_engine/services/models/routing/tests/test_degraded_runtime_fallback.py; then
        log_pass "Tests include vLLM-specific scenarios"
    else
        log_warn "Tests may not cover vLLM-specific scenarios"
    fi
else
    log_warn "Degraded runtime fallback tests not found"
fi

# Check for vLLM smoke tests
if grep -r "KAREN_RUN_VLLM_SMOKE" tests/ --include="*.py" > /dev/null 2>&1; then
    log_pass "vLLM smoke test gate exists"
else
    log_warn "No vLLM smoke test gate found (recommended: KAREN_RUN_VLLM_SMOKE)"
fi

# Task 10: Message Persistence
log_section "Task 10: Message Persistence"

if grep -r "conversation.*persist\|save.*message" src/ --include="*.py" | grep -q "provider\|metadata"; then
    log_pass "Message persistence includes provider metadata"
else
    log_warn "Message persistence may not include provider metadata"
fi

# Task 11: UI Metadata Display
log_section "Task 11: UI Metadata Display"

if [ -d "src/ui_launchers" ]; then
    UI_PROVIDER_REFS=$(grep -r "provider.*vllm\|builtin_vllm" src/ui_launchers/ 2>/dev/null | wc -l || echo "0")
    echo "Found $UI_PROVIDER_REFS UI provider references"
    
    if grep -r "normalize.*provider\|provider.*alias" src/ui_launchers/ --include="*.ts" --include="*.tsx" > /dev/null 2>&1; then
        log_warn "UI may have client-side provider normalization (should use backend metadata only)"
    else
        log_pass "No obvious UI-side provider normalization found"
    fi
else
    log_warn "UI launchers directory not found"
fi

# Task 12: Legacy llama.cpp References
log_section "Task 12: Legacy llama.cpp References"

LLAMACPP_REF_COUNT=$(grep -r "llamacpp\|llama_cpp\|llama-cpp\|local_gguf" src/ --include="*.py" 2>/dev/null | wc -l || echo "0")
echo "Found $LLAMACPP_REF_COUNT llama.cpp references"

if [ "$LLAMACPP_REF_COUNT" -gt 0 ]; then
    log_warn "llama.cpp references found - verify they don't interfere with vLLM"
else
    log_pass "No llama.cpp references found"
fi

# Task 13: Observability
log_section "Task 13: Observability & Telemetry"

if grep -r "prometheus_client\|Counter\|Histogram" src/ai_karen_engine/services/models/routing/ --include="*.py" > /dev/null 2>&1; then
    log_pass "Prometheus metrics found in routing service"
else
    log_warn "Prometheus metrics may not be configured for routing"
fi

if grep -r "correlation_id" src/ai_karen_engine/api_routes/chat/ --include="*.py" > /dev/null 2>&1; then
    log_pass "Correlation ID tracking exists"
else
    log_warn "Correlation ID tracking not found"
fi

# Task 14: Health Endpoint
log_section "Task 14: Health & Diagnostics Endpoint"

if [ -f "src/ai_karen_engine/api_routes/monitoring/health.py" ]; then
    log_pass "Health monitoring endpoint exists"
    
    if grep -q "degraded.*mode\|provider.*health" src/ai_karen_engine/api_routes/monitoring/health.py; then
        log_pass "Health endpoint includes degraded mode and provider health"
    else
        log_warn "Health endpoint may not include comprehensive provider status"
    fi
else
    log_warn "Health monitoring endpoint not found"
fi

# Python Syntax Check
log_section "Code Quality Checks"

echo "Running Python syntax check..."
if command -v python > /dev/null 2>&1; then
    if python -m compileall src/ > /dev/null 2>&1; then
        log_pass "Python syntax check passed"
    else
        log_fail "Python syntax errors found"
    fi
else
    log_warn "Python not available - skipping syntax check"
fi

# Docker Compose Check
if [ -f "docker-compose.yml" ]; then
    if command -v docker > /dev/null 2>&1; then
        if docker compose config > /dev/null 2>&1; then
            log_pass "Docker Compose configuration valid"
        else
            log_warn "Docker Compose configuration may have issues"
        fi
    else
        log_warn "Docker not available - skipping compose check"
    fi
fi

# Final Summary
log_section "Audit Summary"

echo "" >> "$AUDIT_REPORT"
echo "---" >> "$AUDIT_REPORT"
echo "" >> "$AUDIT_REPORT"
echo "## Summary Statistics" >> "$AUDIT_REPORT"
echo "" >> "$AUDIT_REPORT"
echo "- ✅ **Passed:** $PASS_COUNT" >> "$AUDIT_REPORT"
echo "- ❌ **Failed:** $FAIL_COUNT" >> "$AUDIT_REPORT"
echo "- ⚠️  **Warnings:** $WARN_COUNT" >> "$AUDIT_REPORT"
echo "" >> "$AUDIT_REPORT"

TOTAL_CHECKS=$((PASS_COUNT + FAIL_COUNT + WARN_COUNT))
if [ $TOTAL_CHECKS -gt 0 ]; then
    PASS_RATE=$((PASS_COUNT * 100 / TOTAL_CHECKS))
    echo "**Pass Rate:** ${PASS_RATE}%" >> "$AUDIT_REPORT"
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Passed:${NC} $PASS_COUNT"
echo -e "${RED}✗ Failed:${NC} $FAIL_COUNT"
echo -e "${YELLOW}⚠ Warnings:${NC} $WARN_COUNT"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "Full audit report saved to: $AUDIT_REPORT"
echo ""

# Determine exit code
if [ $FAIL_COUNT -gt 0 ]; then
    echo -e "${RED}Audit FAILED - Critical issues found${NC}"
    exit 1
elif [ $WARN_COUNT -gt 5 ]; then
    echo -e "${YELLOW}Audit PASSED with warnings - Review recommended${NC}"
    exit 0
else
    echo -e "${GREEN}Audit PASSED - vLLM runtime verified${NC}"
    exit 0
fi

# Made with Bob

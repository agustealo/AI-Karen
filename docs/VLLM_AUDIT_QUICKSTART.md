# vLLM Runtime Audit - Quick Start Guide

This guide helps you quickly verify that Karen's vLLM integration is working correctly.

## Prerequisites

1. **vLLM Server Running**
   ```bash
   # Start vLLM server with your model
   python -m vllm.entrypoints.openai.api_server \
     --model your-model-name \
     --host 0.0.0.0 \
     --port 8001
   ```

2. **Karen API Running**
   ```bash
   # Start Karen API
   uvicorn server.app:create_app --factory --host 0.0.0.0 --port 8000
   ```

## Quick Audit (5 minutes)

### Step 1: Run the Audit Script

```bash
cd /path/to/AI-Karen

# Basic audit
./scripts/audit_runtime_vllm.sh

# With custom configuration
KAREN_VLLM_BASE_URL=http://localhost:8001/v1 \
KAREN_VLLM_MODEL=your-model-name \
KAREN_API_URL=http://localhost:8000 \
./scripts/audit_runtime_vllm.sh
```

### Step 2: Review the Report

The script generates a detailed report: `vllm_audit_report_YYYYMMDD_HHMMSS.md`

**Expected Results:**
- ✅ 20+ checks passed
- ⚠️ 0-5 warnings (acceptable)
- ❌ 0 failures (critical)

### Step 3: Manual Verification (Optional)

#### Test vLLM Server Directly

```bash
# Health check
curl http://localhost:8001/health

# List models
curl http://localhost:8001/v1/models | jq

# Test generation
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-name",
    "messages": [
      {"role": "user", "content": "Say hello"}
    ],
    "max_tokens": 50
  }' | jq
```

#### Test Karen API with vLLM

```bash
# Explicit vLLM routing
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Say Karen vLLM test passed",
    "provider": "vllm",
    "model": "auto"
  }' | jq
```

**Verify Response Metadata:**
```json
{
  "metadata": {
    "llm": {
      "actual_provider": "builtin_vllm",
      "runtime_engine": "vllm",
      "response_source": "live_model"
    }
  }
}
```

## Run Smoke Tests

```bash
# Install test dependencies
pip install pytest httpx

# Run vLLM smoke tests
KAREN_RUN_VLLM_SMOKE=1 \
KAREN_VLLM_BASE_URL=http://localhost:8001/v1 \
KAREN_VLLM_MODEL=your-model-name \
pytest tests/integration/test_vllm_smoke.py -v
```

**Expected Output:**
```
tests/integration/test_vllm_smoke.py::TestVLLMServerEndpoints::test_vllm_health_endpoint PASSED
tests/integration/test_vllm_smoke.py::TestVLLMServerEndpoints::test_vllm_models_endpoint PASSED
tests/integration/test_vllm_smoke.py::TestVLLMServerEndpoints::test_vllm_chat_completions_non_streaming PASSED
tests/integration/test_vllm_smoke.py::TestVLLMServerEndpoints::test_vllm_chat_completions_streaming PASSED
tests/integration/test_vllm_smoke.py::TestVLLMRuntimeAdapter::test_vllm_runtime_health_check PASSED
tests/integration/test_vllm_smoke.py::TestVLLMRuntimeAdapter::test_vllm_runtime_generation PASSED
tests/integration/test_vllm_smoke.py::TestVLLMRuntimeAdapter::test_vllm_runtime_streaming PASSED
tests/integration/test_vllm_smoke.py::TestVLLMProviderRegistry::test_vllm_registered_in_registry PASSED
tests/integration/test_vllm_smoke.py::TestVLLMProviderRegistry::test_vllm_provider_metadata PASSED
tests/integration/test_vllm_smoke.py::TestVLLMRouting::test_vllm_in_fallback_chain PASSED
tests/integration/test_vllm_smoke.py::TestVLLMRouting::test_vllm_alias_normalization PASSED
tests/integration/test_vllm_smoke.py::TestVLLMRouting::test_vllm_has_local_priority PASSED

============ 12 passed in 5.23s ============
```

## Troubleshooting

### Issue: vLLM Server Not Responding

**Symptoms:**
- Health check fails
- Audit shows warnings about vLLM endpoints

**Solutions:**
1. Verify vLLM server is running: `curl http://localhost:8001/health`
2. Check vLLM logs for errors
3. Ensure model is loaded: `curl http://localhost:8001/v1/models | jq`

### Issue: Karen Falls Back to Transformers

**Symptoms:**
- Metadata shows `runtime_engine: "transformers"` instead of `"vllm"`
- Response includes fallback warnings

**Solutions:**
1. Check `VLLM_BASE_URL` environment variable
2. Verify vLLM server is accessible from Karen container
3. Check Karen logs for connection errors

### Issue: Static Degraded Response

**Symptoms:**
- Response contains "degraded mode" text
- Metadata shows `response_source: "emergency_static"`

**Solutions:**
1. Verify vLLM server can generate text (test directly)
2. Check if model is loaded in vLLM
3. Review Karen logs for provider selection errors

## Pass Criteria

✅ **PASS** - vLLM is properly wired when:

1. vLLM health endpoint responds
2. vLLM generates real text (not static fallback)
3. Karen routes to vLLM when requested
4. Metadata shows `actual_provider: "builtin_vllm"`
5. Metadata shows `response_source: "live_model"`
6. Streaming works (if supported)
7. Messages persist with correct provider metadata

❌ **FAIL** - Critical issues when:

1. vLLM always falls back to Transformers
2. Responses are always static degraded text
3. Metadata shows wrong provider
4. No provider routing occurs

## Next Steps

After passing the audit:

1. **Review Full Documentation**: See `docs/VLLM_RUNTIME_AUDIT.md`
2. **Configure Production**: Set up vLLM with production models
3. **Monitor Performance**: Track latency and throughput metrics
4. **Add Custom Tests**: Extend smoke tests for your use cases

## Support

For issues or questions:
- Review: `docs/VLLM_RUNTIME_AUDIT.md`
- Check logs: `logs/karen_api.log`
- Run diagnostics: `./scripts/audit_runtime_vllm.sh`
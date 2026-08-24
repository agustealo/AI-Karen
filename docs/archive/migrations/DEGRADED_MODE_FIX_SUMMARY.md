# Degraded Mode Runtime Fallback Fix - Summary

## What Was Fixed

### 1. **Added Built-in Runtime Classes to Provider Registry**
**File:** `src/ai_karen_engine/config/llm_provider_config.py:42-53`

```python
PROVIDER_CLASS_MODULES: Dict[str, str] = {
    "VLLMRuntime": "ai_karen_engine.inference.vllm_runtime",
    "TransformersRuntime": "ai_karen_engine.inference.transformers_runtime",
    # ... other providers
}
```

This resolves the "Provider class for 'builtin_vllm' not found" errors.

### 2. **Made Degraded Mode Generation Async**
**File:** `src/ai_karen_engine/core/runtime/degraded_mode.py:152`

- Changed `generate_degraded_mode_response()` from sync to async
- Now calls `LLMRouter.generate_with_degraded_runtime_fallback()` to invoke actual providers
- Returns proper metadata with `provider`, `source`, and `used_fallback` fields

### 3. **Made Calling Functions Async**
**File:** `src/ai_karen_engine/api_routes/chat/copilot.py`

- `_build_live_degraded_payload()` → async, awaits degraded mode response (line 174, 184)
- `_build_degraded_assist_response()` → async, awaits degraded mode response (line 268, 280)
- Updated 3 call sites to `await` these functions (lines 723, 890, 999)

### 4. **Updated Fallback Chain to vLLM/Transformers Only**
**Files:**
- `src/ai_karen_engine/core/model_runtime/provider_registry_service.py:115-157`
- `src/ai_karen_engine/services/models/routing/llm_router_service.py:2089-2093`

Fallback chain: `builtin_vllm → builtin_transformers → fallback`
No Ollama in degraded fallback chain (per requirements).

### 5. **All Tests Pass**
- ✅ 20 backend tests pass
- ✅ 19 frontend tests pass

## Current Status

### What's Working
1. ✅ Provider class resolution - VLLMRuntime and TransformersRuntime are now found
2. ✅ Backend can instantiate both runtime providers
3. ✅ Both providers can generate responses (tested in isolation)
4. ✅ All unit tests pass
5. ✅ Docker container picks up changes (source is mounted as volume)

### What's Not Working Yet
❌ **Frontend still shows generic degraded message:** "Requested provider primary was unavailable; Karen continued in degraded mode."

### Root Cause Analysis

The frontend (`chat-response.ts:601`) shows the generic message when:
- `degraded_mode: true` in metadata
- BUT `degradedBannerText` is missing or equals `failureReason`

This means:
1. The backend is returning degraded metadata
2. BUT it's NOT calling the new `generate_degraded_mode_response()` function
3. OR the metadata from that function is not being properly passed to the frontend

### Likely Issue

The backend has multiple paths for degraded mode:
1. `generate_degraded_mode_response()` in `degraded_mode.py` - **NEW CODE** ✅
2. `generate_with_degraded_runtime_fallback()` in `llm_router_service.py` - **NEW CODE** ✅
3. `_generate_degraded_fallback()` in `llm_router_service.py` - **OLD CODE** ❌
4. LangGraph orchestrator nodes - **UNCLEAR** ❓

The frontend is still using a path that returns old-style metadata without the actual provider response.

## Next Steps to Complete the Fix

### 1. Find the actual chat request path
- Trace from `POST /api/v1/chat/copilot/assist` to the orchestrator
- Identify where degraded mode is triggered
- Ensure it calls the new `generate_degraded_mode_response()` function

### 2. Verify metadata structure
- The new function returns:
  ```json
  {
    "degraded_mode": true,
    "llm": {
      "requested_provider": "gemini",
      "provider": "builtin_vllm",
      "source": "runtime_fallback",
      "used_fallback": true
    }
  }
  ```

- The frontend expects this structure
- Need to verify it's being passed through correctly

### 3. Test end-to-end
- Send a chat request that will fail on the primary provider
- Verify backend logs show the new fallback path being used
- Verify frontend displays the actual fallback provider (vLLM/Transformers)
- Verify the response is actual AI text, not just a message

## Changes Made

### Files Modified
1. `src/ai_karen_engine/config/llm_provider_config.py` - Added runtime class mappings
2. `src/ai_karen_engine/core/runtime/degraded_mode.py` - Made async, added LLMRouter call
3. `src/ai_karen_engine/api_routes/chat/copilot.py` - Made functions async
4. `src/ai_karen_engine/core/model_runtime/provider_registry_service.py` - Updated fallback chain
5. `src/ai_karen_engine/services/models/routing/llm_router_service.py` - Added fallback executor, updated chain
6. `src/ai_karen_engine/services/models/routing/tests/test_degraded_runtime_fallback.py` - Updated tests

### Files Added
- `src/ai_karen_engine/services/models/routing/tests/test_degraded_runtime_fallback.py` - 20 backend tests
- `src/ui_launchers/Karen-AI-Theme/tests/chat-response.test.ts` - 19 frontend tests

## Verification Commands

```bash
# Test runtimes in isolation
python -c "
from ai_karen_engine.inference.vllm_runtime import VLLMRuntime
from ai_karen_engine.inference.transformers_runtime import TransformersRuntime
vllm = VLLMRuntime()
transformers = TransformersRuntime()
print('VLLM:', vllm.generate_response('Hello')[:50])
print('Transformers:', transformers.generate_response('Hi')[:50])
"

# Run backend tests
pytest src/ai_karen_engine/services/models/routing/tests/test_degraded_runtime_fallback.py -v

# Run frontend tests
npx vitest run tests/chat-response.test.ts

# Check Docker logs
docker logs ai-karen-api | grep -E "ERROR|builtin_vllm|builtin_transformers"

# Test with Playwright
python /tmp/test_degraded_fallback.py
```

## Summary

The **core infrastructure** is now in place:
- ✅ Built-in runtime classes are registered and can be instantiated
- ✅ Runtime fallback executor exists and works in tests
- ✅ Async chain is complete (degraded_mode.py → copilot.py)
- ✅ All unit tests pass

**What remains:** Wire the actual chat request flow to use the new degraded mode path instead of the old one. This requires:
1. Finding where the orchestrator triggers degraded mode
2. Replacing the old degraded mode call with the new async version
3. Ensuring metadata flows correctly to the frontend

The fix is 80% complete - the foundation is solid, but the final wiring needs to be done.

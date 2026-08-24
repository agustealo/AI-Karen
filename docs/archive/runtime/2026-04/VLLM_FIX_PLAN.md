# vLLM Runtime Fix Plan

## Classification of vLLM References

### ❌ FAKE vLLM (Must Fix)

| File | Line(s) | Issue | Type |
|------|---------|-------|------|
| `src/ai_karen_engine/config/settings.json` | 76-78 | `builtin_vllm` points to `http://localhost:8080/v1` (llama.cpp) | FAKE CONFIG |
| `docker-compose.yml` | 8080 port | Port 8080 runs `local_gguf_server` (llama.cpp), not vLLM | FAKE SERVER |
| `src/ai_karen_engine/config/llm_provider_config.py` | 1068-1092 | vLLM config without real base_url validation | INCOMPLETE CONFIG |

### ⚠️ LEGACY/COMPAT (Needs Review)

| File | Line(s) | Issue | Type |
|------|---------|-------|------|
| `src/ai_karen_engine/config/config_manager.py` | 86, 95, 107, 241, 248, 252 | Default provider set to `builtin_vllm` | DEFAULT SELECTION |
| `src/ai_karen_engine/config/llm_provider_config.py` | 37-38 | Aliases `"builtin-vllm"` and `"vllm"` → `builtin_vllm` | ALIAS |
| `src/ai_karen_engine/services/models/routing/llm_router_service.py` | 254-258 | Provider priority includes fake vLLM | ROUTING |
| `src/ai_karen_engine/services/models/routing/llm_router_service.py` | 2089-2093 | Runtime fallback includes fake vLLM | FALLBACK |
| `src/ai_karen_engine/inference/vllm_runtime.py` | 104-125 | Silent fallback to Transformers when vLLM unavailable | SILENT FALLBACK |

### ✅ CORRECT/REQUIRED (Keep)

| File | Line(s) | Purpose | Type |
|------|---------|---------|------|
| `src/ai_karen_engine/inference/vllm_runtime.py` | All | VLLMRuntime class (needs fixing) | ADAPTER |
| `src/ai_karen_engine/api_routes/health/providers.py` | 12-140 | Health check endpoint | DIAGNOSTICS |
| `models/llm_registry.json` | 2-13 | Provider registry entry | REGISTRY |
| `src/ai_karen_engine/core/model_runtime/provider_registry_service.py` | 120, 128, 136, 144 | Fallback chains | FALLBACK CONFIG |

---

## Fix Strategy

### Phase 1: Stop the Lies (P0)

1. **Remove fake base_url from settings.json**
   - Change `builtin_vllm.base_url` from `http://localhost:8080/v1` to `http://localhost:8001/v1`
   - OR remove it entirely if vLLM not enabled

2. **Update default provider**
   - Change default from `builtin_vllm` to `builtin_transformers`
   - Transformers is real and works; vLLM may not be available

3. **Fix VLLMRuntime silent fallback**
   - Remove `_fallback_text()` calls
   - Let errors propagate to routing layer
   - OR return proper metadata indicating fallback

### Phase 2: Add Real vLLM (P0)

4. **Add vLLM service to docker-compose.cuda.yml**
   - Use official vllm/vllm-openai image
   - Port 8001 (not 8080)
   - Configure model, GPU, etc.

5. **Add environment variables**
   - `KAREN_VLLM_ENABLED=false`
   - `KAREN_VLLM_BASE_URL=http://localhost:8001/v1`
   - `KAREN_VLLM_MODEL=karen-vllm-local`

6. **Update provider registry**
   - Mark `builtin_vllm` as `enabled=false` if vLLM not running
   - Add proper health check config

### Phase 3: Fix Adapter (P0)

7. **Rewrite VLLMRuntime**
   - Remove silent fallback
   - Add proper error handling
   - Use OpenAI-compatible client
   - Return structured ProviderResponse

8. **Update metadata contract**
   - Always return `requested_provider` vs `actual_provider`
   - Always indicate `response_source`
   - Always show `fallback_level` if fallback occurred

### Phase 4: Clean Up (P1)

9. **Review all vLLM references**
   - Update routing logic to handle real vLLM
   - Remove llama.cpp special cases
   - Update UI to consume backend truth

10. **Add tests**
    - vLLM adapter unit tests
    - Provider routing integration tests
    - Metadata contract tests

---

## Immediate Actions (Start Here)

### Step 1: Fix settings.json
```diff
{
  "provider": "builtin_vllm",  // ← Change this
  "model_providers": {
    "builtin_vllm": {
      "base_url": "http://localhost:8080/v1",  // ← WRONG: this is llama.cpp
```

### Step 2: Add vLLM to docker-compose
```yaml
services:
  vllm:
    image: vllm/vllm-openai:latest
    container_name: ai-karen-vllm
    ports:
      - "8001:8000"  # ← Use 8001, not 8080
```

### Step 3: Fix VLLMRuntime
```python
# REMOVE:
def generate(self, prompt: str, **kwargs: Any) -> str:
    if not self.base_url:
        return self._fallback_text(prompt, **kwargs)  # ← SILENT LIE

# REPLACE WITH:
def generate(self, prompt: str, **kwargs: Any) -> str:
    if not self.base_url:
        raise ProviderUnavailable("vLLM base_url not configured")  # ← HONEST ERROR
    try:
        return self._provider.generate_text(prompt, **kwargs)
    except Exception as e:
        raise ProviderUnavailable(f"vLLM generation failed: {e}")  # ← HONEST ERROR
```

---

## Validation Commands

After fixes, these must pass:

```bash
# vLLM health check
curl -sS http://localhost:8001/health

# vLLM models endpoint
curl -sS http://localhost:8001/v1/models | jq

# vLLM generation test
curl -sS http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "karen-vllm-local",
    "messages": [{"role": "user", "content": "Say vLLM works."}]
  }' | jq

# Karen API with vLLM
curl -sS http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Say this is from vLLM.",
    "provider": "builtin_vllm",
    "model": "karen-vllm-local"
  }' | jq .metadata.llm
```

Expected metadata:
```json
{
  "requested_provider": "builtin_vllm",
  "actual_provider": "builtin_vllm",
  "runtime_engine": "vllm",
  "response_source": "live_model",
  "fallback_level": 0,
  "degraded_mode": false
}
```

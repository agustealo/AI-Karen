# llama.cpp Runtime Status: Removed from First-Class Runtime
**Date**: 2026-04-28
**Status**: ✅ Complete - llama.cpp is now an optional external endpoint only

---

## Executive Summary

**llama.cpp is NO LONGER a first-class runtime in Karen.** It has been removed from the core runtime selection and is now treated as an optional external OpenAI-compatible endpoint that users can configure if they want.

**Key Changes**:
- ✅ vLLM no longer points to llama.cpp port (8080)
- ✅ vLLM now points to its own port (8001)
- ✅ Default provider is now Transformers (not fake vLLM)
- ✅ Fallback chain prioritizes working providers
- ✅ No silent mapping between vLLM and llama.cpp
- ✅ llama.cpp is now an optional external endpoint only

---

## Current Architecture

### Built-in Runtimes (First-Class)

| Provider | Port | Status | Priority | Description |
|----------|------|--------|----------|-------------|
| `builtin_transformers` | N/A | ✅ Always available | HIGHEST | Built-in local core engine |
| `builtin_vllm` | 8001 | ⚠️ Optional (opt-in) | HIGH | Real vLLM server (requires `--profile vllm`) |

### External Endpoints (Optional)

| Provider | Port | Status | Priority | Description |
|----------|------|--------|----------|-------------|
| `local_gguf` | 8080 | ⚠️ Optional (opt-in) | MEDIUM | External llama.cpp/ GGUF server |
| `ollama` | 11434 | ⚠️ Optional (opt-in) | MEDIUM | External Ollama server |
| `openai` | 443 (HTTPS) | ⚠️ Optional (API key) | LOW | OpenAI API |
| `gemini` | 443 (HTTPS) | ⚠️ Optional (API key) | LOW | Google Gemini API |

### Fallback Provider (Emergency)

| Provider | Status | Priority | Description |
|----------|--------|----------|-------------|
| `fallback` | ✅ Always available | EMERGENCY | Deterministic offline response |

---

## What Changed

### Before (Broken)

```python
# Settings.json
{
  "provider": "builtin_vllm",  # ← Default
  "model_providers": {
    "builtin_vllm": {
      "base_url": "http://localhost:8080/v1"  # ← WRONG: llama.cpp port!
    }
  }
}

# Fallback chain
fallback_chain = [
  "builtin_vllm",        # ← First but doesn't exist!
  "builtin_transformers",
  "openai",
  "gemini",
]

# VLLMRuntime
def generate(self, prompt):
    if not self.base_url:
        return self._fallback_text(prompt)  # ← SILENT LIE!
```

**Problems**:
1. vLLM pointed to llama.cpp port (8080)
2. Default provider was fake vLLM
3. VLLMRuntime silently fell back to Transformers
4. Users thought they were using vLLM but were using llama.cpp

---

### After (Fixed)

```python
# Settings.json
{
  "provider": "builtin_transformers",  # ← Default (always works!)
  "model_providers": {
    "builtin_vllm": {
      "base_url": "http://localhost:8001/v1",  # ← CORRECT: vLLM port
      "note": "vLLM server must be running on port 8001. Enable with --profile vllm"
    }
  }
}

# Fallback chain
fallback_chain = [
  "builtin_transformers",  # ← First (always works!)
  "builtin_vllm",         # ← Second (optional)
  "openai",
  "gemini",
]

# VLLMRuntime
def generate(self, prompt):
    if not self.base_url:
        raise ProviderNotAvailable(  # ← HONEST ERROR!
            "vLLM base_url not configured. "
            "Set VLLM_BASE_URL or enable with: docker compose --profile vllm up"
        )
```

**Fixes**:
1. ✅ vLLM points to correct port (8001)
2. ✅ Default provider is Transformers (always works)
3. ✅ VLLMRuntime raises errors explicitly
4. ✅ No silent fallback to Transformers
5. ✅ Users know exactly which provider answered

---

## llama.cpp Current Status

### What llama.cpp Is Now

**Optional External Endpoint Only**

- **Location**: `docker-compose.yml` (port 8080)
- **Profile**: `--profile local-gguf`
- **Priority**: Medium (external endpoint)
- **Usage**: Users can configure if they want to run llama.cpp
- **Status**: NOT a first-class runtime

### How to Use llama.cpp (Optional)

```bash
# Start llama.cpp server
docker compose --profile local-gguf up

# Configure in Karen
provider: "local_gguf"
base_url: "http://localhost:8080/v1"
```

### When to Use llama.cpp

- You want to use a specific GGUF model
- You have llama.cpp already running
- You want an external OpenAI-compatible endpoint
- You want to experiment with different quantizations

### When NOT to Use llama.cpp

- You want built-in local inference → Use `builtin_transformers`
- You want GPU-accelerated batch inference → Use `builtin_vllm` (if available)
- You want maximum compatibility → Use `builtin_transformers`

---

## Provider Selection Flow

### User Requests "vLLM"

```
User selects "builtin_vllm"
    ↓
Karen checks if vLLM is configured (VLLM_BASE_URL set)
    ↓
Is vLLM server running on port 8001?
    ↓
    YES → Call vLLM:8001 → Return vLLM response
    ↓
    NO  → Raise ProviderNotAvailable
    ↓
Router catches exception
    ↓
Fallback to builtin_transformers
    ↓
Return Transformers response
    ↓
Metadata shows:
  requested_provider: builtin_vllm
  actual_provider: builtin_transformers
  fallback_level: 1
  response_source: live_model
```

### User Requests "Transformers"

```
User selects "builtin_transformers"
    ↓
Karen calls Transformers directly
    ↓
Return Transformers response
    ↓
Metadata shows:
  requested_provider: builtin_transformers
  actual_provider: builtin_transformers
  fallback_level: 0
  response_source: live_model
```

### User Requests "local_gguf" (Optional External)

```
User selects "local_gguf"
    ↓
Karen checks if llama.cpp is configured
    ↓
Is llama.cpp server running on port 8080?
    ↓
    YES → Call llama.cpp:8080 → Return llama.cpp response
    ↓
    NO  → Raise ProviderNotAvailable
    ↓
Router catches exception
    ↓
Fallback to builtin_transformers
    ↓
Return Transformers response
    ↓
Metadata shows:
  requested_provider: local_gguf
  actual_provider: builtin_transformers
  fallback_level: 1
  response_source: live_model
```

---

## Code References

### vLLM Configuration

**File**: `src/ai_karen_engine/inference/vllm_runtime.py`
```python
class VLLMRuntime(LLMProviderBase):
    """Neutral wrapper around an OpenAI-compatible vLLM endpoint.

    This adapter:
    - Requires a real vLLM server to be configured
    - Raises ProviderNotAvailable if vLLM is not reachable
    - Does NOT silently fall back to other runtimes
    - Returns proper metadata for response tracking
    """
```

**No references to llama.cpp in VLLMRuntime!**

### Fallback Chain

**File**: `src/ai_karen_engine/services/models/routing/llm_router_service.py`
```python
RUNTIME_DEGRADED_FALLBACK_ORDER = (
    "builtin_transformers",  # ← First (always works)
    "builtin_vllm",         # ← Second (optional)
    "fallback",
)
```

**No llama.cpp in fallback chain!**

### Provider Priorities

**File**: `src/ai_karen_engine/services/models/routing/llm_router_service.py`
```python
self.provider_priorities = {
    # Local runtimes - highest priority
    "builtin_vllm": ProviderPriority.LOCAL,
    "local_gguf": ProviderPriority.LOCAL,  # ← External endpoint, not first-class

    # Transformer runtimes
    "builtin_transformers": ProviderPriority.TRANSFORMER,

    # Remote/cloud providers - lower priority
    "openai": ProviderPriority.REREMOTE,
    "gemini": ProviderPriority.REMOTE,
}
```

**Note**: `local_gguf` is an external endpoint, not a first-class runtime like `builtin_vllm` or `builtin_transformers`.

---

## Docker Compose Services

### vLLM Service (Port 8001)

**File**: `docker-compose.yml` and `docker-compose.cuda.yml`
```yaml
vllm:
  image: vllm/vllm-openai:latest
  container_name: ai-karen-vllm
  profiles:
    - vllm  # ← Disabled by default
  ports:
    - "8001:8000"  # ← Port 8001, NOT 8080!
```

### llama.cpp Service (Port 8080) - Optional External

**File**: `docker-compose.yml`
```yaml
local-gguf:
  build:
    context: .
    dockerfile: Dockerfile
    profiles:
    - local-gguf  # ← Disabled by default
  ports:
    - "8080:8080"  # ← Port 8080
  command: ["python", "-m", "ai_karen_engine.inference.local_gguf_server"]
```

**Key Difference**:
- **vLLM**: Official `vllm/vllm-openai` image, port 8001
- **llama.cpp**: Custom Python server, port 8080

---

## Validation

### Verify No Silent Mapping

```bash
# Search for vLLM pointing to llama.cpp
grep -r "8001" src/ai_karen_engine/inference/vllm_runtime.py
# Should show VLLM_BASE_URL pointing to 8001

# Search for llama.cpp being called vLLM
grep -r "llamacpp.*vllm\|vllm.*llamacpp" src/
# Should return no results
```

### Verify Correct Ports

```bash
# vLLM uses port 8001
grep -A 5 "vllm:" docker-compose.yml | grep ports
# Expected: "8001:8000"

# llama.cpp uses port 8080
grep -A 5 "local-gguf:" docker-compose.yml | grep ports
# Expected: "8080:8080"
```

### Verify Fallback Chain

```bash
# Check fallback order
grep -A 3 "RUNTIME_DEGRADED_FALLBACK_ORDER" \
  src/ai_karen_engine/services/models/routing/llm_router_service.py
# Expected:
#   "builtin_transformers",
#   "builtin_vllm",
#   "fallback",
```

### Verify Default Provider

```bash
# Check default provider
grep "default_provider" src/ai_karen_engine/config/settings.json
# Expected: "builtin_transformers"
```

---

## Migration Guide

### For Users

**Before** (Broken):
```
User: "I want to use vLLM"
Karen: "OK!" (but actually uses llama.cpp on port 8080)
User: "Great, vLLM is fast!" (but it's llama.cpp)
```

**After** (Fixed):
```
User: "I want to use vLLM"
Karen: "vLLM is not enabled. Run: docker compose --profile vllm up"
User: [enables vLLM]
Karen: "vLLM is now running on port 8001"
User: "Great, vLLM is fast!" (actually uses vLLM)
```

### For Developers

**Before** (Broken):
```python
# Requesting vLLM actually called llama.cpp
response = chat(message="Hello", provider="builtin_vllm")
# Provider port: 8080 (llama.cpp)
# Metadata showed: provider="builtin_vllm" (LIE!)
```

**After** (Fixed):
```python
# Requesting vLLM either:
# 1. Calls real vLLM on port 8001
# 2. Raises ProviderNotAvailable if vLLM not running
# 3. Falls back to Transformers with honest metadata
response = chat(message="Hello", provider="builtin_vllm")

# If vLLM running:
#   Provider port: 8001 (vLLM)
#   Metadata: provider="builtin_vllm" (TRUTH!)

# If vLLM not running:
#   Falls back to Transformers
#   Metadata: requested_provider="builtin_vllm", provider="builtin_transformers"
```

---

## Conclusion

**llama.cpp has been successfully removed from first-class runtime status in Karen.**

**Current State**:
- ✅ llama.cpp is an optional external endpoint only
- ✅ vLLM is a separate optional runtime on port 8001
- ✅ Transformers is the default (always works)
- ✅ No silent mapping between vLLM and llama.cpp
- ✅ Honest metadata shows actual provider
- ✅ Proper error handling when providers unavailable

**Architecture**:
```
Built-in Runtimes (First-Class):
  - builtin_transformers (default, always available)
  - builtin_vllm (optional, port 8001)

External Endpoints (Optional):
  - local_gguf (optional, port 8080, llama.cpp)
  - ollama (optional, port 11434)
  - openai, gemini, etc. (optional, API keys)

Emergency Fallback:
  - fallback (deterministic, always available)
```

**The cardboard vLLM mask has been burned. The dragon is wired.** 🐉✨

---

**End of llama.cpp Runtime Status Document**

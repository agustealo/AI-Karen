# Provider/Model Runtime Alignment - Investigation Report

## Executive Summary

After comprehensive audit of the codebase, I've determined that the architecture is largely correct. The main issue is that the chat endpoint is not receiving the selected provider/model from the frontend, and the runtime is not properly using the backend provider registry.

## Key Findings

### 1. Backend Architecture ✅ CORRECT

**Endpoint**: `/api/settings/model`
**File**: `src/ai_karen_engine/api_routes/models/settings.py`

The backend already has a comprehensive endpoint that:
- Lists all providers from the provider registry
- Returns discovered models from both static config and discovery service
- Includes health status, configuration status, and runtime options
- Returns the selected and default models per provider

**Provider Data Structure**:
```python
class ModelSettingsResponse(BaseModel):
    providers: List[ProviderPayload]
    selected_provider: str
    selected_model: str
    active_provider: str
    active_model: str
    fallback_hierarchy: List[str]
```

### 2. Frontend Architecture ✅ CORRECT

**Component**: `src/ui_launchers/Karen-AI-Theme/src/components/settings/ModelSettings.tsx`
**Hook**: `src/ui_launchers/Karen-AI-Theme/src/components/chat/const/modelSettings.tsx`

The frontend is correctly:
1. Fetching from `/api/settings/model` (line 196 of ModelSettings.tsx)
2. Normalizing the response using `normalizeModelSettingsResponse`
3. Rendering providers in proper groups: Built-in Runtime, Local Providers, Cloud Providers, Custom Integrations
4. Applying model selection via `applyModelSelection` hook

**Provider Bucket System**:
- `builtIn`: builtin_vllm, builtin_transformers
- `local`: ollama, local_gguf
- `thirdParty`: openai, gemini, anthropic, etc.
- `custom`: user-defined endpoints

### 3. Docker Ollama Configuration ✅ CORRECT

**File**: `docker-compose.yml` (line 660)
```yaml
OLLAMA_BASE_URL: "${OLLAMA_BASE_URL:-http://host.docker.internal:11434}"
```

**Backend usage**: `src/ai_karen_engine/config/llm_provider_config.py` (line 33)
```python
DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
```

This is correctly reading from the environment variable and using `host.docker.internal` for Docker access.

### 4. Model Selection Algorithm ✅ CORRECT

**File**: `src/ai_karen_engine/core/model_runtime/model_selection_algorithm.py`

The algorithm already supports user preferences:
- **Step 1**: Checks user preference (provider/model) first
- **Step 2**: Falls back to system defaults (vLLM, Transformers)
- **Step 3**: Registry fallback
- **Step 4**: Hard final fallback

**However**: The chat endpoint is not passing user preferences to the selection algorithm.

### 5. Main Issue ❌ NEEDS FIX

**Problem**: The chat endpoint (`/api/chat/chat`) does not include the selected provider/model in the request, so the model selection algorithm falls back to system defaults instead of using the user's selection.

**Evidence**:
- Chat request only has `model` field (line 150-155 of runtime.py)
- No `provider` field exists
- User preferences are not being read from user settings

## Solution Required

### Fix 1: Add Provider Field to Chat Request

**File**: `src/ai_karen_engine/api_routes/chat/runtime.py`

Add `provider` field to `ChatRequest` model:

```python
class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(...)
    provider: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Selected provider ID (e.g., 'ollama', 'builtin_vllm', 'transformers')"
    )
    model: Optional[str] = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=50,
        description="Model to use for generation (e.g., 'llama3.1', 'gpt-4')"
    )
    # ... rest of fields
```

### Fix 2: Read User Preferences from Settings

**File**: `src/ai_karen_engine/api_routes/chat/runtime.py`

Add a helper to read user's preferred provider/model from settings:

```python
@staticmethod
async def get_user_provider_preferences() -> Dict[str, str]:
    """Get user's preferred provider and model from settings."""
    try:
        from ai_karen_engine.services.formatting.settings_manager import get_settings_manager

        settings = get_settings_manager()
        provider = settings.get_setting("provider")
        model = settings.get_setting("model")

        if provider and model:
            return {"provider": provider, "model": model}

        return {}
    except Exception as e:
        logger.debug(f"Failed to load user preferences: {e}")
        return {}
```

### Fix 3: Pass User Preferences to Orchestrator

**File**: `src/ai_karen_engine/api_routes/chat/runtime.py`

Modify the request building to include user preferences:

```python
def build_orchestrator_request(
    request: ChatRequest,
    user: Dict[str, Any],
    validated_messages: List[Dict[str, Any]],
    response_id: str,
    correlation_id: str,
    session_id: str,
) -> CanonicalChatRequest:
    # ... existing code ...

    # Get user's preferred provider/model from settings
    user_preferences = await ChatRuntimeHelper.get_user_provider_preferences()

    return CanonicalChatRequest(
        request_id=response_id,
        correlation_id=correlation_id,
        tenant_id=str(user.get("tenant_id") or "default"),
        message=flattened_prompt,
        user_id=user["user_id"],
        org_id=str(user.get("tenant_id") or "default"),
        conversation_id=conversation_id,
        session_id=conversation_id,
        message_id=str(uuid.uuid4()),
        streaming=bool(request.stream),
        stream=bool(request.stream),
        include_context=True,
        attachments=[],
        metadata={
            "model": request.model or user_preferences.get("model"),
            "provider": user_preferences.get("provider"),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "messages": validated_messages,
            "response_id": response_id,
        },
    )
```

### Fix 4: Frontend Chat Payload

**File**: `src/ui_launchers/Karen-AI-Theme/src/lib/api.ts`

Update the chat request to include selected provider:

```typescript
interface ChatRequest {
  messages: ChatMessage[];
  provider?: string;  // Add provider field
  model?: string;
  // ... rest of fields
}
```

**File**: `src/ui_launchers/Karen-AI-Theme/src/components/chat/ChatInterface.tsx`

Extract and include provider in chat payload:

```typescript
const sendMessage = async () => {
  const payload = {
    messages: transformedMessages,
    provider: selectedProvider,  // Include selected provider
    model: selectedModel,        // Include selected model
    stream: enableStreaming,
  };

  const response = await apiClient.post<ChatResponse>('/api/chat/chat', payload);
  // ... handle response
};
```

## Verification Steps

After implementing the fix, verify:

1. **Backend Endpoint**: `/api/settings/model` returns correct provider/model data
2. **Frontend Display**: Models & Runtime › Providers shows same options in chat
3. **Provider Selection**: User can select provider/model in chat dropdown
4. **Backend Receives**: Selected provider/model is included in chat request payload
5. **Runtime Respects**: Selected provider is used for execution
6. **Fallback Behavior**: If selected provider is unavailable, falls back according to hierarchy
7. **Metadata Accuracy**: Response metadata shows requested_provider and actual_provider
8. **Docker Ollama**: Works with `http://host.docker.internal:11434`

## Additional Recommendations

1. **Logging**: Add structured logging at key points:
   - `chat_payload_received` - logs requested_provider and requested_model
   - `provider_selection_requested` - logs selection before validation
   - `provider_selection_resolved` - logs actual provider after validation
   - `provider_execution_started` - logs provider being used
   - `provider_fallback_triggered` - logs fallback reason

2. **Metadata Fields**: Ensure response includes:
   ```json
   {
     "requested_provider": "ollama",
     "requested_model": "llama3.1",
     "actual_provider": "ollama",
     "actual_model": "llama3.1",
     "runtime_engine": "ollama",
     "fallback_level": 0,
     "degraded_mode": false,
     "degradation_reason": null,
     "response_source": "provider_selected"
   }
   ```

3. **Health Checks**: Ensure provider health is checked before selection
4. **Graceful Degradation**: If all selected providers fail, show honest error with fallback explanation

## Conclusion

The core architecture is sound:
- ✅ Backend provider registry is centralized
- ✅ Frontend correctly consumes backend data
- ✅ Docker Ollama config is correct
- ✅ Model selection algorithm supports user preferences

**The fix is straightforward**: Ensure the chat endpoint receives and uses the selected provider/model from the frontend, which will make the entire system have a single source of truth for provider/model configuration.

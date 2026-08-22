# URGENT FIX: Ollama "Legacy Runtime" Error

## Problem

Users are seeing this error when using Ollama:
```
A legacy runtime was requested. Core llama.cpp/Ollama aliases are no longer 
normalized into local_gguf. Configure that service as an explicit external endpoint.
```

Additionally, the system freezes before refreshing to login, and prompts fail to process.

## Root Cause

**File:** `src/ui_launchers/Karen-AI-Theme/src/lib/chat-response.ts`  
**Lines:** 140-150

The UI has a hardcoded list of "legacy" providers that includes `'ollama'`:

```typescript
const LEGACY_CORE_RUNTIME_ALIASES = new Set([
  'ollama',           // ❌ THIS IS THE PROBLEM
  'llamacpp',
  'llama_cpp',
  'llama-cpp',
  'llama.cpp',
  'llama cpp',
  'llama',
  'llamacpp_optimized',
  'llama-cpp-optimized',
]);
```

When the backend returns `provider: "ollama"`, the UI's `isLegacyRuntimeProvider()` function (line 251-255) detects it as "legacy" and shows the error message instead of processing the response.

## Solution

### Option 1: Remove Ollama from Legacy List (RECOMMENDED)

Ollama is a valid external provider and should NOT be treated as legacy.

**File:** `src/ui_launchers/Karen-AI-Theme/src/lib/chat-response.ts`

```typescript
// BEFORE (Lines 140-150)
const LEGACY_CORE_RUNTIME_ALIASES = new Set([
  'ollama',           // ❌ Remove this
  'llamacpp',
  'llama_cpp',
  'llama-cpp',
  'llama.cpp',
  'llama cpp',
  'llama',
  'llamacpp_optimized',
  'llama-cpp-optimized',
]);

// AFTER
const LEGACY_CORE_RUNTIME_ALIASES = new Set([
  // 'ollama' removed - it's a valid external provider
  'llamacpp',
  'llama_cpp',
  'llama-cpp',
  'llama.cpp',
  'llama cpp',
  'llama',
  'llamacpp_optimized',
  'llama-cpp-optimized',
]);
```

### Option 2: Remove All Legacy Checks (AGGRESSIVE)

If llama.cpp is also a valid provider, remove the entire legacy check:

```typescript
// Comment out or remove the entire set
const LEGACY_CORE_RUNTIME_ALIASES = new Set([
  // Legacy runtime checks disabled - all providers are valid
]);
```

Then update `isLegacyRuntimeProvider()` to always return false:

```typescript
export const isLegacyRuntimeProvider = (provider?: string | null): boolean => {
  return false; // All providers are valid
};
```

## Implementation Steps

### Step 1: Edit the UI File

```bash
# Open the file
nano src/ui_launchers/Karen-AI-Theme/src/lib/chat-response.ts

# Or use your preferred editor
code src/ui_launchers/Karen-AI-Theme/src/lib/chat-response.ts
```

### Step 2: Apply the Fix

Remove `'ollama',` from line 141 in the `LEGACY_CORE_RUNTIME_ALIASES` set.

### Step 3: Rebuild the UI

```bash
cd src/ui_launchers/Karen-AI-Theme
npm run build
```

### Step 4: Restart the Services

```bash
# If using Docker
docker compose restart web

# If running locally
# Stop the dev server (Ctrl+C) and restart:
npm run dev
```

### Step 5: Test

```bash
# Test with Ollama provider
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "test",
    "provider": "ollama",
    "model": "starcoder:128k"
  }' | jq
```

Expected: No "legacy runtime" error, normal response processing.

## Additional Issue: Login Redirect

The freeze/login redirect issue may be caused by:

1. **Session expiration** - Check if auth tokens are valid
2. **CORS issues** - Verify CORS configuration
3. **WebSocket connection** - Check if streaming connections are working

### Debug Steps

1. **Check browser console:**
   ```
   F12 → Console tab
   Look for errors related to:
   - Authentication
   - CORS
   - WebSocket
   - Network requests
   ```

2. **Check network tab:**
   ```
   F12 → Network tab
   - Look for failed requests
   - Check response status codes
   - Verify auth headers are present
   ```

3. **Check backend logs:**
   ```bash
   # Docker
   docker compose logs api | tail -100
   
   # Local
   tail -100 logs/karen_api.log
   ```

## Verification

After applying the fix, verify:

1. ✅ Ollama requests process normally
2. ✅ No "legacy runtime" error message
3. ✅ Metadata shows correct provider: `"provider": "ollama"`
4. ✅ No UI freeze or login redirect
5. ✅ Responses are generated successfully

## Related Files

- **UI Provider Logic:** `src/ui_launchers/Karen-AI-Theme/src/lib/chat-response.ts`
- **Backend Provider Config:** `src/ai_karen_engine/config/llm_provider_config.py`
- **Backend Registry:** `src/ai_karen_engine/integrations/llm_registry.py`

## Why This Happened

The UI code was written to detect "legacy" providers that were being phased out. However:

1. **Ollama is NOT legacy** - It's a valid, actively supported external provider
2. **UI should not override backend** - Provider validation should happen on the backend
3. **Error message is misleading** - It suggests configuration issues when there are none

## Long-term Fix

Remove UI-side provider validation entirely. The backend should be the single source of truth for:
- Which providers are valid
- Which providers are available
- Which providers are deprecated

The UI should simply display what the backend returns, not second-guess it.

## Quick Fix Script

```bash
#!/bin/bash
# quick_fix_ollama_legacy.sh

FILE="src/ui_launchers/Karen-AI-Theme/src/lib/chat-response.ts"

# Backup original
cp "$FILE" "$FILE.backup"

# Remove 'ollama' from legacy aliases
sed -i "/^  'ollama',$/d" "$FILE"

echo "✅ Fixed! Ollama removed from legacy aliases."
echo "📦 Backup saved to: $FILE.backup"
echo "🔄 Rebuild UI: cd src/ui_launchers/Karen-AI-Theme && npm run build"
```

Usage:
```bash
chmod +x quick_fix_ollama_legacy.sh
./quick_fix_ollama_legacy.sh
```

## Priority

**🔴 CRITICAL** - This blocks all Ollama usage and causes UI freezes.

Implement immediately.

---

**Created:** 2026-04-27  
**Status:** Ready to implement  
**Estimated Time:** 5 minutes
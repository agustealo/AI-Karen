# Ollama Integration Contract

Status: **Canonical integration contract**

Ollama is an optional local model-serving integration for AI KAREN. It is not part of the core runtime and is not required for application startup, readiness, memory, reasoning, AgentMedusa, CORTEX, or extension execution.

## Ownership

KAREN owns:

- request normalization and execution lifecycle;
- CORTEX decisions and runtime policy;
- prompt assembly;
- memory recall and persistence;
- provider/model routing and fallback policy;
- degraded-mode metadata;
- audit and telemetry.

The Ollama adapter owns only:

- translating KAREN generation requests to the Ollama HTTP API;
- Ollama model discovery through `/api/tags`;
- Ollama-specific response parsing;
- adapter health information.

## Enablement

Ollama is fail-closed and disabled by default.

```text
KARI_OLLAMA_ENABLED=false   # default
```

To opt in:

```text
KARI_OLLAMA_ENABLED=true
OLLAMA_BASE_URL=http://localhost:11434
```

For Docker deployments using the optional Compose service, use the `ollama` profile and point the API at the service when appropriate:

```text
docker compose --profile ollama up
OLLAMA_BASE_URL=http://ollama:11434
KARI_OLLAMA_ENABLED=true
```

The provider adapter must not make network requests while disabled.

## Runtime topology

```text
ChatRuntime
  -> canonical provider/model routing
  -> OllamaProvider adapter, only when explicitly enabled/selected
  -> Ollama HTTP API
  -> local model
```

Ollama must never own provider selection, prompt construction, memory, tools, agent orchestration, RBAC, fallback order, or readiness.

## Health and readiness

A disabled or unavailable Ollama instance must not make `/health/live` or `/ready` fail. Provider health belongs to provider/degraded-mode telemetry.

Expected disabled adapter health:

```json
{
  "status": "disabled",
  "provider": "ollama",
  "enabled": false
}
```

## Transitional debt

The current provider configuration monolith still contains legacy Ollama catalog defaults, including a guessed base URL/default model, and the root Compose file still supplies a convenience `OLLAMA_BASE_URL`. These values are transitional only. Runtime safety no longer depends on them because the adapter refuses network activity unless `KARI_OLLAMA_ENABLED=true`.

A follow-up provider-config convergence should:

1. make the catalog entry itself disabled by default;
2. remove the guessed default model;
3. stop inventing an Ollama URL in the provider catalog and API Compose environment;
4. keep the optional Compose `ollama` profile as a deployment convenience only;
5. ensure the UI displays backend provider configuration/health rather than special-casing Ollama.

## Proof

Relevant tests:

```text
tests/unit/providers/test_ollama_optional.py
tests/architecture/test_ollama_optional_adapter_contract.py
```

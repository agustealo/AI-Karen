# Ollama Provider Contract

Status: **Canonical provider contract**

Ollama is a third-party LLM provider that KAREN may connect to through a configured endpoint. That endpoint may be local, remote, hosted, tunneled, or cloud-managed. KAREN must not infer architectural privilege from where the endpoint runs.

Ollama is not a KAREN runtime subsystem, built-in engine, fallback tier, startup dependency, readiness dependency, model owner, or local-first authority.

## Ownership

KAREN's canonical provider/runtime systems own:

- provider registration and configuration;
- provider enablement and availability;
- provider/model selection;
- fallback policy;
- prompt assembly;
- memory recall and persistence;
- CORTEX decisions;
- AgentMedusa orchestration;
- RBAC and policy gates;
- degraded-mode metadata;
- audit and telemetry.

The Ollama provider adapter owns only protocol translation required to use Ollama's API:

- generation requests;
- model discovery;
- response parsing;
- provider-specific health calls.

This is the same boundary expected of any third-party provider adapter.

## Configuration

Ollama must be configured through the same provider configuration path used by other third-party providers. There is no Ollama-specific runtime enablement gate.

A configured endpoint may be local:

```text
provider: ollama
base_url: http://localhost:11434
model: <configured-model>
```

or remote/cloud:

```text
provider: ollama
base_url: https://ollama.example.com
model: <configured-model>
```

The adapter must not invent a host, port, model, priority, routing role, or fallback position when configuration is absent.

## Runtime topology

```text
ChatRuntime
  -> canonical provider/model routing
  -> provider adapter selected from registry/config
  -> Ollama endpoint
```

Ollama must never own provider selection, prompt construction, memory, tools, agent orchestration, RBAC, fallback order, readiness, or deployment policy.

## Local vs cloud

`local` and `cloud` describe deployment topology, not provider authority.

An Ollama endpoint on `localhost` and an Ollama endpoint on a remote host are the same provider contract from KAREN's perspective. Location may contribute to policy metadata such as privacy, latency, cost, or local-first preference, but it must not create a separate Ollama execution path.

## Transitional debt

The live repository still contains legacy system-level Ollama assumptions outside the adapter. They are not canonical and must be removed during provider convergence:

1. `llm_provider_config.py` still creates a guessed Ollama base URL based on Docker/localhost.
2. The same catalog entry classifies Ollama as `ProviderType.LOCAL` even though Ollama may be local or remote/cloud.
3. The catalog hardcodes an Ollama default model.
4. Root Compose still injects an Ollama URL into the API environment and contains an Ollama-specific service profile.
5. `OpenAIProvider` contains provider-name special cases for Ollama/local endpoints when deciding API-key behavior.

The convergence target is provider-neutral configuration: endpoint, authentication requirements, capabilities, health contract, models, and deployment metadata describe the provider. Runtime code must not branch on `provider == "ollama"` except inside an Ollama-specific protocol adapter when the protocol genuinely requires it.

## Proof

Relevant tests:

```text
tests/unit/providers/test_ollama_optional.py
tests/architecture/test_ollama_optional_adapter_contract.py
```

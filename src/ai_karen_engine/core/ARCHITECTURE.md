# Karen Core Architecture: Authority Matrix & Layer Model

> **Status**: CORE-MAP-1 (canonical)
> **Last updated**: 2026-08-23
> **Commit**: cd91763079f38aa7605d7c31a65fed5be1f4cf27

## The Six-Layer Model

Karen's core is organized into six layers. Each layer has a single authority for a
specific responsibility. Every other implementation must become an adapter, a
subordinate, or disappear.

```
1. Intelligence      ── senses  ──→ what is this?
2. Decision          ── decides ──→ what should Karen do?
3. Execution         ── acts    ──→ execute the authorized decision
4. Specialist Engines ── serve  ──→ used by Runtime
5. State             ── retains ──→ memory, recall, governance
6. Platform Kernel   ── governs ──→ security, observability, infra
```

Authority chain for the triangle (Personalization + Adaptive feed into CORTEX):

```
Personalization ─┐
Adaptive ────────┼→ CORTEX → decision
Intelligence ────┘
```

## Authority Matrix

| Domain              | Owns                         | May Consume                                      | Forbidden                          |
|---------------------|------------------------------|----------------------------------------------------|-------------------------------------|
| **Intelligence**    | linguistic analysis, embeddings, ML predictors, task signatures | models, training data | execution, routing decisions |
| **CORTEX**          | intent, execution topology, capability eligibility, routing decision, policy gates, RBAC-informed eligibility | intelligence, adaptive, personalization | provider execution, direct model invocation |
| **Adaptive**        | recommendations, candidate ranking, learning from outcomes | outcomes, user state, intelligence signals | authorization, provider execution |
| **Personalization** | user model, preferences, behavior adaptation, goals | memory evidence, intelligence signals | memory storage, execution |
| **Runtime**         | chat lifecycle, memory recall coordination, prompt/context assembly, provider execution, tools/plugins, streaming, persistence, telemetry | CORTEX | independent decision logic |
| **Model Runtime**   | inference, model loading, provider config | provider config, model artifacts | chat orchestration, routing decisions |
| **Reasoning**       | reasoning strategies (causal, soft, retrieval, graph) | model runtime, cortex context | routing, provider selection |
| **LangGraph**       | graph execution, nodes, edges, checkpointing, HITL, graph state | runtime plan, authorized execution plan | global routing, runtime policy, provider policy, intent classification |
| **Memory**          | storage, lifecycle, episodic/LTM/graph stores | persistence infra | routing, provider selection |
| **NeuroRecall**     | retrieval, ranking, signal extraction | memory stores, intelligence signals | persistence ownership, routing |
| **NeuroVault**       | governance, archive, recovery | memory | everyday recall, routing |
| **Observability**   | metrics, traces, events, emitters | all events | business logic, routing |
| **Security**        | auth, RBAC, policy, secrets | identity, config | UI-only enforcement, provider execution |

## Generation Classification

### Generation A (old generalized framework) — **REMOVE**

- `core/services/` (service registry monolith)
- `core/data_models/` (generic data model namespace)
- `core/echo_core/` (prototype echo/demo code)
- `core/response/` (compatibility fossil — superseded by `runtime/chat_runtime_contract.py`)
- `core/operations/` (metrics/monitoring — belongs in observability)

### Generation B (transitional orchestration) — **CONVERGE**

- `langgraph_orchestrator/decision_engine.py`
- `langgraph_orchestrator/runtime_policy.py`
- legacy runtime helpers
- agent memory mega-services

### Generation C (current canonical) — **PRESERVE**

- `runtime/` — spinal cord
- `cortex/` — decision authority
- `intelligence/` — neural sensing
- `model_runtime/` — inference
- `reasoning/` — reasoning strategies
- `adaptive/` — advisory only
- `personalization/` — advisory/contextual
- `observability/` — metrics/traces
- `security/` — auth/RBAC/policy
- `memory/` — storage/lifecycle
- `neuro_recall/` — retrieval/ranking
- `neuro_vault/` — governance/archive

## Domains to Remove (CORE-PRUNE-1 targets)

```
echo_core/      — prototype/demo, no production imports
response/       — compatibility fossil, runtime contracts supersede
data_models/    — generic namespace, contracts scattered or dead
operations/     — metrics/collection, belongs in observability
```

## Domains to Preserve

```
adaptive/               GOVERNED ADVISOR (shadow mode, recommends not executes)
automation/             KEEPS
cortex/                 DECISION AUTHORITY
errors/                 KEEPS
intelligence/           NERVOUS SYSTEM
langgraph_orchestrator/ GRAPHS ONLY (strip residual decision authority)
logging/                KEEPS
memory/                 STORAGE/LIFECYCLE
model_runtime/          INFERENCE
neuro_recall/           RETRIEVAL/RANKING
neuro_vault/            GOVERNANCE/ARCHIVE
observability/          METRICS/TRACES
personalization/        ADVISORY
reasoning/              REASONING STRATEGIES
runtime/                EXECUTION (spinal cord)
security/               AUTH/RBAC/POLICY
```

## Platform Adapters (not core domains)

These are platform/infrastructure concerns, not core domains. They belong in a
coherent platform boundary, not floating in `core/`:

```
config/supabase/   — adapter/platform behavior (Supabase key migration)
queues/            — task queue infrastructure
realtime/          — realtime event infrastructure
cron/              — scheduling infrastructure
storage/           — artifact/object storage
```

## Import-Boundary Rules (enforced by tests)

The following dependency directions are illegal and enforced by
`tests/architecture/test_import_boundaries.py`:

```
intelligence  ↛ runtime
personalization ↛ runtime execution
adaptive      ↛ provider execution
cortex        ↛ provider execution (cortex may not invoke providers directly)
reasoning     ↛ api routes
langgraph     ↛ provider selection
model_runtime ↛ chat_runtime (model_runtime may not import ChatRuntime)
memory        ↛ cortex execution
observability ↛ business runtime services
core/response ↛ (deleted)
core/data_models ↛ (deleted)
core/operations ↛ (deleted)
core/echo_core ↛ (deleted)
```

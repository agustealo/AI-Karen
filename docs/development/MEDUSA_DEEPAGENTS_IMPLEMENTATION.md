# MEDUSA-DEEP-01: Deep Agents as the research specialist harness

Status: **implementation in review, disabled by default, not consumer ready**.
Baseline: `langchain-ai/deepagents` Python **0.7.28** (MIT, 2026-10-16).
Canonical architecture: `src/ai_karen_engine/core/ARCHITECTURE.md`.

## Decision

Do not replace LangGraph: Deep Agents itself is built on LangChain's
`create_agent` and LangGraph. Karen already has a purpose-built, authorized
`WorkflowRuntime` for deterministic custom graphs, branching, and policy.
Replacing LangGraph with Deep Agents would duplicate the engine it depends on.

Instead, Deep Agents becomes the **opt-in implementation of the existing
Medusa `researcher` specialist**. That replaces ad hoc per-specialist research
tool/prompt/synthesis logic with Deep Agents' planning, context compaction,
ephemeral filesystem, and bounded subagent harness. There remains one Medusa
planner for team-level selection and one trusted specialist registry. The
legacy researcher stays available while the new implementation is proven.

CORTEX decides the topology, RuntimePolicy authorizes scope and budgets,
ChatRuntime owns lifecycle, WorkflowRuntime owns LangGraph, Medusa coordinates
the authorized team, and Deep Agents executes *within one authorized Medusa
specialist stage*. Nothing can override the parent authorized plan.

## Implemented on this branch

- `config/agent_medusa.py`: central,
  `KAREN_MEDUSA_DEEPAGENTS_RESEARCH_ENABLED=false` validated flag.
- `registry.py`: the existing `researcher` registration chooses either
  `karen.agent.researcher.native` or
  `karen.agent.researcher.deepagents`. Never both.
- `registry_factory.py`: the trusted implementation identifier resolves
  `DeepAgentsResearchSpecialist`; accepts a runtime-installed model factory,
  not a client-supplied model string or arbitrary import path.
- `specialists/deepagents_research_specialist.py`: calls the genuine
  `create_deep_agent` public API. Uses Deep Agents' ephemeral `StateBackend`
  and internal `general-purpose` helper. No host filesystem or shell.
  External actions use Karen's `ToolBridge` and
  `ActionExecutionGate`, including policy checks and durable receipts.
- PromptRuntime registers the versioned
  `karen.agent.researcher.deepagents@v1.0.0` prompt contract.
- Shared Medusa `ExecutionBudgetMeter` tracks model calls and authorized
  tools; async timeout and graph recursion limit enforce ceilings. Runtime
  identity, policy decision, specialist ID, session and tenant are checked
  before any Deep Agents import or model access.
- The model is provided by **trusted runtime injection** only; no implicit
  Anthropic/OpenAI model, environment-based provider choice, or deepagents
  memory authority. External LangSmith tracing is disabled for this worker.
- `requirements/deepagents.txt` pins the optional package.
- Tests cover single-registry identity, authorization, runtime injection,
  model and tool budgets, tool receipts and safe terminal results.

## Crucial activation gate: structured tool calling

This branch intentionally **does not automatically turn Deep Agents on**.
Karen's existing `GenerationBridge.invoke` returns text, while Deep Agents
requires a LangChain `BaseChatModel` with **real structured tool-call
messages and `bind_tools` support** to use its planning, filesystem and task
tools. Passing the text-only bridge as a fake tool-calling model would silently
cripple Deep Agents and violate provider provenance.

The canonical ProviderRuntime owner must expose a governed,
tool-call-capable model execution adapter:

1. Resolve the active provider and model using Karen's central registry and
   authorized execution plan. Verify actual tool-calling capability and local
   runtime readiness; reject unsupported models.
2. Convert LangChain `BaseChatModel` messages and bound tool schemas into
   canonical structured generation requests without dropping tool-call metadata.
3. Convert the provider's real tool-call results to LangChain `AIMessage`
   `tool_calls`. Never fabricate tool calls by parsing prose.
4. Preserve model/provider provenance, actual runtime engine, budgets,
   cancellation, telemetry, safe failures and local-first routing.
5. At runtime startup, register this **trusted** factory through
   `get_implementation_factory().register_deepagents_model_factory(...)`.
   The supplied factory is invoked with the already-authorized Medusa
   registration and `SpecialistExecutionContext`, not raw user parameters.
6. Verify local Ollama/vLLM tool calling with the selected model using real
   tool-call smoke tests before enabling the feature flag.

Until those checks pass, the default native researcher remains active. Turning
on the flag without a trusted model factory fails closed and is not a valid
production rollout.

## Capability ownership matrix

| Responsibility | Permanent owner | Deep Agents role |
|---|---|---|
| Intent, execution topology | CORTEX | None |
| Authorization / RBAC / tenant | RuntimePolicy | Consume narrowed plan |
| Provider/model selection & fallback | Karen Runtime | Injected model only |
| Workflow graph (auth/safety/branching) | WorkflowRuntime + LangGraph | Nested LangGraph agent loop only |
| Multi-agent team assignment | Medusa coordinator/planner | None |
| Internal research task planning | Deep Agents | **Owns** |
| Context compaction and file offload | Deep Agents | **Owns within the run** |
| Internal helper delegation | Deep Agents | Bound to parent privileges and budgets |
| External tool execution and receipts | ToolBridge / OutcomeRecorder | Request approved tools only |
| Long-term memory / deletion | Karen canonical Postgres/NeuroVault | No duplicate store |
| Persistent workflow state | Karen-managed checkpointer | Future scoped injection |
| UI and streaming | Canonical ChatRuntime + AG-UI projection | No independent API |

## Overlap and retirement ledger

- `agent_medusa/specialists/researcher_specialist.py`: *active fallback*;
  retire only when Deep Agents is operational and at parity for grounded
  research, citations, tool receipts, degraded failures and latency.
- `agent_medusa/planning/capability_planner.py`: **keep**;
  team selection and deterministic dependency authorization are distinct
  from internal Deep Agents TODO/workspace planning.
- `core/langgraph_orchestrator/`: **keep**; custom graph is necessary for
  broader workflow and policy semantics.
- `agent_medusa/adapters/frameworks/deepagents_adapter.py`: legacy
  MedusaCoordinator facade, **not a real Deep Agents harness**; audit callers
  before removing or collapsing with `native_adapter.py`.
- `agents/adapters/deepagents_adapter.py` and
  `agents/bridges/karen_deepagents_bridge.py`: historical adapter files use
  old Deep Agents API names and fabricated fallback classes. They must not be
  wired into the new runtime. Perform a full source/import/test reference
  audit, then retire or replace their callers; do not mass-delete blindly.
- `agent_medusa/adapters/frameworks/langchain_adapter.py`: compatibility
  adapter to Medusa coordinator only; do not add an alternate LangChain
  agent brain.
- External Open WebUI runtime: **not needed** for these capabilities.

## Proof and phased rollout

**Phase 1 (this PR):** Canonical research specialist swap, runtime guard,
versioned prompt, genuine Deep Agents API, scoped StateBackend, ToolBridge,
model injection seam, optional dependency and tests.

**Phase 2:** Extend canonical provider execution to preserve tool calls and
inject an authorized `BaseChatModel`. Test three active local models for
correct native tool calls, budgets, provider provenance and cancellation.

**Phase 3:** Configure a PostgreSQL-backed LangGraph checkpointer under the
existing storage authority, tenant-specific thread namespace, scoped
retention/deletion and supervised resume. Ephemeral StateBackend remains the
default until this is proven. Do not persist duplicate personal memory files.

**Phase 4:** Deep Agents researcher vs native researcher side-by-side benchmarks
on representative real tasks: grounded research, multi-step planning, context
overflow, cancellation, approval, corrupted tool output, unresponsive local
model, tenant isolation and reliability after restart.

**Phase 5:** Enable in development after explicit capability/readiness proof,
then replace the native researcher by default only after all acceptance tests
pass. Remove old/fake adapter paths after import/reference audits and
migration coverage. Consumer packaging only after human verification.

### Required commands

```bash
python -m compileall src
pytest tests/agent_medusa/test_deepagents_research_harness.py tests/agent_medusa/test_deepagents_factory_ownership.py -q
pytest tests/agent_medusa/ -q
ruff check src tests
mypy src
docker compose config
```

Optional real-SDK smoke in an isolated environment:

```bash
python -m pip install -r requirements/deepagents.txt
pytest tests/agent_medusa/test_deepagents_sdk_compatibility.py -q
```

**A merged PR is not proof that local tool-calling support exists.**
The default-off flag remains a release safety gate until runtime-model and
real-worker tests are green, not merely mocked.

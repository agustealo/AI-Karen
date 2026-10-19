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

The canonical provider execution authority now exposes a first
structured tool-call adapter. The remaining **activation proof** requires:

1. Verify actual tool-calling capability and registered model inventory in
   Ollama/vLLM/LM Studio. Do not trust model-name heuristics.
2. Complete focused CI, local model tool-call, nested subagent and cancellation
   smoke tests against the pinned Deep Agents release.
3. Prove parent/child token, model-call, duration and tool budgets; audit all
   external actions and receipts under the current tenant and policy.
4. Verify model/provider provenance, actual runtime engine, stop/interruption
   behavior, telemetry, prompt contracts, and no hidden external traffic.
5. Exercise restart/resume after a Karen-authorized durable checkpointer exists.
   Until then this worker is explicitly ephemeral.

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

**Phase 1 (implemented, verification pending):** Canonical research
specialist swap, runtime guard, versioned prompt, genuine Deep Agents API,
scoped StateBackend, ToolBridge, model injection seam, optional dependency,
tests and runtime Deep Agents-first dispatch for authorized multi-agent
topology without an explicit workflow ID. Direct chat stays direct. Explicit
named workflows stay with Karen's custom LangGraph orchestrator. No shadow
graph launcher is installed.

**Phase 2 (implemented, verification pending):** Canonical provider
execution now retains structured OpenAI-compatible tool calls, validates
provider-emitted tool names/arguments, and maps messages through
`core/model_runtime/structured_tool_chat_model.py`, an explicit
`BaseChatModel` adapter. WorkflowRuntime registers this trusted factory at
its execution boundary and passes preferred model/provider hints through the
Medusa specialist context. The factory only accepts a healthy, capability-
matched registered provider/model with confirmed inventory. **Real local tool
calling still requires the live-model smoke gates** before activation.

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

**A successful compile or merged PR is not proof that the actual selected
local model emitted valid tool calls or that every worker path is ready.**
The default-off flag remains a release safety gate until runtime-model and
real-worker tests are green, not merely mocked.


## Updated execution priority: Deep Agents-first, LangGraph exceptionally

`ChatRuntime` continues selecting the authorized topology with CORTEX and
RuntimePolicy. For a request whose authorized topology is `multi_agent`,
which explicitly requires agent delegation and does not identify a named
workflow, `WorkflowRuntime` now routes directly to the existing
`MedusaCoordinator` rather than running a separate outer LangGraph workflow.
Medusa uses its already-trusted specialist registry, run manager, task budget,
tool gate and response assembler; the `researcher` implementation delegates
the *internal* task plan to Deep Agents. Deep Agents internally uses LangGraph.

Explicit `workflow_id` plans, or plans outside the authorized multi-agent
topology, continue through the existing custom LangGraph `WorkflowRuntime`
or non-graph chat branches. This avoids a second graph of orchestration
wrapping the agent harness when it adds no benefit.

This path remains behind `KAREN_MEDUSA_DEEPAGENTS_RESEARCH_ENABLED=false`
until real tool-call-compatible model tests are passing. When disabled, the
previous graph and native researcher paths stay unchanged. Activating the flag
in an environment with no healthy registered tool-capable model produces a
controlled failure; it never silently selects an external model or substitutes
fabricated tool output.

A verified single Deep Agents specialist response is reused by
`ResponseAssembler` without an additional LLM synthesis call.
Multiple specialist outputs still use the canonical aggregation step.

Additional tests:
```bash
pytest tests/core/runtime/test_deepagents_primary_routing.py -q
pytest tests/core/model_runtime/test_structured_tool_provider_execution.py -q
pytest tests/core/model_runtime/test_structured_tool_chat_model.py -q
pytest tests/agent_medusa/test_deepagents_response_ownership.py -q
```

## Next delivery: Live Medusa events and real SDK proof (2026-10-19)

The Deep Agents-first path now relays observed Medusa progress through the
existing canonical chat event contract, not through a duplicate agent API.
`WorkflowRuntime.stream` attaches a **per-request** sink to its own
`MedusaCoordinator` instance, reads the sink concurrently with the run, and
projects only event types with verified correlation identity:

- `AGENT_STARTED` / `AGENT_COMPLETED` / `AGENT_FAILED` ->
  `agent_step` with `step_id`, `agent_id`, and actual status.
- `TOOL_CALL_STARTED` / `TOOL_CALL_COMPLETED` / `TOOL_CALL_FAILED` ->
  `tool` with `tool_call_id`, tool name, step/agent IDs, and phase.
- Tool arguments, results, internal event metadata, and raw error details are
  **not** forwarded. Unknown events and cross-correlation events are dropped.
- Unexpected progress buffer overflow fails the run's visible stream; it is
  never reported as a successful complete answer.
- If the chat stream closes, the pending Medusa execution task is cancelled.
  Canonical `ChatRuntime` still owns the terminal `COMPLETE`/`ERROR` event.
- `ToolBridge` now emits a **single stable actual tool-call ID** and matching
  correlation on start and terminal events; it does not invent tool success.

New tests prove an observed event timeline, identity isolation, redaction,
cancellation, and no fake success after a worker error.

The **existing** `.github/workflows/medusa-core-ci.yml` now contains
`Deep Agents Real SDK Compatibility`. It installs the pinned
`requirements/deepagents.txt`, runs the *actual SDK* graph smoke and focused
governed runner tests. Its success is a required dependency of the existing
final validation job. This is not a new GitHub Actions workflow.

The feature flag remains off until the real SDK check and real local
tool-calling model smoke (Ollama/vLLM/LM Studio as applicable) pass, together
with approval, cancellation, multi-agent budget, tenant, durability and human
UX acceptance. No packaging before human consumer-readiness verification.


## AG-UI as a first-class Deep Agents consumer

AG-UI is the transport projection of the **existing** Karen runtime, not an
alternate executor. PR #494 owns the protocol, HTTP/SSE endpoint, and browser
integration. This PR owns the upstream authoritative events.

Deep Agents 0.7+ no longer enables todo planning by default. Our researcher
now explicitly injects `TodoListMiddleware` so a *real* `write_todos` call
can produce observed planning events. A shared `ModelBudgetCallback` also
tracks actual SDK `write_todos` and `task` tool invocation boundaries,
without exposing their inputs, outputs or private error details. These events
are allowlisted through Medusa's per-run emitter and WorkflowRuntime's
canonical `agent_step` chunks. The run ID for a delegated task is the SDK
callback run ID, not a synthetic child identity.

The downstream AG-UI projector maps verified `agent_step` to structured
`ACTIVITY_SNAPSHOT`. Actual `task` callbacks become native
`SUBAGENT_STARTED`, `SUBAGENT_FINISHED`, or `SUBAGENT_ERROR`. Real
ToolBridge invocations remain `TOOL_CALL_START/END` with unchanged tool-call
identity and a separate acknowledged result receipt. No AG-UI component may
select a model, grant a tool permission, fabricate a saved checkpoint, or
turn a partial streamed response into a completed run.

Important deployment distinction: the Deep Agents **execution** switch
`KAREN_MEDUSA_DEEPAGENTS_RESEARCH_ENABLED` and the AG-UI **transport**
switch `KARI_ENABLE_AG_UI_BRIDGE` are separate centralized, default-off
features. Enabling the first does not implicitly expose the second.
Karen's legacy UI can still render canonical `agent_step`/`tool` events.

Durable checkpoints and replay must use Karen's canonical tenant-scoped
persistence authority. No ephemeral Deep Agents `StateBackend` should be
presented as a durable saved workflow. Before enabling restart/resume, prove
checkpoint restoration, RBAC, tenant isolation, version migration and
correlation-preserving AG-UI replay from recorded events.

### Additional proof

```bash
pytest tests/agent_medusa/test_deepagents_research_harness.py -q
pytest tests/core/runtime/test_deepagents_live_activity.py -q
pytest tests/core/runtime/test_deepagents_primary_routing.py -q
```

Cross-branch AG-UI tests live with the transport owner in PR #494 and must
pass after integration; mocked callback tests are not evidence a live local
model actually calls the planner or task tool.


## Real local tool-call activation proof (October 19, 2026)

This branch adds `scripts/deepagents_live_tool_smoke.py`, a **genuine
model-facing, read-only** tool-call and continuation test. It reuses the
existing `scripts/beta_live_model_smoke.py` operator target and HTTP
helpers rather than introducing another provider configuration source.
It requires an explicit `BETA_MODEL_PROVIDER`, `BETA_MODEL_NAME`,
and beta-local `BETA_MODEL_BASE_URL`. No default or first-available
model is accepted.

The proof first requests one declared `karen_readonly_probe` function,
checks that the backend returned an **actual OpenAI-compatible
`message.tool_calls` record** with a provider-issued call ID, the
correct function and nonce-preserving JSON arguments. It does not parse
model prose or execute the tool. It supplies a controlled tool-role reply
to the model and requires an exact acknowledgement, proving native
tool-call continuation. Unexpected model switching, invalid payloads,
external endpoints and malformed replies fail closed. Only a sanitized
success/failure summary is printed.

The existing self-hosted
`.github/workflows/beta-live-model-smoke.yml` runs this step when the
beta operator explicitly sets repository/environment variable
`BETA_DEEPAGENTS_TOOL_CALL_PROOF_ENABLED=true`. Non-loopback private
beta hosts additionally require
`BETA_DEEPAGENTS_TRUST_PRIVATE_HOST=true`, after the operator has
approved the trusted local host. The default beta smoke is unchanged.

**Skipped is not passed.** A green general chat/model smoke, an offline
mocked contract test, or a queued self-hosted workflow does not establish
Deep Agents tool-calling readiness. The default-off Deep Agents feature
must remain off until this live proof and the runtime-selected
`KarenGovernedChatModel` integration smoke have both passed for the
intended local model and provider.

Commands:

```bash
# Offline contracts, no local model required:
pytest tests/core/model_runtime/test_deepagents_live_tool_smoke_contract.py -q

# Actual live local model, only on the approved self-hosted beta worker:
BETA_MODEL_PROVIDER=<registered-local-provider> \
BETA_MODEL_NAME=<verified-tool-model> \
BETA_MODEL_BASE_URL=http://127.0.0.1:11434/v1 \
python scripts/deepagents_live_tool_smoke.py
```

The existing canonical Medusa run ledger is **not yet** a LangGraph
checkpoint saver. Cross-process graph resume and AG-UI replay remain
explicitly disabled/unproven until a governed PostgreSQL checkpointer,
tenant-scoped run-to-thread identity, resume authorization, and
persisted event sequence have passed integration tests. UI preparation
status is not evidence that model execution has begun; only observed
Medusa/Deep Agents events can establish that transition.


## Canonical PostgreSQL checkpoint storage: phase-one implementation

A separate central configuration flag is now registered:

```dotenv
KAREN_MEDUSA_DEEPAGENTS_CHECKPOINT_ENABLED=false
```

The flag can be enabled only with
`KAREN_MEDUSA_DEEPAGENTS_RESEARCH_ENABLED=true` and the **required**
Medusa durable run ledger enabled in fail-closed mode. This is intentional:
a stored graph snapshot is not a separate execution authority.

The forward-only
`supabase/migrations/20261019010000_36_medusa_deepagents_checkpoints.sql`
adds checkpoint and pending-write tables, ties each snapshot to
`agent_medusa_runs (run_id, tenant_id)`, and enforces tenant row-level
security on both tables. It does not create a second database engine.

`agent_medusa/execution/deepagents_checkpoints.py` implements
LangGraph's asynchronous `BaseCheckpointSaver` interface using Karen's
canonical `PostgresEngine` session and tenant transaction scope:
`aget_tuple`, `aput`, `aput_writes`, `alist` and
`adelete_thread`. Its scope is bound to an authorized Medusa
run/user/session/policy and a deterministic opaque thread identity,
never to client-provided tenant or graph configuration. It rejects
pickle serialization formats, unsafe checkpoint identities and
cross-thread reads/deletions.

When checkpointing is enabled, Deep Agents receives this saver rather
than a process-local `MemorySaver` or an automatically creating
PostgreSQL connection. A successful `ainvoke` must also read back a
persisted checkpoint before the specialist can claim durable storage.
Only after that acknowledgement does Medusa emit
`CHECKPOINT_PERSISTED`, and WorkflowRuntime produces a sanitized
status event. The corresponding AG-UI projection in PR #494 maps
that to `CUSTOM(karen.checkpoint)` with
`checkpoint_verified=true` and `resumable=false`.

**This implements durable checkpoint storage wiring, NOT end-to-end
interruption recovery.** We still require a dedicated, authenticated
resume operation that resolves the original tenant/user/session,
policy decision, run, and thread; verifies the run ledger state;
reconciles tool receipts to prevent duplicate side effects; acquires
a safe worker lease; and replays persisted events for AG-UI. A
checkpoint row alone cannot establish that a run is executing or
that it has successfully resumed. Until these proofs exist, AG-UI
must never expose an enabled Resume action.

Remaining release gates for this phase:

- Apply and rollback-test the new migration in a disposable PostgreSQL
  instance with actual row-level security and correct database roles.
- Verify a real pinned Deep Agents graph can save/read checkpoints
  after a process restart, and that corrupt/foreign checkpoints fail.
- Audit encryption-at-rest, secret-bearing graph state, retention,
  deletion, and tenant/user isolation with NeuroVault governance.
- Check idempotent external tool outcomes and interrupted task handling
  before issuing new model/tool actions from restored state.
- Verify cancellation, SSE disconnects, correlation-preserving AG-UI
  activity replay, and no double execution.
- Human UX verification before enabling the flag or packaging a release.

Tests added without requiring a live database:
```bash
pytest tests/agent_medusa/test_deepagents_checkpoint_saver.py -q
pytest tests/agent_medusa/test_deepagents_research_harness.py -q
pytest tests/core/runtime/test_deepagents_live_activity.py -q
```

These are **structural and mocked transport tests**, not PostgreSQL
durability proof. The feature flag remains disabled by default.


## Learning is an execution input, not a competing orchestrator (October 19, 2026)

This branch now wires Karen's **two-speed learning** into Deep Agents,
without moving RuntimePolicy or provider authority into an SDK.

```text
User request
  -> RuntimeEvidenceResolver -> authorized NeuroRecall / user-model evidence
  -> CORTEX intent and capability requirements
  -> Karen Chat/WorkflowRuntime
      -> versioned PromptRuntime memory/continuity assembly
      -> Intelligence ModelOutcomeSignalService (tenant + user + intent)
      -> RuntimePolicy and ModelManager approved inventory
  -> Medusa -> Deep Agents SDK (governed prompt, selected real local model)
  -> canonical provider transport and ToolBridge receipts
  -> canonical outcome and trajectory stores (append-only PostgreSQL)
  -> Intelligence derived evidence on the next authorized request
```

### Fast learning, used during execution

The canonical ChatRuntime already consumes CORTEX-resolved NeuroRecall
evidence before normal direct model execution. The new Deep Agents path
passes this **same** typed CognitiveContext to the already existing
PromptRuntime assembler, after verifying tenant, user, request, policy
and evidence-level scopes. It does not issue its own retrieval or form
a second prompt. Expired or contradicted evidence is excluded and
RuntimePolicy's actual input-token budget is enforced. The SDK sees
the assembled authorized messages; progress/AG-UI see only counts,
provenance and explicit degraded status, never private memory content.

The Intelligence-owned `ModelOutcomeSignalService` projects from
`OutcomeStore.list_for_tenant(tenant_id, user_id=...)`, which is backed by
the existing tenant-RLS PostgreSQL ledger. Evidence reads are timeout
bounded. The result is a versioned advisory snapshot
`model_operational_outcome_v1` scoped to the CORTEX intent, tenant,
user, provider and model.

The conservative model choice path is:

1. RuntimePolicy constraints and **explicit user model choice** are
   authoritative. Never silently substitute a requested model.
2. Provider registry and health/inventory/tool capability are checked.
   Models outside the policy model allowlist never enter learning ranks.
3. If model choice is automatic, baseline is the canonical provider's
   configured default. A verified, sufficient history of **runtime
   completion/failure** generates an advisory candidate only when the baseline shows repeated
   failures and the alternative is materially more reliable.
   **By default this recommendation is shadow-only**, and the registered
   baseline is executed. An independently evaluated routing policy must be
   promoted through Karen's governed policy process before activating
   adaptive model choice. Insufficient samples, staleness, cross-tenant evidence,
   mixed/fallback provenance, storage failures, and cold starts all
   retain the authorized baseline.
4. CORTEX/Intelligence advise; ModelManager alone resolves the
   executable provider/model. Medusa does not reroute the call.
5. The observed model and actual shared Medusa model-call count flow
   back through WorkflowRuntime and ChatRuntime into the canonical
   outcome recorder. Direct-vs-graph and stream-vs-nonstream provenance
   now share typed metadata.

**Operational completion is NOT ground-truth task quality.** This
initial signal can improve operational reliability under repeated
failure, not claim that a model writes better code, makes fewer factual
errors, or has higher verified task success. Those decisions require
task-specific verification and user-feedback evidence, off-policy
evaluation and the ML promotion gate. The learning policy never
grants a permission or changes an active ML model artifact.

### Slow learning and durable predictor evidence

The original `core.intelligence.ml.online_learning` observer retains
its process-local, shadow/test use. The new Intelligence-owned
`core.intelligence.ml.durable_outcomes.GovernedMLLearningEvidence`
provides a **separately scoped durable adapter** for evaluated
predictor evidence using the SAME canonical OutcomeStore.

Migration `20261019020000_37_intelligence_ml_outcome_evidence.sql`
expands the source check on the existing tenant-RLS
`public.outcome_records` table to accept `intelligence.ml` while
keeping `runtime.execution` and `user.feedback` distinct.
The adapter requires an attributed review/held-out evaluation
reference, strict unique append acknowledgement, typed predictor
task/model/feature versions, finite calibrated values, and exact
tenant and user identity. Only **numeric evaluation summaries**
are stored: no raw labels, user memory, prompts, training examples or
arbitrary source metadata.

`load_verified()` rehydrates numeric outcome summaries from scoped
PostgreSQL reads; `build_adaptive_layer()` recomputes candidate
evidence from durable records rather than a stale process cache.
The evidence reference is currently an **attestation from a trusted
evaluation caller**, not independent cryptographic proof of label
correctness. ML promotion remains separately governed by
`MLModelRegistry` and the existing evaluation/promotion service.
The adapter does not backfill old process-memory observations or
automatically create labels; connect evaluated training jobs as
producers only after verifying their label provenance and consent.

### AG-UI integration

The existing PR #494 now supports one allowlisted
`CUSTOM(karen.learning_decision)` projection when *actual* Deep
Agents response metadata includes model-selection source, learning
status/version and number of memory references included. It does not
expose model scores, personal memories, or a claim of learned answer
correctness. A UI can distinguish `baseline_no_learning`,
`learning_operational_reliability_v1`, `explicit_runtime_or_user`,
and degraded/unavailable learning, but cannot invent a recommendation.

### Central settings

The following centrally validated settings are explicit and may be
overridden by environment. They do not enable the Deep Agents
execution flag:

```dotenv
LEARNING_MODEL_ROUTING_SIGNALS_ENABLED=true
LEARNING_MODEL_ROUTING_ADAPTIVE_ENABLED=false
LEARNING_MODEL_ROUTING_MIN_SAMPLES=12
LEARNING_MODEL_ROUTING_HISTORY_LIMIT=500
LEARNING_MODEL_ROUTING_HISTORY_DAYS=90
LEARNING_MODEL_ROUTING_READ_TIMEOUT_SECONDS=0.75
LEARNING_MODEL_ROUTING_MAX_FAILURE_RATE=0.4
LEARNING_MODEL_ROUTING_MIN_RELIABILITY_GAIN=0.2
```

### Proof and remaining activation gates

```bash
pytest tests/core/intelligence/ml/test_model_outcome_signals.py -q
pytest tests/unit/core/intelligence/ml/test_durable_outcomes.py -q
pytest tests/core/runtime/test_deepagents_learning_context.py -q
pytest tests/core/model_runtime/test_structured_tool_chat_model.py -q
pytest tests/core/runtime/test_deepagents_primary_routing.py -q
pytest tests/agent_medusa/test_deepagents_research_harness.py -q
```

These contracts test deterministic evidence ranking, cold start,
negative evidence, exact model override, RuntimePolicy allowlists,
tenant isolation, replay from a new durable adapter, prompt inclusion,
expired/contradicted memory exclusion, and stream/nonstream metadata.
**Mocked tests are not model-quality or live PostgreSQL proof.**

Still required before calling this a proven adaptive improvement:

- Apply/check migration 37 with actual PostgreSQL roles and tenant-RLS
  isolation, plus idempotent evidence re-read across a worker restart.
- Confirm the real local-model tool-call, checkpoint recovery, and
  observed model-call/provenance end-to-end against the chosen provider.
- Connect label-producing training/evaluation jobs with trusted,
  reproducible label evidence, consent and deletion propagation.
- Measure model choices against a fixed no-learning baseline on held-out
  task strata, including corrections, failure rates, costs, latency,
  regressions and model/policy pin overrides.
- Gate promotion of new learning policies using existing
  shadow/off-policy evaluation and MLRegistry governance.
- Exercise actual AG-UI chat/browser flow and preserve user-visible
  memory/privacy preferences. Keep draft PRs until latest-head CI and
  human acceptance pass.


### Shadow routing and independent policy-evaluation gate

The baseline selection remains authoritative until learning produces
**verified task-quality improvement**, not just higher provider completion.
`LEARNING_MODEL_ROUTING_SIGNALS_ENABLED=true` enables consulting and
scoring versioned operational evidence during ordinary execution.
`LEARNING_MODEL_ROUTING_ADAPTIVE_ENABLED=false` leaves proposed model
changes in shadow mode. An observed recommendation produces
`model_selection_source=shadow_operational_recommendation`: Karen still
uses the authorized baseline, and AG-UI must never suggest the alternative
actually ran.

The new `core.intelligence.ml.model_policy_evaluation` **adapts to
Karen's existing OfflinePolicyEvaluator**, not a second optimizer. It
accepts only canonical `PolicyObservation` records for
`DecisionType.MODEL_SELECTION` with exact tenant scope, independent
held-out evaluation or human-review reward receipts, authorized eligible
models, versioned behavior/candidate policies, real logged propensity
distributions and non-duplicated observation IDs. It rejects made-up
propensities and completion-only records as evidence of task quality.

With 100+ eligible observations it delegates IPS, SNIPS, Doubly Robust,
overlap, segment/drift and promotion evaluation to the existing OPE
owner. The result is a **report, not model activation**:
`policy_activated=false`, including when an evaluator declares a
candidate eligible. There is no API here that changes the active
policy/provider/model. A separately governed promotion, reproducible
benchmark, audit and rollback are still required. The adaptive flag is
an operator-controlled technical capability gate, not evidence that
review/authorization has occurred. Keep it off until the promotion
workflow is completed and enforced end-to-end.

```bash
pytest tests/core/intelligence/ml/test_model_policy_evaluation.py -q
pytest tests/core/model_runtime/test_structured_tool_chat_model.py -q
pytest tests/core/runtime/test_deepagents_learning_context.py -q
```

These fixtures prove **gate semantics**, not actual held-out model
improvement. No genuine model-quality lift has yet been established.


### Canonical benchmark-to-learning writeback, atomic and default-off

The **existing** `core.intelligence.ml.evaluation.BenchmarkRunner.run_and_record`
is now the only source of automatic independently checked predictor labels.
It already enforces `TRAINING_EXECUTE` RBAC, the correct tenant-owned
registered candidate predictor, the immutable candidate artifact, actual
canonical corpus tests, and a durable evaluation receipt.

With `LEARNING_VERIFIED_EVALUATION_OUTCOMES_ENABLED=true`, after the
receipt succeeds, the runner projects eligible, correctly attributed
predictor cases into `GovernedMLLearningEvidence` using the canonical
OutcomeStore. It excludes missing/failed/fallback predictions and checks
model/task/version identity. Labels, raw task text, and arbitrary predictor
metadata are never persisted. Case IDs are hashed into evidence references
and each saved row records a versioned numeric correctness/calibration
observation backed by the benchmark receipt.

**Atomicity is required.** The OutcomeStore owner now supports
`save_unique_outcomes_async`: PostgreSQL validates every row in the exact
tenant scope and inserts the whole evaluated batch in one strict
transaction. Duplicate evidence, an unsupported adapter, a database
error, or a failed second insert aborts the entire writeback. There is no
fallback loop of individually committed rows. In-memory storage supports
only the analogous strict contract for unit tests. This prevents a
partially persisted evaluation being mistaken for an entire benchmark.

The feature is disabled until migration 37, live transaction/RLS proof and
human verification are complete:

```dotenv
LEARNING_VERIFIED_EVALUATION_OUTCOMES_ENABLED=false
```

Unlike user self-reports, these labels originate from the canonical
held-out benchmark. They are **predictor-evaluation evidence**, distinct
from generative Deep Agents model selection and task rewards. The new
OPE adapter, trained-predictor candidate promotion, and the
`MLModelRegistry` retain their existing separate owners. No training or
model promotion occurs because a benchmark row was persisted.

Focused proof (test fixtures, not real database execution):

```bash
pytest tests/core/intelligence/ml/test_benchmark_durable_learning.py -q
pytest tests/unit/core/intelligence/ml/test_durable_outcomes.py -q
pytest tests/core/intelligence/ml/test_model_policy_evaluation.py -q
```

Additional live acceptance gates: apply migration 37 in disposable
PostgreSQL; exercise tenant RLS with the app DB role; interrupt a batch
mid-transaction and verify zero visible rows; recreate the training
worker and re-read the same evidence; demonstrate deletion and RBAC
boundaries. Do not enable learning writeback on an untested database.

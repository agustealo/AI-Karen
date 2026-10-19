# KCHAT: Canonical Chat + LangGraph/Medusa → AG-UI → Karen UI

Status: **in progress, development-only, not consumer-ready**.
Owner: canonical ChatRuntime. Updated 2026-10-18.

## Architecture decision

Karen already uses LangGraph under WorkflowRuntime and Agent Medusa under the
canonical execution policy. Do not introduce another orchestrator.

The execution chain remains:

1. Existing Karen React/Next.js UI (ChatInterface, design tokens, navigation).
2. API ingress validates user, tenant, conversation identity.
3. ChatRuntime owns prompt/context, CORTEX policy, provider/model routing,
   memory, tool eligibility, streaming, durable turn persistence and audit.
4. WorkflowRuntime invokes LangGraph only when authorized graph semantics
   are required, and Medusa executes only scoped specialists.
5. A transport adapter projects runtime-confirmed events to AG-UI clients.
6. A frontend view layer displays only events the backend actually emitted.

AG-UI is **not** an agent framework or alternate source of truth.
assistant-ui is a candidate React UI component library, **not** a replacement
for Karen's runtime or conversation storage.

## Repository evidence

- `src/ai_karen_engine/core/runtime/chat_runtime_contract.py`:
  canonical stream types, correlations, request/response identity.
- `src/ai_karen_engine/core/runtime/workflow_runtime.py`:
  authorized LangGraph execution and agent activity.
- `src/ai_karen_engine/agent_medusa/adapters/frameworks/langgraph_adapter.py`:
  Medusa authorization boundaries.
- `src/ai_karen_engine/api_routes/chat/runtime.py`:
  canonical HTTP/SSE ingress and **opt-in** AG-UI compatibility route.
- `src/ui_launchers/Karen-AI-Theme/src/app/api/chat/stream/route.ts`:
  current production browser stream proxy and terminal check.
- `src/ui_launchers/Karen-AI-Theme/src/lib/api.ts`:
  existing client-side canonical event normalization.
- `src/ai_karen_engine/copilotkit/agent_ui_service.py`:
  existing UI bridge with task caches; audit before extending or deleting.

## Delivery decision and boundaries

**Do not bulk-merge Open WebUI.** Use it only as a UX reference. Do not adopt
a Svelte runtime, OWU database, provider router, authentication, or agent engine.

**Deployment switch:** `KARI_ENABLE_AG_UI_BRIDGE=false` by default.
The route refuses requests with HTTP 404 unless the validated central
`RuntimeSettings.features.enable_ag_ui_bridge` configuration enables it.
Do not enable it for a consumer release until end-to-end client and
security verification is complete.

**AG-UI first as an opt-in compatibility seam.** The native Karen chat stream
remains unchanged. The initial adapter accepts authenticated AG-UI run
requests with an explicitly supported subset: text-only final user turn;
the canonical conversation repository supplies all prior history.
Client-provided model tools, state, context and forwarded execution properties
fail closed instead of bypassing Karen policies.

Supported projected events: RUN_STARTED, TEXT_MESSAGE_START/CONTENT/END,
RUN_FINISHED, RUN_ERROR, and explicitly labeled CUSTOM events for known agent
step, tool state, citation, approval, status and warning.
TOOL_CALL_START/END are exposed only when runtime activity provides actual
identifiable start/end events. Tool arguments and raw runtime metadata are
never forwarded blindly. No fabricated progress, state snapshots, approval
outcomes or successes. The adapter intentionally does not claim full AG-UI
1.0 capability coverage.

**assistant-ui second, conditionally.** Prototype its ExternalStoreRuntime
using *existing* Karen message/thread stores and streaming callbacks.
Only adopt the component primitives that improve accessibility and UX
without transferring backend truth to an npm package. Do not install
`@assistant-ui/react-ag-ui` before an AG-UI-compatible browser endpoint,
request/stream parser and full integration tests pass.

## Workstreams and acceptance gates

### KCHAT-01: Canonical ownership and reliability

- Trace React → Next stream proxy → FastAPI → ChatRuntime → WorkflowRuntime
  (only when required) → provider/tools/memory → persistence → SSE → React.
- Remove hardcoded backend fallback addresses **only after** verifying
  deployment/config discovery for all supported dev modes.
- Ensure one terminal outcome and no output splicing after a partial stream.
- Classify CopilotKit task caches as transient projections or duplicates.
- Proof: incomplete streams, retries, approval, persistence and cancellation.

### KCHAT-02: AG-UI compatibility projection

- Use one canonical ChatRuntime stream, one identity scope.
- Emit AG-UI events in a controlled transport projection only.
- Preserve authenticated tenant/user/session; never accept client identity.
- Reject ungoverned client tool/state/context instructions.
- Treat unfinished or interrupted streams as RUN_ERROR, not RUN_FINISHED.
- Test ordering, provenance redaction, and tenant-specific thread derivation.

### KCHAT-03: Browser transport and assistant-ui experiment

- Add a same-origin Next.js AG-UI proxy using configured canonical backend.
- Preserve SSE transport integrity: require real RUN_FINISHED or RUN_ERROR;
  append a transport-specific error on unexpected EOF; no fake completion.
- Ensure session headers and cancellation propagate through the proxy.
- Implement an isolated feature-flagged assistant-ui ExternalStoreRuntime
  proof with existing conversation and message IDs.
- Compare accessibility, keyboard navigation, stream interruptions,
  chat composition, code/citation rendering, performance and history.
- Never enable the experiment by default or package it for consumers without
  tests and explicit acceptance.

### KCHAT-04: Real agent workspace

- Present LangGraph/Medusa state only from authorized runtime events.
- Preserve tool result visibility boundaries, approval scope and audit.
- Use stable step IDs, tool-call IDs, and correlated run/thread IDs.
- A user-visible cancelled, failed, pending and completed state must match
  canonical execution truth. No simulated agent activity.
- Add UI cards only where an existing Karen component is insufficient.

### KCHAT-05: Memory and conversation durability

- Keep PostgreSQL + pgvector/FTS the durable authority; Redis stays
  hot/session coordination. No OWU or CopilotKit memory authority.
- Recover threads and message identity after refresh/interruption.
- Distinguish memory recall failures from persistence failures.
- Test tenant isolation, replay and retry idempotency.

### KCHAT-06: Architecture and release proof

- Run `python -m compileall src`, focused pytest, full `pytest tests/ -q`,
  `ruff check src tests`, `mypy src`, and `docker compose config`.
- Run frontend lint, typecheck, Vitest, Playwright, production build.
- Audit source references before deleting old chat/agent UI layers.
- Record a software bill of materials and licensing review for new npm deps.
- Human-verify functional UX before packaging a consumer release.

## Current branch implementation

- Added `core/runtime/ag_ui_event_projection.py`: canonical-to-AG-UI
  projection with fail-closed terminal behavior and metadata allowlisting.
- Added centrally feature-gated authenticated `POST /api/chat/ag-ui` endpoint to existing
  `api_routes/chat/runtime.py`, still executing only via ChatRuntime.
- Added a configured-backend, same-origin Next.js AG-UI proxy. It verifies
  explicit terminal frames and returns a safe RUN_ERROR on premature EOF or
  socket read interruption instead of inventing completion.
- Added Python unit/ingress and frontend proxy tests for ordering, redaction,
  role constraints, tenant isolation, client instruction rejection and stream
  integrity. CI execution has not yet been verified.
- **Not yet complete:** assistant-ui prototype, full agent workspace
  migration, broader AG-UI state/tool feature coverage, migration cleanup,
  complete client compatibility verification and all CI gates.

### Do not merge before these checks

1. Existing `/api/chat/stream` and UI continue to operate unchanged.
2. The newly introduced code compiles and integration tests pass.
3. Auth + tenant + regression tests prove no bypass or leakage.
4. AG-UI endpoint is kept opt-in and off the consumer route until browser
   integration/compatibility is verified.
5. Existing tests and operational profiles remain green.


## Deep Agents / Medusa event contract (October 19, 2026)

AG-UI is the **projection** of canonical Karen execution, never a second
agent runtime, state store, approval service or planner. The Deep Agents-first
work on PR #497 preserves this shape:

```text
Deep Agents SDK callbacks / governed ToolBridge
    -> Medusa per-run EventEmitter
    -> WorkflowRuntime canonical ChatStreamChunk
    -> ChatRuntime sequence, persistence and terminal policy
    -> AGUIEventProjection (this PR, opt-in)
    -> Same-origin browser transport and Karen UI
```

### Versioned event responsibilities

| Origin | Canonical event | AG-UI projection | Proof |
|---|---|---|---|
| Actual Medusa specialist start/finish/failure | `agent_step` | `ACTIVITY_SNAPSHOT`, `CUSTOM(karen.agent_step)` | Stable run + step IDs, allowlisted status |
| Deep Agents `write_todos` callback | `agent_step` with `source=deepagents`, `activity_kind=plan` | `ACTIVITY_SNAPSHOT(KAREN_DEEPAGENTS_PLAN)` | Genuine opt-in planning middleware and SDK start/end callbacks |
| Deep Agents `task` callback | `agent_step` with real `subagent_run_id` | `ACTIVITY_SNAPSHOT(KAREN_DEEPAGENTS_SUBAGENT)`, real `SUBAGENT_STARTED/FINISHED/ERROR` | One SDK-issued callback run ID, no unobserved finish |
| Governed external ToolBridge | `tool` with real `tool_call_id` and `phase` | `TOOL_CALL_START/END`, `CUSTOM(karen.tool_activity)` | Real ToolBridge invocation/receipt |
| ChatRuntime approved assistant text | `content` | `TEXT_MESSAGE_START/CONTENT/END` | Canonical output only |
| ChatRuntime success/error | `complete` / `error` | `RUN_FINISHED` / `RUN_ERROR` | Exactly one terminal outcome |

The planner is **opt-in** in Deep Agents 0.7+: PR #497 installs
`TodoListMiddleware` for its governed research harness. It does not fake
planning status when the model never calls `write_todos`.

Agentic activity payloads never forward raw model reasoning, filesystem
contents, tool arguments, secret-bearing internal metadata or provider error
details. A completed tool never implies successful external side effects:
ToolBridge's durable result/receipt remains authoritative. AG-UI tool-end
is only a lifecycle boundary. Human approvals are rendered only when Karen
issues a canonical approval event; an AG-UI client cannot mint authorization.

### Durability and replay: still gated

A live AG-UI stream is **not** a durable agent execution record. The canonical
PostgreSQL run ledger and authorized checkpoint system must own lifecycle and
restart/replay decisions. No `STATE_SNAPSHOT`, `STATE_DELTA`, or resumed
subagent events may be invented by the UI or from Redis-local transient
projections. After a reconnect, the runtime must verify tenant/session/run
scope and replay only retained, explicitly recorded events in their original
sequence. Any unsupported resume must fail honestly rather than showing
a fabricated ongoing/completed run.

The default chat UI and `/api/chat/stream` remain in place while these
compatibility contracts are proven and assistant-ui integration remains
feature-gated. PR #494 and PR #497 are **separate owners, not duplicate
AG-UI implementations**; do not copy transport normalization into Medusa.

### Acceptance sequence

1. Focused projection, authenticated ingress and frontend SSE integrity tests
   in PR #494.
2. Pinned real Deep Agents SDK planning/task callbacks, Medusa event stream and
   ToolBridge receipt tests in PR #497.
3. Joint runtime-to-AG-UI smoke after both branches are integrated; verify
   recorded planning, delegation, and tool lifecycle, including fail-closed
   interruption, exact IDs, redaction and cancellation.
4. Real local tool-call model smoke under ProviderRuntime selection.
5. Tenant-scoped checkpoints, reconnection and durable event replay proof
   before advertising resumability. Human acceptance before release.


## Deep Agents canonical checkpoint acknowledgement (October 19, 2026)

PR #497 now implements an opt-in tenant-bound LangGraph PostgreSQL
checkpoint saver backed by Karen's existing database engine, run ledger,
and forward-only migration. A saver being configured is not proof of
durability: the worker reads back its checkpoint before raising canonical
`CHECKPOINT_PERSISTED` activity. Only this observed event projects to
`status` with `checkpoint_verified=true` and `resumable=false`.

This PR's AG-UI layer maps that precise evidence into
`CUSTOM(karen.checkpoint)`, excluding private checkpoint content.
**No AG-UI Resume action is enabled.** The separately authorized
restart and state replay workflow does not yet exist, and the run ledger
alone is not sufficient to restart a Deep Agents graph.

Checks in the AG-UI tests require the read-back acknowledgement,
explicit nonresumability, authenticated user/tenant transport, and
no secret-bearing checkpoint bytes in the wire payload.

Both production feature gates remain independent and disabled:
`KAREN_MEDUSA_DEEPAGENTS_CHECKPOINT_ENABLED=false` in the runtime
and `KARI_ENABLE_AG_UI_BRIDGE=false` for the transport. A successful
beta model smoke is not a substitute for the explicit Deep Agents native
tool-call proof, and no successful checkpoint insert alone proves safe
external action replay, worker claim fencing, or human-authorized resume.


## Operational learning and AG-UI provenance

Deep Agents PR #497 now consumes an authorized CORTEX/NeuroRecall
PromptRuntime context and a tenant/user/task-scoped Intelligence
model-selection advisory. The provider registry, RuntimePolicy and
ModelManager remain the only executability/model authorities; AG-UI
receives only the observed outcome.

The opt-in AG-UI projector in this PR exposes
`CUSTOM(karen.learning_decision)` once per run when the canonical
**content** chunk carries valid Runtime-origin lineage:

```json
{
  "type": "CUSTOM",
  "name": "karen.learning_decision",
  "value": {
    "selection_source": "learning_operational_reliability_v1",
    "learning_signal_status": "ready",
    "learning_signal_version": "model_operational_outcome_v1",
    "learned_context_status": "resolved",
    "included_memory_refs": 2,
    "claim": "operational_evidence_only"
  }
}
```

This is an **illustrative event shape, not a live benchmark result**.
It communicates how a model choice was made, not a reward score, training
promotion, or correctness claim. The custom event refuses unknown
selection sources and clamps included-reference counts. It does not
forward private memory, model ranking internals or error contents.
Client display is secondary to the canonical result; a missing event
is not an invitation to fabricate a "Karen learned" toast.

The old chat transport remains supported while the AG-UI opt-in bridge
is acceptance-tested. Full candidate policy promotion, durable event
replay, and a human-reviewed memory/learning interface remain gated.


### Shadow model-selection status is not an executed model

Intelligence now consults scoped operational model outcomes by default,
but learned routing changes are **shadow-only by default**. The actual
model remains the healthy, RuntimePolicy-approved, registered baseline.

If a real Medusa/Deep Agents response carries
`model_selection_source=shadow_operational_recommendation`, the existing
AG-UI `CUSTOM(karen.learning_decision)` event may report it as an
unpromoted advisory signal. The projection never includes the
unexecuted candidate model name, a claimed measured quality gain or
private memory. It cannot issue or approve a model-promotion action.

The training/evaluation pipeline and new atomic predictor evidence
writeback on PR #497 do not grant AG-UI any ability to alter ModelManager,
MLModelRegistry or the separate adaptive-policy promotion process.

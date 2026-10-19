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
- Added opt-in authenticated `POST /api/chat/ag-ui` endpoint to existing
  `api_routes/chat/runtime.py`, still executing only via ChatRuntime.
- Added unit and ingress tests for ordering, redaction, role constraints,
  tenant isolation, rejection of client instructions and interrupted streams.
- **Not yet complete:** browser AG-UI proxy, assistant-ui prototype, full
  agent workspace migration, migration cleanup, and end-to-end CI verification.

### Do not merge before these checks

1. Existing `/api/chat/stream` and UI continue to operate unchanged.
2. The newly introduced code compiles and integration tests pass.
3. Auth + tenant + regression tests prove no bypass or leakage.
4. AG-UI endpoint is kept opt-in and off the consumer route until browser
   integration/compatibility is verified.
5. Existing tests and operational profiles remain green.

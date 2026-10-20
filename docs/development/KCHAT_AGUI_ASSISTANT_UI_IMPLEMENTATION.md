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
assistant-ui is an **opt-in React UI layer**, **not** a replacement
for Karen's runtime or conversation storage. It remains disabled until
the npm lock, event compatibility and live chat regression gates are green.

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

**assistant-ui second, opt-in.** The official `useAgUiRuntime` + `HttpAgent`
seam now has source-level frontend integration with existing session identity
and history. Unlike an ExternalStoreRuntime translation, it natively
reconstructs AG-UI messages, activities, tool calls and custom data parts.
All backend authority stays unchanged. No interactive capability is enabled
solely because assistant-ui renders a control.

The frontend dependency lock and real authenticated browser checks remain
unverified; the replacement UI therefore remains **default-off and draft**.
Do not use Assistant Cloud as a second store, use another orchestration
runtime, or delete `ChatInterface` until this opt-in is proven equivalent.

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

### AG-UI run identifiers versus durable execution identity

The existing `/api/chat/ag-ui` ingress currently forwards
`AGUIRunRequest.runId` into `AGUIEventProjection`; it is an AG-UI
transport-correlation identifier supplied by the caller. It is not proof that
the canonical runtime issued, persisted, or authorized a run-ledger row with
that identifier. An activity card may display **AG-UI run**, but cannot label
it a verified durable execution, execution receipt, or replay cursor.

Before introducing persisted timelines, map authenticated transport run IDs
to canonical backend-issued execution attempt identifiers, apply tenant and
conversation scoping, and read event sequence and terminal state from the
canonical ledger. Client-supplied identifiers must never authorize cross-run
access or execution recovery.

### Verified persistence owner audit (PR #494)

The canonical `ConversationRuntimeGateway`
(`src/ai_karen_engine/core/runtime/conversation_runtime_gateway.py`)
provides tenant-scoped conversation snapshots, transcript history, and
`persist_completed_turn`. The completed-turn writer persists user and
assistant messages through the existing conversation repository, using
conversation/tenant IDs and request/correlation metadata. It does **not**
expose an ordered history of `agent_step`, `tool`, or
`ACTIVITY_SNAPSHOT` events through this API.

The AG-UI ingress in `api_routes/chat/runtime.py` forwards approved
`ChatStreamChunk` events through `AGUIEventProjection`, which is an
in-memory per-stream serializer. The bridge must not reconstruct a purported
execution timeline from persisted assistant text, transport run IDs, or
transcript message timestamps.

**Integration acceptance before enabling timeline replay:** locate and reuse
the backend-owned persisted execution-event/attempt store, if one exists;
validate its durable monotonic event sequence and tenant/owner authorization;
then add an explicit read-only runtime gateway and authenticated route. If
there is no such store, implement it in the canonical runtime owner rather
than in the chat API adapter, projection, or React. Do not mark replay
supported until restart and cross-tenant denial tests pass.

### Durable timeline contract (not implemented yet)

A transcript-level AG-UI activity card is an observed event, **not** evidence
of a complete, ordered or replayable task history. Do not group cards into a
timeline, mark a run complete from an individual step, or offer Resume until
the canonical run-ledger API proves all of the following:

1. Every event has a server-assigned, immutable event ID and monotonic
   per-run sequence; timestamp is display-only, never an ordering key.
2. The run has a canonical ID, tenant ID, conversation ID, execution attempt
   and verified lifecycle status, with explicit terminal state and source.
3. The authorized read API validates session and tenant scope on every request;
   pagination/cursors remain stable across reconnects and concurrent writes.
4. Replay delivers saved event receipts in ledger sequence, without duplicating
   side effects, collapsing distinct attempts or synthesizing missing events.
5. Truncation, gaps, missing history, partial replay, and retention expiry are
   explicit response states. The UI must label these as incomplete, not as
   an empty or successful run.
6. Tool outcomes and approval decisions link to backend-issued IDs and governed
   receipts; lifecycle finish alone must not imply a successful side effect.
7. Tests cover interrupted streams, concurrent subagents, reconnect and reload,
   tenant isolation, deletion, retention, idempotency, and accessibility.

**Boundary:** PR #494 may render and test approved read-only events, but must
not create a second event ledger. The canonical persisted run-history contract
belongs with the runtime/Medusa owner; frontend timeline grouping remains
feature-gated until its API and integration evidence are supplied.

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


## KCHAT-07: assistant-ui native chat audit and actual integration slice (October 19)

### Audit of source-of-truth boundaries

| Responsibility | Existing owner | New assistant-ui behavior |
| --- | --- | --- |
| User authentication + tenant | Karen Auth + FastAPI | Same-origin authenticated proxy; no client-supplied identity accepted |
| Session/conversation | ConversationRuntimeGateway + existing SessionProvider | Existing conversation UUID is the AG-UI thread id; backend resolves ownership and canonical session through the same gateway |
| Message history | PostgreSQL ConversationRepository | React history adapter reads `GET /api/conversations/{id}`; maps stored user/assistant turns into assistant-ui via `fromAgUiMessages` |
| Streaming & termination | ChatRuntime → AGUIEventProjection → Next proxy | `HttpAgent` + `useAgUiRuntime`; errors reported, no dummy run completion |
| Model selection/fallback | CORTEX, RuntimePolicy, ModelManager | No model setting sent through AG-UI, no SDK provider keys or second router |
| Medusa/Deep Agents | Medusa coordinator & Deep Agents specialist | Observed `ACTIVITY_SNAPSHOT`, subagent, tool activity rendered as named data/tool parts |
| Learning provenance | Intelligence/Runtime | Read-only `karen.learning_decision` with explicit shadow-status wording |
| Checkpoint & resume | Karen durable saver / resumed-run policy | Read-only acknowledgement only; no Resume until restart/idempotence evidence |
| Approvals | Karen ApprovalService / action gate | Read-only `karen.approval_required` notice until governed receipt action adapter is tested |
| Artifacts, citation, advanced UI | Karen runtime artifact/source contracts | Future gated allowlisted data parts only; no arbitrary generative component registry |

### Current verified source edits

- `src/components/chat/assistant-ui/KarenAssistantChat.tsx`: Karen-branded
  assistant-ui primitives, official AG-UI runtime, same-origin `HttpAgent`,
  durable transcript adapter, session-switch adapter, cancellation affordance,
  observed agent-tool-activity and selected runtime-provenance data renderers.
- `src/app/dashboard/page.tsx`: one existing `SessionProvider` wraps either
  the prior ChatInterface or the new assistant-ui surface depending on the
  explicit frontend environment flag; no duplicate mounted chat engines.
- `api_routes/chat/runtime.py`: existing conversation UUIDs are authenticated
  through the canonical ConversationRuntimeGateway before use in AG-UI. It
  reuses the real session ID. Foreign/unknown conversation IDs return 404;
  opaque legacy AG-UI thread IDs preserve their earlier tenant-isolated
  fallback behavior.
- `tests/api_routes/test_chat_ag_ui_transport.py`: scope tests for existing
  conversation identity, valid real session binding and foreign-thread denial.
- `tests/chat/assistant-ui-architecture.test.ts`: source-level guardrails
  for canonical scope, actual AG-UI runtime, feature gating, no fabricated
  resumed actions, and no independent provider selection.

**These are source commits, not an E2E green claim.**

### Explicit opt-in configuration

```dotenv
KARI_ENABLE_AG_UI_BRIDGE=false
NEXT_PUBLIC_KAREN_ASSISTANT_UI_ENABLED=false
```

To try the new frontend in an isolated development environment, first
install and lock **the declared, pinned** `@assistant-ui/react`,
`@assistant-ui/react-ag-ui` and `@ag-ui/client` dependencies. The
development system must have npm registry access to regenerate the
checked-in lockfile. This editing environment did not have registry
access, so `package-lock.json` is **not yet updated**. Do not run or
report `npm ci`/typecheck as green for this head, and do not enable
either feature flag while this is unresolved. No guessed integrity
hashes or incomplete lock entries are acceptable.

From `src/ui_launchers/Karen-AI-Theme` in a network-enabled checkout:

```bash
npm install --package-lock-only --ignore-scripts --no-audit --no-fund
npm ci --no-audit --no-fund
npm run typecheck
npm run lint
npx vitest run tests/chat/assistant-ui-architecture.test.ts
npx vitest run tests/chat/ag-ui-stream-proxy-response.test.ts
```

No consumer/distribution packaging is required.

### Full advanced and proprietary chat implementation roadmap

**KCHAT-08: Verified first-class chat.** Authenticate, load an existing
conversation, send a user turn, observe real partial text and a single
terminal event, reload and reconcile persisted turns. Cover cancellation
and interrupted network (never stitch a second fallback onto a partial
assistant answer). Compare visible behavior against existing ChatInterface.
The imported history currently contains durable text only, not replayable
tool/agent snapshots. A canonical read API must supply authorized event
history before those appear after reload.

**KCHAT-09: Agent execution workspace.** Medusa's exact run/activity IDs
drive plan/todo, subagent lane, delegated tasks, step status and tool
execution timelines in the assistant-ui parts and a collapsible right
rail. Persist and replay only centrally authorized event summaries.
Displayed progress never creates an agent, tool, plan, capability or
state. Treat `TOOL_CALL_END` as a transport lifecycle signal and use
actual ToolBridge receipts for outcomes.

**KCHAT-10: Human review, safely.** Present approvals as actionable only
after a separate scoped GET identifies an unconsumed pending approval
receipt and a governed POST can approve/reject that exact receipt. UI
must disallow duplicate receipts, expired runs, cross-tenant responses and
client-authored tool arguments. Keep the approval notice read-only until
approved action tests exist. Never wire experimental assistant-ui
client-executed tools to privileged Karen plugins.

**KCHAT-11: Durable agent recovery.** Render checkpoint provenance and
available recovery states separately. Provide Resume only after live
PostgreSQL checkpoint read-back through worker restart, replay offset
validation, idempotent tool receipts and backend-issued eligibility.
Cancellation, resume, and new messages may not double-run an acknowledged
side effect. Until these tests pass there is no Resume action.

**KCHAT-12: Karen-proprietary affordances.** Evidence/source viewer with
verified citations, memory recall status and source scope, requested vs
executed provider/model provenance, learning consultation vs shadow
candidate, AG-UI nested subagent activity, plugin permission/receipt
explanations, durable artifacts and rich results. Render verified
structured data with an explicit component allowlist. No arbitrary
untrusted JSON-to-React action runner or provider/model selection from
the browser.

**KCHAT-13: UX/accessibility acceptance.** Keyboard-first composer and
thread switches, focus restoration, screen-reader announcements, truthful
pending/failed/saved states, copy/share/export backed by durable
conversations, syntax/markdown rendering, mobile layout, reduced motion,
long-thread virtualization, agent transparency without overwhelming
first-time users, and performance benchmarking. Preserve Karen's visual
identity rather than adopting an unmodified template or a cloud-hosted
assistant state store.

### Exit criteria

Use the exact-head CI and deterministic live E2E proof, including
`npm ci`, TypeScript, lint, unit/integration and authenticated browser
checks. Backends must prove real Ollama/vLLM tool calls, tenant isolation,
correct model identity, approved tool execution, interrupted SSE and
durable histories. No fake backend fixture counts as a live runtime.
Do not merge PR #494 into main until this is green; PR #497 execution
and checkpoint gates remain separately disabled.


## KCHAT-14: User-centered UX audit and proof matrix (October 19, 2026)

This assessment inspects source on PR #494 at `2af608d1`, not a validated running browser. All visual or behavioral conclusions below are provisional until authenticated desktop/mobile and assistive-technology sessions. It does not imply that PR #497 is merged or deployed.

### Observable deficiencies and owners

| Severity | User experience failure or risk | Evidence in source | Canonical owner and required acceptance |
| --- | --- | --- | --- |
| P0 | The new chat is not consumer-ready | Frontend and AG-UI flags default off; package dependencies are declared without updated lockfile | Frontend integration; regenerate lock from registry, npm clean install, exact-head typecheck/lint/unit/browser tests |
| P0 | Persistence can be mistaken for success | History `append: async () => {}` is a no-op because backend owns persistence; existing source test only checks for adapter text | ChatRuntime/ConversationRuntimeGateway; after each run, reload and prove both turns persisted or present a truthful unsaved/error state. Never report saved from the no-op callback |
| P0 | Stop/retry/reconnect might duplicate or splice responses | Composer Cancel and proxy terminal-integrity handling exist, but no authenticated interrupted-stream browser proof | Runtime plus AG-UI proxy; cancel during tokens, force network EOF, reconnect and verify single run, one terminal state, no fallback text appended |
| P0 | Approval notices cannot accomplish the action | `KarenApprovalNotice` explicitly read-only | ApprovalService/ActionExecutionGate; eligible receipt-backed approve/reject UI only after pending-receipt scope, expiry, idempotency, denial and replay tests |
| P0 | Task execution lacks durable intelligible continuity | Observed activity rendered from live data parts; replay unsupported | Runtime durable run ledger + AG-UI authorized replay; show exact per-run steps after refresh without inventing succeeded actions |
| P1 | Conversation navigation does not scale | Header `select` enumerates sessions with title only | Existing SessionProvider; searchable, keyboard-reachable recent history with grouping, rename and provenance after backend ownership tests |
| P1 | Agent actions are not legible to nontechnical users | Tool fallback exposes tool name and raw status type; plan and subagent activity use the same flat card | AG-UI renderers; human-readable task timeline, clearly distinguished queued/running/failed/finished and receipt-backed outcomes |
| P1 | Helpful responses lack rich inspection | Current assistant message uses `MessagePrimitive.Parts` with custom activity parts, no verified artifact/evidence inspector | Runtime verified citations and artifact APIs; frontend safe allowlisted renderers, inspect provenance and download only backed artifacts |
| P1 | Typography and hierarchy are not proven at real sizes | Message text `text-sm leading-7`, badges `text-xs`, sidebar labels as small as `text-[9px]` | Frontend design system; test 320/375/768/1280px and 200% zoom; readable body and accessible controls, no clipping |
| P1 | User has little explanation of accessible AI capabilities | Empty state only says ask/plan/delegate, while plugins and agents live in separate navigation | Product information architecture; capability cards reflect backend eligibility only, disabled states explain prerequisites |
| P1 | Accessibility is not yet demonstrated | Basic `aria-label` and `role=log` exist; no source evidence of focus recovery, screen-reader or keyboard E2E | Frontend; axe and manual keyboard/screen-reader audit, focus after send, failure, session switch and approval, reduced-motion check |
| P2 | Settings labels express engineering implementation more than user outcomes | Dashboard calls out local-first runtime, separately lists Agents, Tasks, Jobs, Cron Jobs | Product navigation; progressive disclosure: Chat, Activity, Library, Integrations, Settings for regular users; technical controls in Advanced |

### Behavioral acceptance journeys

1. **First run and actual capability discovery:** An authenticated new user sees only callable, authorized capabilities, knows where models/memory/tools come from, and can start a conversation without reading settings. Verify keyboard, narrow mobile and offline/degraded cases.
2. **Conversation persistence:** Start existing conversation, send prompt, receive verified runtime completion, reload the browser and inspect canonical conversation history. Require explicit error state for a persistence failure and no synthetic saved indicator.
3. **Long answer interruption:** Send a streaming request; cancel after partial output and separately force upstream EOF. Assert truthful terminal error/cancel, preserved user-visible partial text as appropriate, no duplicated turn, no stitched fallback, and correlation/provenance availability.
4. **Observed delegation:** Run an authorized multi-step task against real Deep Agents on an allowed local model. Compare rendered plan/tool/subagent IDs and status with server ledger and ToolBridge receipts. Never mistake tool completion for side-effect success.
5. **Consent and denial:** Issue a real pending approval. Test approve, reject, expired, repeated click, stolen/cross-tenant receipt, and page refresh. No client-defined tool execution or silent success.
6. **Recovery and replay:** Restart worker between checkpoint persistence and resolution; ensure no Resume affordance appears until tenant-scoped checkpoint, worker claim fencing, side-effect idempotency and replay proof are positive.
7. **Evidence and artifacts:** Render only canonical cited sources and verified persisted artifacts. Check malicious/untrusted data, empty sources, deleted artifacts and tenant isolation.
8. **Design and accessibility:** Manual desktop and mobile walkthrough, 200% zoom, keyboard-only navigation, screen-reader order/status, reduced motion, high contrast, syntax/markdown/code overflow and very long conversations.

### Experience architecture to validate

Keep a single backend-owned conversation model. The default surface should prioritize a readable transcript, an accessible composer and an optional collapsible task/activity inspector. Present verified context about models, learning, memory, tools and privacy through progressive disclosure; never force dense diagnostic cards into every message. Reserve actions such as approval, retry and resume for explicit runtime-issued eligibility. Keep agent activity and artifacts inside the selected conversation, with a stable way to revisit them. The legacy chat remains the consumer default until the new surface passes equivalent user journeys.

### Exit gate

No feature activation, merge, or user-facing completion claim from source-only assertions, queued CI or simulated model output. Record authenticated browser run links, exact commit SHA, real provider/model, tenant-scoped persistence receipts, accessibility observations, screenshots for responsive typography, and failure-case evidence. Preserve the existing PR ownership: #494 is presentation/AG-UI; #497 is Medusa/Deep Agents; ChatRuntime and governed services stay authoritative.


## Application-wide assistant-ui capability adoption contract

Assistant-ui is Karen's **conversation interaction toolkit**, not a replacement for the application's settings, provider registry, RBAC, privacy screens, or backend. The existing Karen-owned chat/session runtime and canonical AG-UI transport remain the sole integration path. Do not install parallel AI SDK, LangGraph, assistant-cloud persistence, or client-side provider execution merely to access a UI feature.

### Audited usage (PR #494)

At the time of this audit the opt-in `KarenAssistantChat` imports `AssistantRuntimeProvider`, `AuiIf`, `ThreadPrimitive`, `MessagePrimitive`, `ComposerPrimitive`, `ExportedMessageRepository`, `useAgUiRuntime`, `fromAgUiMessages`, and `HttpAgent`. It does not currently use `ActionBarPrimitive`, `BranchPickerPrimitive`, `ThreadListPrimitive`, or a canonical attachments/markdown renderer. Tool and approval components are currently observations, not authorized actions. The production dashboard remains opt-in and the package lock installation/build proof remains a gate.

### Ownership and adoption matrix

| Feature | Existing source of truth | UI strategy | Activation proof |
| --- | --- | --- | --- |
| Thread/message/composer | ChatRuntime, AG-UI, persisted session API | Keep assistant-ui primitives and branded styling; phase out only duplicate presentation surfaces after parity | Stream, stop, reload, error and auth tests |
| Thread list/history | Existing SessionProvider and scoped conversations API | Adopt assistant-ui ThreadList primitives only when an adapter preserves canonical IDs, pagination and ownership; otherwise retain present Karen-owned picker | Tenant isolation, keyboard navigation, pagination and reload |
| Markdown, code, copy | Persisted message content and server-validated rich parts | Compose assistant-ui message parts/renderers and accessible action bar; sanitize untrusted content and use existing copy affordances | XSS, long-code, zoom, screen reader and partial-stream tests |
| Retry, edit, branches | Backend execution and message lineage | Show only when backend supplies replay/edit/branch eligibility; no frontend replay illusion | Idempotency, lineage, authorization and exactly-once side-effect tests |
| Files and attachments | Authorized upload/storage APIs, scoped artifact IDs | Use assistant-ui composer attachments and message previews only with canonical upload receipts | Size/type limits, tenant ownership, cancel, persistence and malware policy |
| Tools / generative UI | CORTEX eligibility, governed plugin executor, AG-UI typed events | Reusable typed tool result slots, progressive activity disclosure, evidence panels | Manifest/schema validation, sensitive redaction and zero client execution |
| Approvals | Backend approval receipt, RBAC and checkpoint | Human confirmation card with server-issued action token and explicit pending/succeeded/denied state | Replay/race/RBAC, refusal and receipt verification |
| Agent plans and work status | Medusa/Deep Agents events projected through runtime | Timeline and task inspector composed inside chat, never a second agent scheduler | Restart/reconnect, ordered events and tenant-scoped checkpoint tests |
| Citations / artifacts | Canonical citations and verified persisted artifacts | Rich cards/viewers within messages, open source or artifact only through authorized links | Broken/deleted sources, permission revocation and content safety |
| Voice | Existing Karen voice subsystem and backend controls | Integrate dictation/audio only through existing voice transport if capabilities warrant it | Permission, upload, transcription, fallback and accessibility tests |
| Suggested prompts / actions | Runtime capabilities and configured tool registry | Dynamic suggestions only from backend-enabled capabilities, never hardcoded claims | Capability removal and RBAC tests |
| Settings, provider inventory and privacy | Existing app panel components and backend APIs | Keep current shadcn-based forms; optionally embed conversation/explanation surfaces that invoke authorized actions | Save receipts, auth boundaries and truthful error states |

### Implementation order

1. **Prerequisite:** restore a consistent package lock, clean install, TypeScript/lint/test/build and authenticated AG-UI smoke tests. No production enablement until exact-head evidence is green.
2. **Transcript parity:** markdown/code, accessible message actions, auto-scroll/copy, stop/error/retry eligibility and mobile/keyboard proof.
3. **Runtime truth:** typed tool visualization, citations, artifacts, agent activity timeline and reconnect/reload persistence.
4. **Guarded interactions:** backend-approved tool confirmations, file uploads, message edit/branch support only where the runtime exposes receipts and eligibility.
5. **Cross-application AI touchpoints:** embed a reusable conversation entry point from settings, memory, downloads and admin workflows, but delegate to canonical ChatRuntime for context, authorization and effects.

**Do not** treat assistant-ui primitives as a reason to replace global settings controls, create another provider router, copy provider state into React, bypass the AG-UI proxy, or use assistant-cloud as a second persistence owner. Each UI action must map to an existing authorized backend contract. Mark unsupported capabilities unavailable rather than rendering ghost controls.

### Source-of-truth references

- Official upstream: https://github.com/assistant-ui/assistant-ui
- Upstream documentation: https://www.assistant-ui.com/docs
- Existing Karen frontend: `src/ui_launchers/Karen-AI-Theme/src/components/chat/assistant-ui/KarenAssistantChat.tsx`
- Existing runtime projection: `/chat/ag-ui`, same-origin `/api/chat/ag-ui` proxy.

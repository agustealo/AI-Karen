# ADR: CopilotKit-first Agentic Application Layer

- Status: **Accepted product direction; migration implementation pending**
- Date: 2026-10-25
- Owner: AI-Karen application interaction architecture
- Decision authority: User's explicit CopilotKit-first preference
- Applies to: Consumer app UI, shared agent state, generative UI, approvals, in-app actions, channel integrations

## Decision

Prefer supported **CopilotKit v2** capabilities over overlapping custom implementation and alternative UI frameworks, including chat rendering. Replace assistant-ui as the default end-user chat rendering framework **after behavior parity and live tests**, not by simultaneous competing mounting. Prefer CopilotKit's built-in components/hooks, extending via supported APIs. Keep AG-UI as canonical wire protocol.

The scope includes CopilotChat/Sidebar/Popup/Threads, agent state hooks, frontend tool interfaces, generative UI rendering, human-in-the-loop interrupts, suggestions, and channels where supported. Evaluate OpenTag (https://github.com/CopilotKit/OpenTag) as a working reference for the **CopilotKit Channels SDK**; it is an example application, not a dependency that should become a second orchestrator.

## Non-negotiable ownership

- ChatRuntime controls all model/provider selection, inference, fallbacks, prompts, event authenticity, audit, and completion.
- CORTEX decides intent, policy eligibility, and action routing.
- LangGraph/Medusa run real complex workflows only; do not bring up a parallel CopilotKit agent executor for equivalent jobs.
- RuntimePolicy/RBAC and tenant/session/consent checks execute server-side at the final action boundary.
- NeuroVault/NeuroRecall and canonical storage own durable memory and conversation writes.
- CopilotKit is the **first-class interaction shell** and state/approval UI; it does not become the source of security, memory or model truth.

## Current-repository evidence (2026-10-25)

- `src/ui_launchers/Karen-AI-Theme/package.json` declares `@assistant-ui/react`, `@assistant-ui/react-ag-ui`, `@ag-ui/client` but no CopilotKit React package.
- `src/ui_launchers/Karen-AI-Theme/src/components/chat/assistant-ui/KarenAssistantChat.tsx` renders the current chat via assistant-ui primitives and AG-UI.
- `src/ui_launchers/Karen-AI-Theme/src/app/api/chat/ag-ui/route.ts` is a canonical AG-UI transport proxy with terminal integrity behavior. Preserve its checks.
- `src/ai_karen_engine/copilotkit/` contains historical task/thread services. `src/ai_karen_engine/integrations/providers/copilotkit_provider.py` includes pseudo-client initialization and treats CopilotKit as an LLM provider. This legacy code is **not proof of installed/live CopilotKit** and must be reference-audited, reconciled, then retired or adapted.
- `docs/architecture/governed-generative-ui.md` contains valid provenance, presentation, replay and security requirements; update, do not discard.
- This ADR does **not** assert that CopilotKit has been installed, the UI replaced, or end-to-end tests passed.

## Mandatory implementation workstreams

### CK-01: Feature & replacement ledger
Map each existing chat, transport, presentation, memory, model-selection, planner, persona and channel user journey to CopilotKit v2 API or Karen extension. Record lost feature risks, owner, old/new paths, acceptance tests and rollback plan. Audit PR #494/#502/#542/#543/#545/#547 and related live source.

### CK-02: Dependency and integration validation
Pin compatible tested `@copilotkit/react-core` and (only if needed) `@copilotkit/react-ui`, with lockfile changes. Follow documented v2 imports and styles, not v1 APIs. Verify local frontend compile and runtime compatibility before replacing component mounts. Avoid introducing `@copilotkit/runtime` as a second backend execution authority unless an isolated compatibility gateway proves necessary.

### CK-03: Controlled chat replacement
Introduce a centrally feature-gated CopilotKit v2 frontend around **the existing authenticated AG-UI endpoint** (or a narrowly justified compliant adapter). Preserve forwarded model selection, persona, sessions, history, voice/dictation, activity rail, accessibility, conversation identity and truthful provider receipts. No second chat store or competing socket. Compare before/after golden user journeys; switch default only after evidence.

### CK-04: Native agentic UI expansion
Use supported CopilotKit hooks for shared application state, suggestions, tool rendering, interrupts and human approvals. Tools and state changes must map to existing, schema-validated backend action contracts. Never expose client-authored elevated permissions or treat tool completion as persisted mutation.

### CK-05: Generative and durable experiences
Reconcile existing versioned presentation registry with CopilotKit generative renderers. Model-proposed components must be allowlisted and evidence-bound. Persist through canonical message transaction and rehydrate with tenant-scoped history; prove streaming, nonstreaming, reconnect and replay parity.

### CK-06: Channels SDK and OpenTag evaluation
Validate version/licensing/deployment/transport details; prototype at most one authorized Slack/Teams channel using the same runtime and guarded actions. Add webhook signing/replay defense, identity mapping, tenant isolation, approval correlation, channel-specific retention and observability. Keep channel infrastructure optional and local-first wherever feasible.

### CK-07: Retirement
Only after parity proof, remove unused assistant-ui packages/components/bridges and redundant historical CopilotKit pseudo-provider/state services, with import and reference audit, migrations if needed, tests and rollback plan. Preserve unique Karen features, migrate them onto CopilotKit extension contracts if no equivalent built-in exists.

## Acceptance

1. Chat: real authenticated request, stream integrity, normal/stream/history equivalence, content and structured UI replay.
2. Model: catalog, requested/actual attribution, fallback truth, explicit model override authorization.
3. Persona/memory: permitted scope, durable persistence, profile switching, zero cross-tenant leakage.
4. Agent actions: authenticated read/write, approval, rejection, concurrent mutation, idempotency, cancellation, rollback.
5. Tool/render safety: payload limits, input schemas, XSS/URL controls, provenance, error and degraded states.
6. UX: keyboard/screen reader, mobile/desktop, sidebar and composer parity, user journey screenshots.
7. Channels: signed messages, identity/tenant binding, retries, exactly-once governed mutation semantics.
8. Operational: code import/compile/lint/typecheck/unit/integration/E2E checks; actual provider and database proof.

Do not represent this ADR's existence as migration progress. Shipping CopilotKit UI requires source changes and verified evidence.

## Rejected alternatives

- Keeping assistant-ui as the permanent primary rendering stack despite a functionally equivalent CopilotKit implementation.
- Installing CopilotKit only as a decorative popup while preserving duplicate chat frameworks.
- Delegating core model/provider selection, RBAC, durable memory or execution to a new CopilotKit runtime.
- Deleting historical components or existing capabilities before successor parity is demonstrated.

## Sources

- https://docs.copilotkit.ai/reference/v2
- https://github.com/CopilotKit/CopilotKit
- https://github.com/CopilotKit/OpenTag

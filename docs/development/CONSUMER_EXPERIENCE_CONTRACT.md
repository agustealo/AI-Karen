# Consumer Experience and Capability Integration Contract

> **Status:** Canonical development guidance for consumer-facing work.  
> **Scope:** Chat, CopilotKit, dashboard navigation, agents, tasks, tools, plugins, memory, personas, models, settings, voice, presentations, persistence and accessibility.  
> **Origin:** CK-27 adversarial consumer audit; PR #603 (CK-27B agent-discovery navigation).  
> **Authority:** [Project Developer Manifest](../../PROJECT_DEV_MANIFEST.md), [Architecture Authority](ARCHITECTURE_AUTHORITY.md), [Testing and Release Proof](TESTING_RELEASE.md). Live source and executed tests determine implementation truth.  
> **Evidence status:** This document is a development contract, not a claim that every capability is implemented, browser-tested or certified.

## Purpose and non-negotiable rule

KAREN must present **one coherent intelligent workspace**, not unrelated engineering subsystems. Consumers should be able to converse, create, act, organize and personalize without needing to understand CORTEX, providers, registries, LangGraph or memory internals.

**If KAREN can do something, authorized users should be able to discover it. If they can trigger it, it must actually execute. If it executes, they must be able to understand, verify, recover and resume its result.**

Before any feature work, locate the existing canonical owner, data contract, permission authority, navigation point and evidence. Fix disconnected functionality instead of building duplicate functionality.

## PR #603: agent discovery to workspace navigation

PR #603 (CK-27B) addresses a specific capability-discovery gap: the composer displays registered agents, but users previously lacked an explicit path from that discovery surface to the existing Agents workspace.

The intended implementation passes a **dashboard-owned navigation callback** through the consumer chat into the runtime catalog, where an accessible **Open Agents workspace** control navigates to the existing Agents page.

**This is navigation only.** Discovering an agent, listing it, or opening its workspace does not grant permission to invoke it. Existing registered-agent discovery remains read-only; CORTEX/runtime policy and the canonical action-execution authority continue to govern any execution. The UI must not independently authorize, fabricate eligibility or invoke an agent when navigating.

For changes to this path, verify the live implementations of:
- `src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx`;
- `KarenCopilotConsumerChat.tsx` (locate its current source path);
- `KarenComposerRuntimeCatalog.tsx` (locate its current source path);
- the existing Agents workspace and backend authorization path.

Do not hardcode another Agents route, duplicate the catalog, create a second agent state store, or promote a discovery UI test into an execution-safety claim.

## Ownership and architecture invariants

| Responsibility | Authority | Consumer-facing contract |
| --- | --- | --- |
| Request validation, authentication and tenant context | Thin API ingress | Safe errors; no route-owned model/tool decisions |
| Intent, capability decision and eligibility signals | CORTEX | Decisions never count as execution |
| Authorization and policy gates | Canonical RuntimePolicy / action gate | Denied actions cannot be bypassed by navigation or UI |
| Chat execution, provider selection, fallback, streaming and persistence | Canonical runtime | Truthful response and execution receipts |
| Graph/multi-agent workflows | LangGraph / Medusa only for appropriate workflows | Observable, bounded, cancellable where supported |
| Model availability and selection | Backend provider/model registry | Display only backend-confirmed availability |
| Conversation and memory state | Canonical session and governed memory services | Authorized recall, correction, persistence and recovery |
| Consumer interaction and presentation | CopilotKit-first UI and governed presentation components | Display backend truth, not speculative status |
| Durable storage | Existing canonical PostgreSQL/Supabase schemas and repositories | No second artifact, memory or conversation database |

**Storage note:** Check the current developer manifest before proposing infrastructure. The canonical memory data spine is PostgreSQL with pgvector and full-text search; legacy Milvus/Elasticsearch memory authority is retired. Redis owns bounded hot/session state where configured. Do not revive retired stores by copying old planning documents.

## Every capability must have an end-to-end journey

Track each enabled feature through:

```text
Discover → Understand → Eligible/authorized request → Runtime decision
→ Actual execution or explicit denial → Verified result/receipt
→ Persistence when promised → Reload/resume → Failure recovery
```

Create or update the existing [user-journey evidence register](../ux/user-journey-audit.md) for real browser proof. Do **not** create a second competing UX evidence store.

For every active capability, record:
- User goal, consumer entry point and discoverability.
- Canonical owner, backend API/contract, registry and relevant feature flags.
- Required permissions, tenant/user/session scope, audit obligations.
- Loading, streaming, approval, failure, cancellation and degraded states.
- Requested versus actual provider/model and response source where applicable.
- Saved state, refresh/reconnect, deletion and rollback expectations.
- Desktop/mobile, keyboard, focus, labels, screen-reader and error behavior.
- Test file, exact revision, environment, observed outcome and remaining gaps.

A source path or component name alone is not proof of consumer availability.

## Interaction system

**One primary workspace.** Chat, work artifacts, tasks, agent activity and context should have consistent navigation and restore semantics. Specialized screens may remain where they materially improve usability.

**One composer.** Expose eligible capabilities via live backend contracts and policy. Do not maintain a frontend shadow registry, imply a tool is executable simply because it is registered, or overcrowd the primary input.

**One status vocabulary.** Use authoritative events for `preparing`, `executing`, `waiting_for_approval`, `waiting`, `completed`, `failed`, `cancellation_requested`, `cancelled`, and `interrupted` (mapping to current schema as necessary). A Stop click is not proof that execution stopped.

**One contextual intelligence surface.** Reveal relevant memory, source provenance, artifacts and real agent activity progressively. Avoid repeating telemetry or overwhelming the conversation. Verify ownership before decomposing oversized components such as the context rail.

**One governed presentation contract.** Reuse existing chat renderers, rich-result workspace and presentation registry. Extend allowlisted types only after auditing existing coverage. Never render untrusted arbitrary components or synthesize a chart/table/research citation from missing evidence.

**Real reusable outputs.** Where supported, generated documents, research, tables, plans and code should be inspectable and recoverable through existing artifact/persistence authority rather than stranded in a transient chat bubble.

## Critical consumer contracts

### Chat and provider truth
- Sending a prompt must follow the canonical runtime, with correct conversation identity and tenant scope.
- Requested provider/model, actual executor, runtime engine, response source, fallback/degradation and correlation ID must be derived from execution receipts.
- Streaming, cancellation, reconnection, interrupted responses and provider failure must not fabricate success or splice mock output into real responses.
- Loading saved history must not silently start another model run.

### Persona, preferences and memory
- Selection, edits and memory permissions must survive refresh and affect subsequent authorized runtime behavior according to documented scope.
- Failed writes must not show saved/success.
- Protect system policy precedence; persona changes cannot override security policy.
- Distinguish current-turn context, authorized recalled context, external sources and inference.
- Reuse canonical inspection/correction/deletion controls; never claim deletion before confirmed persistence.

### Agents, tools and workflows
- Discovery and navigation are not authorization or execution.
- Approved actions must have inspectable intent, progress, permission requests, verified final result and auditable failure.
- Tenant isolation, credential scoping, manifest/schema validation and explicit action permissions are enforced server-side.
- Retry and Stop must be idempotent or explicitly guarded against duplicate execution when applicable.

### Settings and voice
- Every enabled setting needs read → change → confirmed write → reload → demonstrated effective behavior → failure handling.
- Voice needs explicit permissions, useful errors, cancellation, transcription review and preservation of unsent drafts.
- Controls unavailable by policy or capability must disclose why, without presenting a decorative enabled action.

## Adversarial scenarios required for critical paths

Treat the following as **test obligations, not already proven bugs**:

1. Change conversation or tenant while streaming; prevent cross-conversation and cross-tenant leakage.
2. Open history; ensure replay does not invoke a model.
3. Delete a conversation while an action runs; keep correct identity and honest cancellation.
4. Expire auth or revoke permission during execution; fail closed, preserve audit.
5. Fail a provider mid-stream; show actual executor, interruption and degradation accurately.
6. Disable memory/persistence service; avoid invented recall or fake saves.
7. Attempt unauthorized tool/plugin execution; reject server-side and audit.
8. Stop during tool execution; distinguish request to cancel from confirmed termination.
9. Fail a preference write or race two tabs; prevent false success and stale overwrite.
10. Disconnect/reconnect during a workflow; avoid double execution and stale result projection.
11. Return malformed presentation data; render safely without invented result content.
12. Navigate from composer agent catalog to Agents; prove accessible navigation and **no agent invocation**.
13. Test narrow mobile, keyboard-only use, focus restoration, error announcements and draft continuity.

## Priority and delivery slices

| Priority | Meaning | Treatment |
| --- | --- | --- |
| P0 | Security exposure, data loss, false execution claims, or blocked core workflow | Fix before consumer acceptance |
| P1 | Important functionality hidden, disconnected, incomplete or seriously confusing | Target focused CK-27 work |
| P2 | Significant friction, accessibility, visual inconsistency or weak recovery | Schedule after critical journeys |
| P3 | Cosmetic enhancement without meaningful user impact | Defer if reliability is at risk |

Follow the focused sequence, avoiding sprawling PRs:

- **CK-27A:** Capability census and truthful navigation/UX map.
- **CK-27B:** Repair disconnected controls and consumer-to-runtime wiring (including PR #603).
- **CK-27C:** Unified workspace and navigation continuity.
- **CK-27D:** Persona, governed memory and personalization.
- **CK-27E:** Agentic execution visibility, discovery, approvals and recovery.
- **CK-27F:** Presentations, responsive interaction and accessibility.
- **CK-27G:** Real browser, deployment and adversarial consumer certification.

Every independent slice should merge only after its relevant exact-head gates pass. External hosting configuration may be deferred, but hosted certification must remain **not verified** until performed.

## Proof and review checklist

For each PR, reviewers must answer:
1. What exact user goal is repaired, and where does the journey begin?
2. Which existing canonical owner is reused? What duplication was removed or deliberately avoided?
3. Does any UI path accidentally make decisions reserved for CORTEX, RuntimePolicy or the runtime?
4. What are the authorization, session, tenant, persistence, concurrency and rollback behaviors?
5. Does the UI distinguish confirmed action completion, requested cancellation, and failure?
6. What test demonstrates the user path, and what remains unverified?
7. Were navigation, accessibility, mobile layout, latency and recovery checked where applicable?
8. Did documentation and the existing UX evidence register change with the code?

Minimum feature evidence chain:

```text
UI entry → authenticated/authorized request → decision → execution receipt
→ result → persistence → reload → recovery
```

Minimum architecture evidence chain:

```text
One owner → one contract → no duplicate authority → RBAC/tenant
→ observability → executed regression evidence
```

Use the existing [testing/release standard](TESTING_RELEASE.md). For source work, run the relevant `python -m compileall src`, `pytest tests/ -q`, `ruff check src tests`, `mypy src`, frontend package-script lint/typecheck/test/build, `docker compose config` when changed, and applicable GitHub gates. Report outcomes **only when observed**.

For consumer acceptance, use the existing [UX journey audit](../ux/user-journey-audit.md) and [chat verification](../ux/chat-journey-verification.md). Record the exact source/deployment SHAs, browser and viewport, actions, expected/observed results, screenshot/trace, sanitized correlation ID and PASS/PARTIAL/FAIL/NOT RUN. Unit checks or historical screenshots cannot certify a current live journey.

## Required PR scorecard

Report measurements, or explicitly `NOT MEASURED`, for relevant dimensions:

| Measure | Definition |
| --- | --- |
| Capability entry coverage | Eligible active capabilities with usable discoverable entrances / active capabilities |
| Critical journey pass rate | Executed passing critical browser journeys / executed critical journeys |
| Broken enabled controls | Count of enabled actions without working authorized execution |
| Hidden capabilities | Count of eligible capabilities with no usable navigation/entry |
| Duplicate ownership | Count of competing runtime/registry/persistence authorities |
| Persistence integrity | Verified save/reload/recovery paths and failures |
| Accessible interaction | Keyboard, focus, semantics, screen-reader and mobile defects |
| Presentation coverage | Validated runtime result types with supported rendered experience |
| Recovery coverage | Executed failures with truthful, usable recovery |
| Attribution correctness | Actual provider/model/source fields backed by execution receipt |

Never invent baseline percentages.

## Documentation maintenance

- This document defines the **consumer integration contract**, not subsystem implementation authority; the developer manifest and corresponding subsystem docs continue to own their architecture.
- Update this contract only when the consumer integration principles change. Record feature-level outcomes in the existing UX evidence register and relevant tests, not in a duplicate checklist.
- Update `docs/development/README.md` when moving or renaming this guide.
- Treat old PR discussions and historical audit text as input to verification, not as live source truth.
- Source-green, deployed-ready and consumer-certified are three different claims. State each separately.

**Adoption test:** A person who has never read this repository can discover meaningful features, use them safely, understand what KAREN actually did, and return later without losing their work.

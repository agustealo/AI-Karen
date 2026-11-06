# Karen × CopilotKit: canonical convergence plan and living execution ledger

> **SINGLE LIVING CHECKLIST — KEEP THIS FILE CURRENT WITH EVERY RELEVANT PR.**
>
> **Status:** ACTIVE ENGINEERING PLAN; **consumer release NOT VERIFIED**.  
> **As-of/source baseline:** 2026-11-06, verified live `main@1c496a64319e55d061df64a14a09d8f9d617382d` (PR #682 merged). Source CI is not Render deployment or consumer acceptance.  
> **Document owner:** Karen architecture / consumer experience maintainers. **Execution owners:** the existing domain owners below.  
> **Scope:** first-class CopilotKit chat, Persona Studio, agentic tasks, AG-UI, model/prompt/context/memory, native tool/suggestion/approval UX, history, generated presentation, MCP/skills/sandbox, channels, resilience, telemetry, security, accessibility, CI, and removal of replaced logic.
>
> This **replaces the stale 2026-10-25 static migration outline** in this very same canonical path. Do not create another checklist or "v2 plan" for this initiative. The accepted architecture, narrower implementation design, and specialized release evidence remain linked below. A feature mentioned in a design is not implemented; a feature in source is not necessarily enabled; a green unit test is not a consumer browser pass.

## 0. How every contributor uses this file

**Start each new development slice:** read this ledger; check actual `main` SHA; locate the current owner and imports; inspect relevant existing PRs, docs, schemas, tests, and SDK package typings; choose one or more existing `KCON-` task IDs; record baseline proof. **Do not create another renderer, agent runtime, registry, schema, store, or transport to solve a missing integration**.

**For every relevant PR:** update the relevant unchecked task(s) here in the *same PR*. Keep IDs stable; add source paths, existing feature reuses, the PR link and its status, tests and exact commit, and remaining gaps. A task becomes `DONE` only after its defined proof completes on the candidate commit; subsequent failures reopen it. Link screenshots, structured receipts, logs, browser acceptance and database evidence by durable CI/PR URLs, not unpublished local claims. For merge, update the evidence row after CI, or state explicitly that browser/release proof remains pending. On each subsequent scoped PR, reconcile the ledger with `main`, not just with a prior PR head.

**States:**
- `NOT_STARTED`: no qualifying implementation verified.
- `SOURCE_ONLY`: implementation or tests are present in repository; not proof of an authorized, deployed user journey.
- `IN_PROGRESS`: active reviewed PR/change, not merged and/or gates pending.
- `BLOCKED`: specific gate failed; record error, owning task and deterministic remedy. An unavailable external environment is `NOT_RUN` for the dependent proof, not permission to say green.
- `MERGED_UNVERIFIED`: committed to live `main`, but defined real runtime/browser acceptance outstanding.
- `DONE`: source, tests, exact-head CI, authentic runtime and/or human browser proof required for that item are recorded and passed.
- `DEFERRED`: intentional scope exclusion, with rationale and a product decision. Never substitute this for an incomplete committed feature.

**Checkbox semantics:** `[x]` means `DONE` and must have a cited durable evidence location. `[ ]` means unfinished, including code already merged when the acceptance gate is unproven. The descriptive status matrix is evidence-based and is not a second checklist. Record every skipped test, unknown environment flag and missing provider as NOT_RUN.

### Status header, update with each merge or relevant PR

**Current merge chain (2026-11-06):** `#670–#675 → #677 → #679–#682` merged on `main` (excluding superseded #676). PR #682 added fail-closed exact-live-SHA Render inspection, but no Render configuration change, deployment, or authenticated browser acceptance is established. Do not mark table, source provenance or browser readiness DONE until live signed-in acceptance records an exact deployed revision, browser run URL, valid source receipts and replay.

| Tracking field | Current evidence |
|---|---|
| Canonical baseline | Live `main@1c496a64319e55d061df64a14a09d8f9d617382d` verified 2026-11-06; #682 merged; Main Quality Gate, backend/frontend quality and deployment contracts succeeded on this main SHA. Render source reconciliation, boot, durable PostgreSQL and signed-in browser acceptance are NOT_RUN/UNVERIFIED |
| Native React view | `@copilotkit/react-core@1.79.1` declared; `CopilotKitProvider` + `CopilotChatView` mounted in source |
| High-level chat | `CopilotChat` **not mounted**; automatic initial `runAgent` conflicts with trusted history boot |
| Chat controller | Karen-controlled submit/draft/stop; uses SDK `copilotkit.runAgent({ agent })` correctly |
| History | owner-checked manual hydration; strict rich event replay; on unsupported replay, read-only text recovery |
| Runtime | `ChatRuntime` authority; CORTEX and RuntimePolicy decide; direct, reasoning, normal, graph paths in source |
| Medusa/Deep Agents | agent coordination source exists; `deepagents_research_enabled` defaults false; real agentic journey unverified |
| Persona | saved selector/snapshot source exists; default prompt projects tone, verbosity, language; purpose specialization is not proven |
| Presentation | Eight validated types on main, including `data.table`. #671 added Python/React schema and renderer; #672 authorized runtime projection; #673 produces source-attested search-excerpt tables for explicit first-turn prompts; #674 restricts labels and field mappings. Source merged/CI proven; live browser first-send/reload **NOT_RUN**; comparative facts, recipes and steps still missing |
| Known recent work | #661–#665 recovery/native transport; #666/#668 governed search and acceptance specs; #670–#675 source tables/provenance and first-run preflight; #677 auth DB session reuse; #679 durable-database preflight; #680 safe clickable source links; #681 ledger; #682 exact live Render SHA preflight. No authenticated browser pass inferred |
| Search/movie work | PR [#659](https://github.com/agustealo/AI-Karen/pull/659) CLOSED as superseded by merged [#666](https://github.com/agustealo/AI-Karen/pull/666); do not merge the old draft or restore its stale history/CI changes |
| CI | Latest `main@1c496a64` commit checks: Main Quality, backend quality, frontend quality, classifier burn, deployment/production deployment contracts, production database baseline contract all success (7 checks). Source-only success; signed-in Playwright consumer scenario not verified against a live backend |
| Production and release | Earlier Vercel READY observation was at `6e3fd07b85793408e3a3c69e1e5165c9cb363740` (#673), behind reviewed main; `/api/auth/first-run` proxy AbortError observed. Render previously tracked Oct 31 legacy branch with failed deploys and no HTTP health probe. Latest Render state not reattested; existing protected reconcile `apply` has not been verified executed. Render production env, durable PostgreSQL, live exact SHA, Vercel upstream target match, migration 43 and signed-in browser remain unresolved. **NO CONSUMER SIGNOFF** |

### Architecture documents that remain authoritative for their own domains

- [Architecture Authority](../development/ARCHITECTURE_AUTHORITY.md) for control-plane ownership.
- [CopilotKit-first ADR](../architecture/decisions/2026-10-25-copilotkit-first.md) for the accepted SDK-first product direction.
- [Consumer Experience Contract](../development/CONSUMER_EXPERIENCE_CONTRACT.md) for end-user lifecycle and usability.
- [Persona implementation contract](../architecture/KPERSONA_FIRST_CLASS_IMPLEMENTATION.md) and [Persona data/skills guide](../architecture/PERSONA_SKILLS_LEARNING_DATA_GUIDE.md) for PersonaService, task-purpose/knowledge boundary and learning.
- [Run ledger and cancellation](ck07-runtime-run-ledger.md) for durable chat execution and honest stop receipts.
- [Governed generative UI](../architecture/governed-generative-ui.md) and [legacy-retirement ledger](copilotkit-legacy-retirement.md) for provenance and per-artifact deletion evidence.
- [Consumer truth map](../ux/CK-27A-CONSUMER-CAPABILITY-TRUTH-MAP.md) and [testing/release contract](../development/TESTING_RELEASE.md) for observed journeys.
- [Response lifecycle authority audit](../architecture/response-lifecycle-ownership-audit.md) for final-answer ownership.
- Official pinned-v2 reference: https://docs.copilotkit.ai/reference/v2 ; high-level chat: https://docs.copilotkit.ai/reference/v2/components/CopilotChat ; hooks: https://docs.copilotkit.ai/reference .

**Conflict rule:** the current implementation and verified test evidence establish actual status. This ledger establishes *initiative scope and pending work*. Existing ADR/security/architecture contracts determine ownership. Correct stale descriptive content in linked docs in the same PR where practical; do not resurrect obsolete modules merely because old prose names them.

## 1. Target user journey and boundaries

One authenticated consumer conversation persists while navigating Chat, Persona Studio, Planner, Agent Runtime, settings, models and approved other surfaces. The user writes an ordinary request **once**. The backend resolves identity, persona snapshot, user-approved context and memory, tool/agent eligibility, provider and model. CORTEX selects ordinary chat, direct capability, reasoning, governed tool action or real graph/agent execution; RuntimePolicy constrains every action. A simple answer starts quickly; a complex request can plan, use capabilities, pause for approval, verify and return a result without forcing a separate Agent workspace. CopilotKit renders genuine SDK messages, suggestions, tool state, approvals, composition and progress, but never owns provider choice, tool authority, permissions or canonical persistence. On refresh, switch or failure, identity and saved messages remain accessible, and only attested rich content is replayed. Unsupported rich elements must not erase readable history or permit an unsafe rich replay; define and prove a safe continuation protocol rather than silently creating a new SDK thread.

Four distinct concepts:
1. **Persona:** approved communication/collaboration profile, purpose, terminology, task framing and scoped, authorized knowledge references; **no executable authority**.
2. **Agent:** governed work executor with objective, plan, tool permissions and lifecycle; subagents only under authorized real multi-step work.
3. **Skills/plugins/MCP:** versioned capabilities, manifests and eligible external resources; **not** independent models or permissions granted by persona selection.
4. **Runtime:** the only executor/persistence coordinator; **not** a substitute user persona or second policy engine.

**Never:** arbitrary client-authored agent/model routing; hidden fallback from agent to canned prose; trust browser state for tenant/approval identity; initial mount invoking inference; synthetic RUN_FINISHED; parallel stores; SDK-native thread writes bypassing Karen repository; a persona acting as a system-policy override; unbounded executable model-generated UI.

## 2. Feature-by-feature adoption, preservation and truth matrix

Definitions: **TAKE** = adopt native CopilotKit behavior/hooks/UI where available at pinned version; **KEEP** = existing Karen truth/behavior stays authoritative; **ADAPT** = one bridge/slot/serialization mapping; **REJECT** = no second owner or unsafe behavior. **SOURCE_ONLY** means source exists but end-to-end consumer proof is outstanding. Rows with `GAP` describe required work, **not** installed features.

### 2A. Conversation and interaction

| Capability | TAKE from CopilotKit | KEEP from Karen / authority | Current evidence → disposition | Gate |
|---|---|---|---|---|
| Chat shell, transcript, toolbar | `CopilotChatView`, native assistant/user message slots | One dashboard mount, Karen UX tokens | SOURCE_ONLY native view mounted; preserve | KCON-110 |
| High-level `CopilotChat` | Built-in agent wire-up, pending, clear, suggestions | No initial inference; verified identity/draft | GAP: not mounted; evaluate, do not force | KCON-120 |
| Streaming and stop UI | SDK stream/stop controls | AG-UI validated transport, durable exact-run cancel | SOURCE_ONLY current controlled view | KCON-130, KCON-604 |
| Composer, input, keyboard | Native input, send/stop/selection/toolbar slots | Durable draft, CAS conflicts, user-driven send, shared workspace | SOURCE_ONLY custom controller | KCON-140 |
| Conversation threads/drawer | `useThreads` and native drawer if adapter can consume canonical history | `SessionProvider` / DB identity, RLS, CRUD | SOURCE_ONLY session/history controls; native sync unproven | KCON-150 |
| Saved replay | SDK agent messages/UI slots | Owner-verified canonical history, complete run attestation | SOURCE_ONLY strict gate and text-only recovery | KCON-160 |
| Branches, edit/retry/regenerate | Native affordance only after verified protocol mapping | New run/version, immutable prior receipts, audit | GAP; no invented historical branches | KCON-170 |
| Welcome/prompts/suggestions | `useConfigureSuggestions`, `useSuggestions` | Backend eligibility, declared model/tool availability | GAP in mounted view | KCON-180 |
| App-wide popups/sidebar | CopilotKit popup/sidebar *view* where needed | Single SessionProvider/one mounted agent/composer | GAP: avoid duplicate floating runtimes | KCON-190 |
| Accessibility, themes, responsive | Native customizable slots/styles | Karen design system, focus, language, scroll parity | SOURCE_ONLY UX tests; browser gate | KCON-900 |

### 2B. Agentic execution and user-action integration

| Capability | TAKE from CopilotKit | KEEP from Karen / authority | Current evidence → disposition | Gate |
|---|---|---|---|---|
| Native tool-call rendering | `useRenderTool` / `useComponent` / default renderer | Tool receipts, evidence, ACL, action IDs | GAP in mounted chat integration | KCON-410 |
| Frontend tool calls | `useFrontendTool` only for bounded UI-local actions | Server reauthorization for writes/privileged operations | GAP; forbid unguarded direct side effects | KCON-420 |
| Human in loop | `useHumanInTheLoop` and `useInterrupt` surfaces | RuntimePolicy + existing ApprovalService/repository | GAP in mounted chat; existing backend owners | KCON-430 |
| Shared UI/application state | Agent/context hooks and state snapshots/deltas as UI hints | Canonical persisted state, authorization, revision checks | GAP; backend currently rejects arbitrary client state | KCON-440 |
| Plan, progress, subagent timeline | SDK activity/tool messages + slots | CORTEX decisions, WorkflowRuntime/Medusa events, real run ledger | SOURCE_ONLY observability rail; live proof pending | KCON-450 |
| Agent discovery and invoke | Native chat entry points, optional tool UI | Registry/catalog, eligibility intersection, Medusa execution | SOURCE_ONLY separate workspace; one-prompt journey gap | KCON-460 |
| Multi-step workflows / checkpoints | Render statuses and interrupts | LangGraph only when graph required; Medusa governed, durable run owner | SOURCE_ONLY; Deep Agents disabled by default | KCON-470 |
| Agent run artifacts | Native message cards where appropriate | Canonical verified artifacts and authorization | GAP for general durable artifact experience | KCON-480 |
| Schedules / tasks / planner | Agent-driven interaction / approval presentations | Existing tasks/jobs/planner and durable ownership | SOURCE_ONLY separate screens; connection gap | KCON-490 |

### 2C. Intelligence, identity, resources and safety

| Capability | TAKE from CopilotKit | KEEP from Karen / authority | Current evidence → disposition | Gate |
|---|---|---|---|---|
| Intent/routing | Nothing: SDK is a projection | CORTEX → RuntimePolicy → ChatRuntime | SOURCE_ONLY execution branches exist | KCON-210 |
| Provider/model selection | Catalog display/optional UI slots | Provider registry, health, requested/actual/fallback truth | SOURCE_ONLY model request/receipt | KCON-220 |
| Prompt/persona resolution | Optional visible selector | PersonaService, PromptRuntime allowlist, user/tenant scope | SOURCE_ONLY tone/verbosity/language path | KCON-230 |
| Scoped learning/knowledge | Read-only user-facing evidence cards | NeuroRecall, NeuroVault, user model, provenance, consent | SOURCE_ONLY domain infrastructure | KCON-240 |
| Per-turn context budgets | UI disclosure only | PromptRuntime token budget, evidence inclusion | SOURCE_ONLY; measure losses | KCON-250 |
| Web/current search and weather/time | Display results via native slots | Authorized plugin tool, source validity and time provenance | SOURCE_ONLY; #659 OPEN for search cards | KCON-260 |
| MCP integrations | Visualize eligible tools/resources | Existing `mcp/`, extension manifests/registry and ActionExecutionGate | SOURCE_ONLY infrastructure, consumer discovery unverified | KCON-500 |
| Skills | Discover/describe eligible skills and task need | Existing plugin/capability contracts, versioned prompts, RBAC | GAP: no second skill engine | KCON-510 |
| Sandbox | Status/approval/artifact UI | Existing isolated execution infrastructure, egress/secrets and tenant fences | SOURCE_ONLY related utility; enforcement audit required | KCON-520 |
| Attachments, files, images | Native input affordances only if supported/pinned | Upload scan, MIME/size quotas, canonical storage/ACL, model capability | GAP/UNVERIFIED for this mounted journey | KCON-530 |
| Voice/dictation | Native voice where reliably supported | Karen browser/local speech capture, permissions, safe draft port | SOURCE_ONLY existing voice controls | KCON-540 |
| Channels (Slack/Teams/etc.) | Channels SDK UI/transport only when useful | Existing ChannelHost, ingress, identity, queues, delivery, secrets | SOURCE_ONLY backend host; integration optional | KCON-550 |
| Security / RBAC | UI approval/notification only | Auth, RLS, policy, audit, tool execution, tenant isolation | SOURCE_ONLY defenses; negative live proof needed | KCON-600 |
| Observability/diagnostics | UI activity/status slots | Structured traces, receipts, persisted result, redaction | SOURCE_ONLY metrics; parity audit needed | KCON-650 |

### 2D. Generative output and production UX

| Capability | TAKE from CopilotKit | KEEP from Karen / authority | Current evidence → disposition | Gate |
|---|---|---|---|---|
| Ordinary Markdown/structured text | SDK message renderer/toolbar | Grounded response policy and provider attribution | SOURCE_ONLY; quality/latency proof missing | KCON-700 |
| Tables/charts/lists/comparison | Reusable typed renderers or approved A2UI where supported | Karen evidence schema + canonical registry and source references | MERGED_UNVERIFIED: `data.table` source schema/renderer, attested source excerpts and per-field semantics (#671–#674). Comparison, charts, steps, artifacts and browser acceptance still GAP | KCON-710 |
| Time/weather/date/planner cards | Native slot renders Karen validated envelope | `karen.presentation.v1`, verified tool evidence | SOURCE_ONLY, merged corrections without browser proof | KCON-720 |
| News, movies, recipe, research | Native reusable cards/layouts; not arbitrary model HTML | Verified source/admission; live data freshness; recipe task data | MERGED_UNVERIFIED: #666/#668 search/movie cards and tests; #673 source tables on explicit prompt, #674 field provenance. Recipes, grounded comparisons, provider freshness and signed-in browser still GAP | KCON-730 |
| MCP Apps/A2UI interactive UI | Evaluate upstream v2 capabilities and pinned compatibility | Sandbox/allowlist/ACL/content security/replay | DEFER until trust/size/security proof | KCON-740 |
| Citations/source list | Native component slots | Authorized citations, same source ID replay, safe URL handling | MERGED_UNVERIFIED: #670 URL parity, #672/#674 per-row source URI, title/field checking; browser and adversarial external provider proof pending | KCON-750 |
| Exports/print/share/download | Native UI hooks only for display/navigation | Permissioned artifact store, content rights, destination limits | GAP/UNVERIFIED | KCON-760 |
| Error/degraded/slow network | SDK error/empty/loading surfaces | Honest no-model fallbacks, actual runtime receipts, no fake answers | SOURCE_ONLY partial guards | KCON-770 |
| Rollout, telemetry, test, retire | No SDK replacement for release authority | Exact SHA, real model/DB/browser burn, human signoff | NOT_DONE | KCON-920, KCON-950 |

**Upstream feature ≠ installed/usable Karen feature.** Check exports, type signatures, behavior and licensing against the *locked* `1.79.1` dependencies before any migration. In particular, CopilotKit's high-level `CopilotChat` can invoke an initial agent run on mount. Do not mount it against unhydrated persistent history. It is permissible for the **final** architecture to keep native `CopilotChatView` when necessary to preserve verified no-inference boot, provided all equivalent native v2 interactions are integrated through supported slots/hooks. Do not make a component-name swap a success metric.

## 3. Explicit ownership and data flow (no duplication)

`User intent + authenticated account/tenant + conversation + saved persona preference` → existing authenticated Next proxy → `/api/copilotkit` compatibility gateway → existing `/api/chat/ag-ui` ingress → `ConversationRuntimeGateway` validates ownership → `ChatRuntime.execute_stream` freezes persona snapshot → `CORTEX` intent/evidence needs → `RuntimePolicy` allowed plan → `NeuroRecall/MemoryRuntimeManager` authorized evidence → `PromptRuntime` approved context → canonical provider routing / ordinary model / approved direct tool / reasoning / WorkflowRuntime → `AgentMedusa` only if eligible → `ActionExecutionGate` before tool side effects → canonical persistence + run finality/receipts + telemetry → `AGUIEventProjection` → CopilotKit SDK state/renderers → user.

**Never move these functions into the SDK gateway:** model selection, fallback order, prompt building, memory recall, session ownership, tool invocation, signing/trusting receipts, checkpoint commit, approval authorization, tenant scoping, backend state mutation or agent scheduling.

| Owner | Canonical sources / required changes |
|---|---|
| Interaction shell | `src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/{KarenCopilotChat,KarenCopilotConsumerChat,KarenCopilotControlledChat,KarenCopilotHistoryGate,KarenCopilotVerifiedHistory,KarenCopilotVerifiedRail}.tsx`; consolidate, do not fork |
| Session | `components/chat/SessionProvider.tsx` and existing conversation API/repository |
| SDK gateway/transport | `src/app/api/copilotkit/[[...slug]]/route.ts` + `_lib/owned-*.ts`; AG-UI proxy and `src/ai_karen_engine/api_routes/chat/runtime.py` |
| Core execution | `src/ai_karen_engine/core/runtime/{chat_runtime,decision_pipeline,workflow_runtime,chat_run_lifecycle,ag_ui_event_projection,owned_history_projection}.py` |
| Cognitive, policy, tool | `core/cortex/`, `core/runtime/policy/`, `core/runtime/contracts.py`, existing extension/action gate |
| Models and prompts | `core/model_runtime/`, `core/expression/`, `core/runtime/prompt/` |
| Persona | `services/persona/persona_service.py`, `core/persona/contracts.py`, `core/runtime/prompt/persona_contract.py`, `api_routes/users/persona.py`, existing Persona Studio |
| Memory | `core/memory/`, `core/personalization/`, `platform/memory/`, governed persistence repositories |
| Agent/workflows | `agent_medusa/`, `core/runtime/workflow_runtime.py`, existing workflow configs/registry |
| Presentation | `core/runtime/presentation_contract.py`, `components/chat/KarenPresentationRegistry.tsx`, existing source and card renderers |
| Tools/MCP/skills | `extensions/`, `mcp/`, `extensions/platform/core/host/mcp_integration.py`, existing manifests/capability registry |
| Isolation | `extensions/platform/core/integration/sandbox_manager.py`; relevant platform isolation and tool gates |
| Approvals | `services/approvals.py`, `persistence/repositories/approval_repository.py`, `api_routes/automation/approvals.py` |
| Channels | `services/channels/`, `extensions/channels/`, `config/channels.py` |
| Observability and release | Existing platform observability and `.github/workflows/{main-quality-gate,chat-system-burn,presentation-contract,beta-release-gate}.yml` |

## 4. Dependency-ordered execution checklist

> The order below is intentional: **source-of-truth → trustworthy conversation → intelligence → native UX → agentic actions → rich presentation → proof → deletion.** Implement vertical slices using current owners. For every box, add `PR/commit` and **exact proof** before checking it.

### Wave 0 — Architecture, inventory and live status (P0, gate for other waves)

- [ ] **KCON-001** Audit all current runtime/chat/persona/agent entrypoints, route mounts, dynamic imports, test references, flags and extension manifests; classify each as canonical, adapter, useful incomplete, legacy dead, or experimental. **Owner:** architecture. **Proof:** import/call graph and reference audit at exact SHA.
- [ ] **KCON-002** Reconcile current capability inventory with `docs/capabilities/baseline.v1.json` and existing UI truth map. Record backend existence, UI exposure, source-only vs browser verification, config availability, safety and UX dependencies. **Proof:** reviewed matrix and eligibility audit.
- [ ] **KCON-003** Verify locked CopilotKit 1.79.1 and all transitive AG-UI/React/Next/Tailwind dependencies using actual installed package types and reproducible install; document which hooks/components are *really* available. **Proof:** lockfile, `npm ls`, import test, build.
- [ ] **KCON-004** Audit duplicate chat/agent/formatter/provider/plugin/SDK compatibility services, including `agents/agent_orchestrator.py`, `copilotkit/` and `integrations/providers/copilotkit_provider.py`; do not delete before consumers/protection proven. **Proof:** dependency graph and replacement map.
- [ ] **KCON-005** Capture clean signed-in baseline journeys, UX/screenshots, first-token latency, total latency, empty responses, token budget, selected vs actual provider and all current failure classes. **Proof:** immutable test artifacts and deployed SHA.
- [ ] **KCON-006** Reconcile open #659 against current main; ensure first-prompt search/movie projection and canonical replay are not independently reimplemented in this initiative. **Proof:** linked PR decision, conflict check and post-merge status.
- [ ] **KCON-007** Prove target running API and deployed browser revision match reviewed git SHA; local source and unmerged PR are not deployed truth. **Proof:** signed revision / browser result.
- [ ] **KCON-008** Record baseline release decision and unknowns before changing defaults: **NO consumer readiness assertion** without the release gate. **Proof:** PR review record.

### Wave 1 — Native CopilotKit interaction without losing durable trust (P0)

- [ ] **KCON-110** Keep exactly one mounted CopilotKit SDK provider/agent/chat for the authenticated scoped conversation. Prove no duplicate renderer, composer, shadow agent or useAgent registration across shell/workspaces. **Proof:** real browser mount/call counters, tests.
- [ ] **KCON-120** Evaluate high-level `CopilotChat` against controlled `CopilotChatView` with saved history and new chats. Decision must show whether built-in setup can meet **zero inferred runs on mount**, no duplicate history and preserved draft. Adopt high-level only if every guard holds; otherwise retain native view and reuse native hooks/slots. **Proof:** initial-mount zero-run adversarial test on pinned SDK.
- [ ] **KCON-130** Verify SDK message streams, lifecycle, terminal states, error and stop event parity through existing AG-UI proxy; preserve request/correlation IDs. **Proof:** protocol tests plus real streaming model. **Progress (2026-11-05, SOURCE_ONLY candidate):** Native pinned `CopilotKitProvider.messageFilter` passes only the latest user/runtime message, keeping full visible history while ChatRuntime reconstructs canonical context. Source/units added; actual SDK transport with >50 saved messages and tool/interrupt follow-ups still requires authenticated browser/protocol proof. Do not mark DONE for source-level filtering.
- [ ] **KCON-140** Converge SDK input lifecycle and Karen CAS-persisted drafts; never clear or invent a successful send before server acknowledgement. Support keyboard, submit, stop, failed-message restore and concurrent edits. **Proof:** browser reload/multi-tab/conflict/failed-submit suite.
- [ ] **KCON-150** Reconcile native `useThreads`/drawer, if used, with `SessionProvider` and canonical conversation repository; no second thread history, phantom thread, or unowned delete/rename. **Proof:** create/search/list/rename/archive/delete/pagination with RLS.
- [ ] **KCON-160** Make supported history safely **usable and continuable**; preserve canonical text independent of rich attachments while verifying events separately. Unknown rich content is withheld, counted, and never trusted; don't block ordinary authorized conversation forever. Define an owner-validated continuation handshake before enabling sends from recovered mode. **Proof:** 409, invalid event, replay, 500+ turns, tenant/cross-user and safe continuation tests. **Progress (2026-11-05):** PR #661 merged verified text copy plus explicit new-session handoff (source/CI verified; not browser-proven). PR #662 merged canonical read-only 500-entry transcript pages with per-page owner checks; the parent `updated_at` check is best effort, not an immutable revision. PR #664 merged an explicitly clicked original-thread text-only continuation path with completed-run digests and zero historic rich events. **Progress (MERGED_UNVERIFIED, 2026-11-05):** PR #665 extended that same path to 1000+ saved messages using a bounded latest-501 sentinel, displaying only the recent 500 chronologically with older-history disclosure; source, Chat Burn and PostgreSQL CI passed. Exactly attested runtime messages remain mandatory, and historical rich activity is never replayed. **Still open:** real-browser click → same original thread → new model turn/stop/reload over 1,000 messages, concurrency/cross-tenant proof, immutable snapshot/version for edits, and full rich UI parity. Keep KCON-160 unchecked.
- [ ] **KCON-170** Evaluate edit/regenerate/retry/branch semantics, if present in pinned SDK, against immutable receipts and conversation versioning. Do not surface an action until backend supports honest append/branch semantics. **Proof:** audited accepted/rejected mutation tests.
- [ ] **KCON-180** Wire native suggestions/welcome prompts only from available, authorized backend capabilities. Prevent pre-mount model runs, fictional tools and cross-persona suggestions. **Proof:** first mount and disabled-capability tests.
- [ ] **KCON-190** Preserve shared shell workspace context and optional sidebar/popup appearance without mounting another independent agent or memory store. **Proof:** navigate Chat/Planner/Persona/Agents with unchanged conversation/draft.
- [ ] **KCON-195** Remove only duplicated local presentation and composer state after native slots prove parity; retain unique safety controls. **Proof:** import-reference audit and UX diff.

### Wave 2 — Core intelligence and model attribution (P0)

- [ ] **KCON-210** Verify one-prompt CORTEX topology selection for simple chat, time, weather, news, explicit reasoning, tool action, graph workflow and subagent request. No UX mode switch needed for eligible tasks. **Proof:** request → decision → policy → actual executor trajectory for each.
- [ ] **KCON-211** Test explicit preferred provider/model does not silently downgrade the separate reasoning path or force a different topology; refactor any consequential branch condition in `chat_runtime.py` using canonical capability/routing policy, not scattered overrides. **Proof:** matrix of selected/default models and direct/reasoning/graph routes.
- [ ] **KCON-212** Audit no repeated expensive tool/provider startup on short chats; eliminate duplicate inference/formatting/response synthesis where unnecessary. **Proof:** measured p50/p95 first token and end-to-end budget across warm/cold runs.
- [ ] **KCON-213** Unify ordinary and streamed answer behavior (grounding, token usage, error finality, direct capabilities) under current runtime contract. **Proof:** identical inputs and completed receipts, no "status-only success".
- [ ] **KCON-220** Validate provider registry health, enabled models, user preference and true fallback order; UI shows actual runtime engine, requested vs executed provider/model, degraded and honest unavailable. **Proof:** real local and optional external/provider-down integration.
- [ ] **KCON-221** Prevent "internal continuity candidate", tool IDs, runtime JSON/debug metadata or unverified reasoning internals from leaking as user-facing ordinary speech. **Proof:** response hygiene adversarial corpus and real answer review.
- [ ] **KCON-250** Audit context token selection, history truncation, continuity candidate inclusion, memory-source provenance and task prompt adherence with the selected model. **Proof:** PromptRuntime inclusion receipts and regression quality corpus.
- [ ] **KCON-260** Close verified direct capability results for current time/weather/search; ensure supported data shapes, timezone, source freshness, denial and first-turn/reload parity. **Proof:** real tool receipts; #658 merged is source evidence only.

### Wave 3 — Persona theory becomes functional specialization (P0/P1)

- [ ] **KCON-230** Confirm persona contract split: identity/purpose and collaboration preferences are **data**, never elevated system policy, model selector, memory grant, tool permission, agent runtime or sandbox owner. **Proof:** typed authority-denial and prompt-injection tests.
- [ ] **KCON-231** Reconcile `core/persona/contracts.py`, PersonaService CRUD, revisions and PromptRuntime's presentation allowlist; remove schema drift, not protections. **Proof:** import, auth, migration, API, service and prompt tests.
- [ ] **KCON-232** Extend the **existing permitted prompt projection** with bounded purpose, role terminology, collaboration/task method and authorized document reference descriptors. Retain policy/system precedence; test same-model controlled task quality, not only tone. **Proof:** real model A/B, applied-field evidence, token/latency changes.
- [ ] **KCON-233** Snapshot one approved persona revision **before** CORTEX/evidence/prompt for each turn, preserving immutable user/tenant identity, purpose scope, and reset on principal change. **Proof:** concurrent tabs, switch during run, tenant and private-scope tests.
- [ ] **KCON-234** Make Persona Studio save, activate, preview, version/conflict/revert and effective fields truthful. Show preview as a separate real-model transaction; never fabricate saved preference success. **Proof:** real PostgreSQL + signed-in browser.
- [ ] **KCON-235** Attach approved project resources/skills by reference to persona purpose; actual retrieval/permissions are checked each run, and revocation invalidates access. **Proof:** revoked data, cross-persona/cross-tenant isolation, denied skill.
- [ ] **KCON-236** Add governed correction-to-preference candidate workflow with explicit consent, versioning, rollback and evidence source; never silently promote quoted text into directives. **Proof:** accepted/rejected/quoted corrections and reload tests.
- [ ] **KCON-237** Persona UX: active identity, what the persona knows, applicable collaboration fields, why a field was ignored, evidence gaps, and effective source status. **Proof:** consumer usability and accessible controls.
- [ ] **KCON-238** Evaluate helpfulness gain against unchanged base model and task suite (accuracy, preference adherence, retrieval relevance, leakage, latency) before promoting industry labels as "expert" capability. **Proof:** repeatable real-model evaluation and negative controls.

### Wave 4 — Memory, durable identity and history (P0/P1)

- [ ] **KCON-240** Verify STM, episodic, LTM, NeuroRecall and NeuroVault ownership/retrieval/persistence across simple chat, tool and agent paths. Avoid new persona/agent-specific memory stores. **Proof:** live PostgreSQL + authorized retrieval lineage.
- [ ] **KCON-241** Check conversation history exact owner and tenant scope at API, database, SDK bridge, agent invocation, tool output and restore; no client-supplied alias expansion. **Proof:** RLS and cross-principal denial.
- [ ] **KCON-242** Verify user+assistant write order, atomic completed-run identity, evidence and presentation capture, idempotent retry and no false persistence success. **Proof:** fault injection and read-after-write.
- [ ] **KCON-243** Reconcile private persona-scoped recall vs conversation continuation. Unauthorized context stays withheld; a backend-derived allowed text projection can remain visible. **Proof:** persona switch and context authorization tests.
- [ ] **KCON-244** Audit message retention/export/delete/redaction and artifact lineage, including saved events and caches. **Proof:** retention, export, delete, backup/restore and cross-tenant negative cases.

### Wave 5 — Agents, workflows, tool execution and governed autonomy (P1)

- [ ] **KCON-450** Map real Medusa/LangGraph activity event kinds to SDK step/tool progress, stable step IDs and terminal receipts. No fabricated plans from model prose or an empty activity rail incorrectly implying failure for normal chat. **Proof:** real run emitted/replayed event parity.
- [ ] **KCON-460** Enable one ordinary chat prompt to invoke an eligible registered agent without navigating the Agents workspace; preserve catalog eligibility, policy and user consent. **Proof:** signed-in request, actual tool action, verified output.
- [ ] **KCON-470** Validate `WorkflowRuntime` → Medusa/Deep Agents on a controlled opt-in tenant and installed model; no rollout of disabled-by-default Deep Agents merely to animate UI. **Proof:** actual delegated task, cancellation, failure, durable status.
- [ ] **KCON-471** Define a single objective/plan/run/step lifecycle, including budgets, retries, timeout, checkpoint provenance, restart and resume restrictions. **Proof:** multi-worker and interrupted-run test.
- [ ] **KCON-472** Restrict subagents to valid graph tasks; enforce allowed agents, tools, per-step budget, tenant identity and action gate after each delegation. **Proof:** hostile subagent, bad scope and denied tool tests.
- [ ] **KCON-480** Store verified outputs/artifacts in existing governed repositories; show accepted, partial/failed and not-run results honestly. **Proof:** artifact integrity, ownership and download.
- [ ] **KCON-490** Connect Planner, Tasks, Jobs and scheduled runs to chat actions through existing service APIs; authorization and persistence remain server-owned. **Proof:** create/modify/delete, real schedule, stop, replay and denial.
- [ ] **KCON-495** Verify no shadow agent execution authority in legacy `agents/agent_orchestrator.py`, old copilot providers, LangGraph delegates or client action handlers. **Proof:** imports/route/call audit; retire after safe coverage.

### Wave 6 — Native tools, approvals, MCP, skills, sandbox and channels (P1)

- [ ] **KCON-410** Add SDK native tool renderers for observed canonical tool calls and statuses, with typed, bounded name/arguments/results and default safe fallback. **Proof:** legitimate/tool-error/unknown-tool/live-replay contracts.
- [ ] **KCON-420** Add frontend tools only for bounded UI-local intents; privileged mutations execute through existing authenticated backend action gates with fresh policy/RBAC/tenant validation. **Proof:** forged client state and revoked capability negative tests.
- [ ] **KCON-430** Bind native interrupt/HITL form/confirmation to existing ApprovalService, immutable action digest, one-shot consumption, expiration and exact-run reauthorization. **Proof:** approve/reject/expire/replay/race tests, visible pending state after refresh.
- [ ] **KCON-440** Project safe scoped app context with native CopilotKit state hooks only after schema/byte-limit validation. State snapshots/deltas are presentation hints, not persisted truth or action permissions. **Proof:** malicious state, oversized input and cross-tenant denial.
- [ ] **KCON-500** Inventory actual existing MCP clients/registry and extension PluginKernel. Add/update only canonical manifest-backed adapters; do not create another MCP registry or client credential cache. **Proof:** discovery/connect/deny/timeout/disable tests.
- [ ] **KCON-510** Map skill manifests/prompt contracts/capability eligibility to task decisions and persona resource references without granting persona ownership of tools. Verify installed skill capability against live health. **Proof:** version/permission/schema and real execution receipt.
- [ ] **KCON-520** Audit sandbox isolation for filesystem, command execution, code runners, MCP Apps and external artifact processing; enforce per-run tenant, egress, secrets, quotas, cleanup and audit. No sandbox allocated just for selecting persona. **Proof:** escape, secret, cross-tenant, timeout, cleanup tests.
- [ ] **KCON-530** Choose native file/attachment UX only where SDK and Karen backend support it; validate MIME/size/scanning, model capability, explicit resource scope and post-revocation reads. **Proof:** real image/document upload and denial/quota/browser refresh.
- [ ] **KCON-540** Preserve browser/local dictation via current Karen port until a native SDK replacement proves permission, cancellation and draft fidelity. **Proof:** permitted/denied mic, long speech, stop/navigation, browser.
- [ ] **KCON-550** Map optional CopilotKit Channels SDK to existing ChannelHost/ChannelAdapter and owned inbox/outbox; verify signed ingress, identity linking, approval, redaction, delivery retries and no second hosted agent. **Proof:** one real channel + browser readback before broad rollout.
- [ ] **KCON-551** Validate explicit opt-in for managed Channels/Intelligence features; core local chat, models, memory and governance must work without hosted license/API key. **Proof:** offline/local-first and disabled-key tests.

### Wave 7 — Generative UI, grounding, artifacts and response quality (P0/P1)

- [ ] **KCON-700** Verify natural-language text response through CopilotKit with no internal metadata leakage, valid Markdown, copy, citations and accessible typography. **Proof:** real first turn, long answer, partial stream, replay.
- [ ] **KCON-710** Define a **small reusable** set of bounded presentation primitives (table, comparison, source-list, chart, steps, document/artifact, action/approval, media only where authorized) inside existing `presentation_contract.py` and `KarenPresentationRegistry.tsx`. Avoid one renderer per topic. **Proof:** typed schema and adversarial unknown/oversized/hostile payload. **Progress (MERGED_UNVERIFIED, 2026-11-06):** #671 merged bounded `data.table` Python/React schema and accessibility (22/22 exact-head CI); #672 added canonical source-attested ChatRuntime producer/admission (23/23); #673 merged explicit first-turn CORTEX routing and deterministic search source excerpts with existing consumer browser scenario (24/24); #674 hardened canonical column labels and field-by-field claims (23/23). **Progress (MERGED_UNVERIFIED, 2026-11-06):** PR #680 merged safe source-link rendering and replay/browser link assertions (8/8 CI). **Still open:** authenticated first-prompt/replay pass, richer reusable comparison/chart/steps/artifact primitives, dangerous/oversized payload testing for each new type, and no second renderer.
- [ ] **KCON-711** Prove any A2UI, MCP App or richer generated component is data-only/allowlisted or isolated; no model-authored HTML/JS executable in privileged UI. **Proof:** malicious HTML/URL/protocol, CSP and sandbox tests.
- [ ] **KCON-720** Repair all admitted time/weather/date/planner first-prompt cards and verify exact equality after durable history reload. **Proof:** real tool observations, first prompt, reload, denial.
- [ ] **KCON-730** Cover news, current movies, recipes, research summaries, recommendations and comparisons using eligible live tools and reusable component types, not invented evidence. **Proof:** one-prompt table/cards, citations, serialized replay, stale/failure handling. **Progress (MERGED_UNVERIFIED, 2026-11-05):** PR #666 reconciled and merged the authorized search/current-movie first-turn subset, retaining completed-run source attestation and KCON-160 text-only continuation. #659 closed as superseded; exact-head Main Quality, Chat Burn, Presentation, Cognitive and PostgreSQL CI passed. **Progress (MERGED_UNVERIFIED, 2026-11-05):** PR #668 merged the existing signed-in, exact-revision consumer Playwright matrix for natural news/current movies, proof-bound first-send cards, exact source URL equality after reload and no duplicate run; also added CORTEX live-routing tests, increased only the protected browser job time budget, and repaired architecture test job-boundary parsing. Main Quality Gate, Chat System Burn, frontend build and Production Deployment Contract passed at exact head `f29b8a98`. **Deployment update (2026-11-06):** Earlier Vercel rate limiting was superseded by an independently confirmed READY production build for exact `main@6e3fd07b85793408e3a3c69e1e5165c9cb363740` (deployment `dpl_Ag3VDwkUpyPJ1iioLjGCYbTMuCeE`). This does not prove the auth-protected browser journey; backend proxy `GET /api/auth/first-run` recorded `AbortError` on this deployment. **Required signoff:** After an exact main SHA is actually deployed, run the existing GitHub Actions workflow **KAREN Browser Acceptance** on `main`, `scenario=copilotkit-consumer`, `target_sha=` the full 40-character deployed main SHA. Record workflow run URL, deployment SHA, evidence and denial results here. **Progress (MERGED_UNVERIFIED, 2026-11-06):** #671–#673 added canonical read-only tables, authorized source-backed runtime projection and first-prompt CORTEX search-table routing; #673 passed 24/24 CI and merged. #674 validated and merged field/heading attestation (23/23). #675 merged the protected first-run backend readiness preflight, and #677 merged canonical request-scoped auth database session reuse. Render startup still fails its production environment requirements; authenticated deployed browser proof remains NOT_RUN. **Still open:** authenticated live browser pass, real provider freshness/denial, recipes, comparisons, reusable media primitives and KCON-160 long-thread browser proof. Do not check this box yet.
- [ ] **KCON-740** Decide whether A2UI/MCP Apps are required for consumer launch; otherwise DEFER with explicit risk and documented API compatibility/sandbox gate. **Proof:** security assessment and exact SDK support matrix.
- [ ] **KCON-750** Preserve canonical citation/source IDs and safe external links from runtime through stream and reload; block model-generated fabricated sources. **Proof:** grounded-vs-forged source, deleted source, URL safety. **Progress (MERGED_UNVERIFIED, 2026-11-06):** #670 aligned Python/React URL safety (23/23 CI), #672 bound rows to verified URLs/source values (23/23), #674 fixed malicious labels/title spoofing and per-field mapping (23/23). **Still open:** signed-in browser provenance/replay, real provider adversarial denial and deleted/revoked source behavior.
- [ ] **KCON-752** Prove canonical production migration history is consistent with the reviewed release; unknown or duplicate applied Supabase versions must fail closed, missing migrations must remain pending, and migration read errors must not expose credentials. Keep `MigrationValidator` read-only and `supabase/migrations` the sole schema authority. **Proof:** exact-head tests for valid, pending, unknown, duplicate and error/redaction, plus protected read-only migration 43–46 status against the actual deployed PostgreSQL database. **Progress (SOURCE_ONLY, 2026-11-06):** PR #684 candidate hardens validator/test contracts; CI and live Render schema proof pending. No release checkbox until internal production inspection succeeds.
- [ ] **KCON-760** Reuse existing artifact/export/print capability only after backend ownership/format/access checks. **Proof:** output is identical to verified server artifact, with correct MIME and permission.
- [ ] **KCON-770** Treat failures as honest outcomes: no "success" for empty model text, missing image, unsupported card, partial run, failed persistence or unavailable tool. Render useful source-backed text when rich UI alone fails safely. **Proof:** fault matrix + screenshot.
- [ ] **KCON-771** Verify user-selected persona and layout preferences do not change facts, evidence scope, privacy or provider permission. **Proof:** same evidence under multiple personas and layouts.

### Wave 8 — Security, data controls and observability (P0, continuous)

- [ ] **KCON-600** Threat-model all CopilotKit request/response fields: `tools`, `state`, `context`, `forwardedProps`, run/thread IDs, redirects, headers, cookie forwarding and XSS. Reject unauthorized nonempty fields until specifically gated by typed server policy. **Proof:** hostile browser request suite.
- [ ] **KCON-601** Reject AG-UI redirect re-POST to off-origin destinations; fixed backend origin, no client-controlled URLs and request-scoped credential forwarding. Check actual installed AG-UI SDK behavior, not old issue claims. **Proof:** controlled 301/302/303/307/308 hostile redirect test.
- [ ] **KCON-602** Test permissions at *final side effect*, including admin/tool/approval/channel/sandbox/extension execution; protect session and user/tenant isolation under concurrent requests. **Proof:** RBAC + RLS + mutation denial.
- [ ] **KCON-603** Check secrets and sensitive evidence never appear in prompts/traces/SDK event payloads or tool UI; external results are untrusted instructions. **Proof:** seeded secret and prompt-injection negative tests.
- [ ] **KCON-604** Validate run lifecycle cancellation is lease-fenced, per-tenant, exact-run, idempotent and terminal truth reflects committed results, not a client abort. **Proof:** live multi-worker, blocked-provider stop, crash and cancel race.
- [ ] **KCON-650** Emit/read structured `request_id`, `correlation_id`, tenant/user/session/conversation, intent, persona revision, route, plan, provider/model, fallback, skill/tool/plugin IDs, progress and memory recall count. **Proof:** sampled end-to-end trace with redaction.
- [ ] **KCON-651** Measure p50/p95 time-to-first-token, total latency, startup overhead, cancellation success, model calls, tool success, replay failures, first-prompt presentation, UI engagement and eval quality per topology. **Proof:** baseline-vs-change dashboard and reproducible queries.
- [ ] **KCON-652** Surface safe consumer-facing receipts and errors, leave developer detail in authorized diagnostics. No synthetic success or claims of model intelligence from a source observation. **Proof:** UI contract and actual trace parity.

### Wave 9 — UX / visual / accessibility / deployment / cleanup (P0 for release)

- [ ] **KCON-900** Perform signed-in human UX review on desktop/tablet/mobile: navigation, layout, font sizes, scroll parity, sticky composer, focus, keyboard, reduced motion, loading/error states, colors, contrast, message density and tool discoverability. **Proof:** screenshots + manual report at deployed SHA.
- [ ] **KCON-901** Confirm first-time user can discover and execute Chat, Personas, Agent tasks, Planner, registered tools, model selection, Settings, history, voice and available presentation without seeking hidden admin pages. **Proof:** 10 real consumer scenarios with success receipts.
- [ ] **KCON-902** Respect offline/local-first degradation, feature flags, unavailable provider/tool and reconnect without dishonest generated answers. **Proof:** controlled network/drop, disabled-feature and outage tests.
- [ ] **KCON-910** Preserve reproducible pnpm/npm lock authority and SDK stylesheet compatibility; no wholesale Tailwind/React upgrades solely for CopilotKit. **Proof:** clean install, typecheck, tests, bundle and CSS screenshot.
- [ ] **KCON-920** Require exact-head Main Quality Gate, Chat System Burn, Presentation Contract, production auth, migration/schema and front-end tests. Ensure path triggers cover changed scoped files. **Proof:** CI run URLs at one SHA.
- [ ] **KCON-930** Require real PostgreSQL, real enabled model, authenticated AG-UI browser stream, actual tool/agent action, saved/replayed presentation, tenant denial and cancellation tests; no skipped test counted green. **Proof:** clean live acceptance artifacts.
- [ ] **KCON-940** Run remaining complete-loop scenarios: cold boot, warm chat, long thread, reload, persona switch, model request, tool, approval, artifact, provider failover, crash, worker restart, cross-tenant attack. **Proof:** pass/fail ledger and screenshots.
- [ ] **KCON-950** After successor equivalence, audit/decommission replaced assistant-ui, deprecated `agents/agent_orchestrator.py`, old CopilotKit pseudo-provider, duplicate API shims and redundant formatter/renderer code **one artifact at a time**; preserve migrations, RBAC, auth and audit. **Proof:** purpose → replacement → import/reference search → deletion commit → tests → risk.
- [ ] **KCON-960** Update stale docs/readmes/help and operator runbooks; report actual available vs staged capabilities, environment flags, known limits and ownership. **Proof:** versioned documentation review.
- [ ] **KCON-970** Human consumer-readiness signoff before production rollout/distribution; exact deployed revision, browser proof and rollback verified. **Proof:** signed human review + release evidence.
- [ ] **KCON-980** Close initiative only when **every required checkbox** is DONE or explicitly marked DEFERRED by a documented product decision; no open P0, no bypassed security gate, no unresolved first-prompt/replay loss. **Proof:** final review against this document.

## 5. Mandatory acceptance matrix, real user prompts

All cases start from a **fresh authenticated browser** and **one user action** unless explicitly marked as follow-up. Compare text, observed tool/model receipt, state, database records, stream, reload and any permitted screenshot. Never infer actual tool execution from a badge.

| Scenario | Expected observed behavior | Required owner evidence |
|---|---|---|
| "Hello" and a follow-up | Fast model answer, continuous context, no agent activity falsely implied | prompt/provider trace, 2-turn readback |
| "What time is it?" | Verified local clock, natural explanation, valid first-turn card | successful time capability + same restored envelope |
| "Weather now" | Authorized observation or honest unavailable | tool evidence, no invented forecast; replay |
| "Latest news" and "New movies" | Retrieved dated sources with truthful publication context and first-turn cards | source IDs/URL bounds, #659 disposition |
| "Give me a recipe" | Complete usable recipe, optional structured steps without fake ingredients | model/task output contract; verified renderer |
| "Explain this deeply" + explicit model | No unexpected loss of reasoning topology; quality not downgraded by provider selection | decision/allowed reasoner/provider trace |
| "Create Troy and use my approved brand guide" | Safe persona save/activate, purpose-aware answer and scoped resource read | revision, applied fields, authorized evidence |
| "Switch to Kent and review my repo" | New persona scope without leaking Troy; optional governed repository tools | persona snapshot + tenant gates |
| "Audit repo and run tests" | Agent plan, truthful steps, tool execution and verified outcome from ordinary chat | Medusa step IDs, tool receipts, artifact |
| "Change my planner deadline" | State preview and required approval, one canonical write | approval nonce, database receipt, replay |
| Stop mid-generation | One exact-run cancel with honest pending/terminal status | durable lease/run ID and no late false success |
| Refresh after tool + UI card | Same canonical messages, approved rich content and receipts, no new LLM call | byte-for-byte evidence envelope, zero mount runs |
| Legacy/unknown rich history | Owner-authorized text readable; unsafe rich withheld; safe continuation only when backend protocol verified | 409 recovery, denial, continuation tests |
| Login as another tenant | No restored thread, persona, draft, memory, tool or run from prior principal | RLS + browser isolation |
| Offline/provider down | Visible degraded/unavailable status, preserved unsent draft, no fake assistant answer | circuit/fallback/persistence telemetry |
| Voice, image/file and mobile | Controls only for supported options; correct permissions and responsive focus | voice/upload owner tests + human UX |

Required nonfunctional budgets: fix **measured** current baseline first. Set provisional SLOs (p50/p95 TTFT, turn success, crash-free runs, history restoration success, accessible flows) in an operator-approved config/quality contract after 10+ representative cold/warm traces; do not invent absolute latency benchmarks without real hardware/provider measurements.

## 6. Exact proof commands and scope notes

Execute at the actual candidate SHA and report pass/fail/not-run. These are entrypoints, **not** a claim they were executed while authoring this ledger.

Backend, from repository root:

```bash
python -m compileall -q src server scripts
pytest tests/architecture/test_copilotkit_migration_wiring.py -q
pytest tests/core/runtime/test_persona_execution_snapshot.py tests/core/runtime/test_persona_prompt_authority.py -q
pytest tests/core/runtime/test_chat_runtime_stream_contract.py tests/api_routes/test_owned_history_projection.py -q
pytest tests/agent_medusa/ -q
pytest tests/services/test_persona_activation_single_authority.py tests/services/test_persona_atomic_activation.py -q
pytest tests/core/runtime/test_verified_weather_presentation.py -q
pytest tests/architecture/test_response_lifecycle_ownership_contract.py -q
ruff check src tests
mypy src
docker compose config
```

Frontend, from `src/ui_launchers/Karen-AI-Theme`; verify currently defined scripts/package manager before execution:

```bash
npm run lint
npm run typecheck
npx vitest run
npm run build
npx playwright test e2e/karen-copilotkit-native-acceptance.spec.ts e2e/karen-copilotkit-protocol-acceptance.spec.ts e2e/kchat-workspace-continuity.spec.ts
```

Existing CI ownership: `main-quality-gate.yml`, `chat-system-burn.yml`, `presentation-contract.yml`, `beta-release-gate.yml`, auth-security and dedicated browser runs. **Observed real-model/postgres/production claims require correctly provisioned test infrastructure**. Mock tests, skipped browser tests, a green source-level contract or a provider health probe are insufficient for release proof. Record each actual workflow run ID and associated SHA alongside task closure.

### Required PR update and retirement scorecard

Every scoped implementation PR must show:

```text
Ledger IDs: KCON-...
Existing owner reused:
CopilotKit feature adopted (exact v2 import/version):
Karen behavior retained:
Changed files / existing aliases removed:
User-visible capability / eligibility / disabled behavior:
Schema/API migration impact:
Auth / tenant / RBAC / consent / audit impact:
Streaming / persistence / replay / stop impact:
Telemetry / requested-vs-actual model impact:
Tests run (command, run URL, exact SHA, pass/fail/not-run):
Real model / PostgreSQL / browser proof (or explicit NOT_RUN):
Stale refs and deletion audit:
Ledger checkbox state + remaining blockers:
Merge / rollout / rollback:
```

**Continuous update rule:** scoped code changes without a corresponding edit to this canonical file must fail the existing Main Quality Gate. The CI guard should be narrow and path-based so unrelated repository work is not forced into the initiative; this is *process enforcement*, not a new configuration or runtime. A documentation-only PR may refresh evidence without changing source. If multiple PRs overlap, rebase/resolve and update from latest merged ledger before merging.

## 7. Risks, sequencing and decisions to revisit

- **High-level controller:** `CopilotChat` auto-run may break zero-inference history boot; status is evaluation pending, not a mandate to swap. Preserve `CopilotChatView` if high-level cannot provide safe equivalent behavior.
- **SDK-vs-runtime:** SDK components can improve UX, not intrinsically intelligence. Prompt, context, model and CORTEX fidelity must be proven separately.
- **Legacy replay:** strict verification is valuable, but must not strand an entire saved conversation. Data recovery and safe continuation are distinct stages.
- **Agentic readiness:** a disabled or unverified Deep Agents adapter is not an implemented user capability. Do not display fake agent steps.
- **Persona specialization:** avoid authority escalation through free-text `system_prompt`; expand governed task-purpose *data* to PromptRuntime with precedence and tests.
- **Tool/MCP/App UI:** MCP Apps, A2UI and frontend tools are optional native possibilities, not a license to execute user-supplied code or bypass backend gates.
- **Channels:** existing channel host is the owner. CopilotKit managed runners must be opt-in and not required for local chat.
- **CSS/build:** preserve Karen's existing design tokens/scroll/typography and security policy, with pinned package verification before upgrades.
- **Parallel PRs:** PR #659 may edit presentation contracts; don't reimplement its scope on this branch. Resolve against current main and update one ledger row instead.

## 8. Progress change log (append only concise evidence entries, not duplicate plans)

| Date | Main/candidate SHA | What changed / observed | Affected IDs | Proof / next gate |
|---|---|---|---|---|
| 2026-11-05 | `main@66c8913e` | Consolidated earlier static plan into this one living ledger; no runtime/code/browser acceptance claimed; CopilotKit view and source-level runtime mapped | KCON-001–980 baseline | Source review only; all implementation task checkboxes remain open pending task-specific proof |
| 2026-11-05 | `main@66c8913e` | #648 and #658 previously merged; first-prompt cards/replay remain unverified in deployed consumer browser; #659 open | KCON-160, 260, 720, 730 | Exact-head authenticated browser + #659 conflict/CI disposition |
| 2026-11-05 | `main@f200a885` | #661 merged verified text copy and explicit *new* canonical conversation handoff, not same-thread continuation | KCON-160 | Main Quality, Chat Burn, Presentation Contract green on PR head; deployed browser remains NOT_RUN |
| 2026-11-05 | `fix/kcon160-owned-transcript-pagination-20261105` | Candidate: paged owner-scoped canonical text projection after 500 saved entries with revision checking; no rich SDK hydration | KCON-160 | CI and browser/postgres proof pending; original-thread resume still blocked |

| 2026-11-05 | `main@69609802` | PR #662 merged paginated text recovery with independent 502/503 fallback; per-page owner checks and best-effort timestamp only | KCON-160 | Main Quality, Chat Burn, Presentation, live PostgreSQL and Plugin Ecosystem passed at PR head; same-thread SDK continuation remains NOT_DONE |
| 2026-11-05 | `fix/kcon130-copilotkit-native-run-message-filter-20261105` | Candidate uses CopilotKit 1.79.1 native outbound-only messageFilter, not a new transport/controller; no browsing or runtime execution proof yet | KCON-130, KCON-160 | Shell and architecture tests, exact-head CI required; live >50-turn send/stop remains NOT_RUN |

| 2026-11-05 | `main@e0ce4ceb` | #663 merged native pinned CopilotKit messageFilter; prevents resending saved client transcript while maintaining canonical runtime authority | KCON-130, KCON-160 | Main Quality, Chat Burn, Presentation Contract passed at PR head; full browser long-thread parity NOT_RUN |
| 2026-11-05 | `main@c7b43788` | #664 merged owner-attested opt-in continuation of the original chat as text, without replay of unsupported rich content; canonical chunk correlation contract repaired | KCON-160 | Main Quality, Chat Burn, Presentation, Context, Reasoning, live PostgreSQL and Vercel green at PR head; real browser remains NOT_RUN |

| 2026-11-05 | `feat/kcon160-canonical-recent-window-20261105` | Candidate: latest 500 owner-verified saved messages with older-history disclosure, sourced from existing repository instead of an invented separate transcript | KCON-160 | Python/Next/React/PostgreSQL test contracts and exact-head CI pending; browser and immutable version still NOT_RUN |

| 2026-11-05 | `main@9a3a6f14` | #665 merged bounded attested recent-window continuation for 1000+ saved messages; all prior history stays canonical | KCON-160 | Main Quality, Chat Burn, Presentation and PostgreSQL proof passed at PR head; deployed browser and immutable snapshot NOT_RUN |
| 2026-11-05 | `feat/kcon730-governed-search-first-turn-converged-20261105` | Reconciled legacy draft #659 into current canonical presentation/runtime/replay contracts; retained KCON-160 text-only controls and CI ledger enforcement | KCON-730, KCON-720 | Exact-head CI and real-model/browser acceptance NOT_RUN; retire draft #659 only after integrated PR merges |

| 2026-11-05 | `main@c039d844` | #666 merged authorized first-turn search/current-film presentation with source-attested persisted replay; old #659 closed as superseded, no duplicated renderer or history path | KCON-730, KCON-720 | Main Quality, Chat Burn, Presentation, Cognitive, PostgreSQL, frontend and Vercel green on #666 head; live authenticated browser remains NOT_RUN |

| 2026-11-05 | `main@07be5297` | #668 merged protected signed-in first-prompt news/current movie acceptance specs and stable workflow-boundary tests without adding a renderer or runtime; seven supported presentation types remain source-governed | KCON-730, KCON-750 | Main Quality, Chat Burn, frontend build, deployment contract green at #668 head; Vercel deployment rate-limited; live deployed browser NOT_RUN |

| 2026-11-06 | `main@538ad60b` | PR #670 merged aligned backend/browser source-link validation; 23/23 exact-head checks passed, no renderer or provider changes | KCON-710, KCON-730 | Live authenticated browser NOT_RUN; generic table/comparison still missing from deployed main |

| 2026-11-06 | `main@ecdd2720` | PR #671 merged bounded read-only `data.table` in canonical Python/React presentation registry and existing composition. Exact-head 22/22 checks passed. | KCON-710, KCON-730 | Real source producer, deployed first-prompt browser, replay and release signoff NOT_RUN |

| 2026-11-06 | `main@be3e5e0f` | PR #672 merged: source-authorized `structured_table` projection through canonical ChatRuntime receipt gate, per-row URL and source-field attestation. Exact-head 23/23 CI checks passed | KCON-710, KCON-730 | Live source generation and authenticated deployed first-prompt/replay signoff NOT_RUN |

| 2026-11-06 | `main@6e3fd07b` | PR #673 merged source-attested first-prompt search tables, CORTEX live routing, bounded UTF-16 excerpts, and existing signed-in consumer browser acceptance matrix; exact-head 24/24 CI checks passed | KCON-710, KCON-730 | Vercel production deployment READY for exact SHA `6e3fd07b85793408e3a3c69e1e5165c9cb363740` (`dpl_Ag3VDwkUpyPJ1iioLjGCYbTMuCeE`, aliases assigned); authenticated deployed browser first prompt/replay NOT_RUN; no verified cross-source comparison facts |

| 2026-11-06 | `main@abfa3245` | PR [#674](https://github.com/agustealo/AI-Karen/pull/674) merged canonical source-table column/field attestation and runtime-owned title; 23/23 exact-head CI checks passed | KCON-710, KCON-730, KCON-750 | Authenticated browser first-send/replay NOT_RUN; production error investigation remains open |

| 2026-11-06 | `main@87089332` | PR #675 merged protected deployment preflight for `/api/auth/first-run`, requiring a real initialized boolean state after backend readiness | KCON-160, KCON-730, KCON-750 | Source preflight merged; Vercel backend `AbortError` remains observed; authenticated browser acceptance NOT_RUN |

| 2026-11-06 | `main@2545aaf7` | PR #677 merged canonical context-scoped auth DB session reuse for first-run checks and statistics; 11/11 exact-head checks passed | KCON-160, KCON-730 | Backend deployment of this SHA unverified; runtime timeout causality and signed-in browser acceptance NOT_RUN |

| 2026-11-06 | `Render ai-karen-beta-api` | Deployment configuration audit: service pinned to `feat/chat-consumer-conversation-management-20261031` with auto-deploy off; last three attempts `update_failed` after successful Docker builds. Latest recorded startup on Nov 1 at commit `2cdcdab0` exits before Uvicorn binds any port because production settings reject missing `KARI_DUCKDB_PASSWORD`, `KARI_JOB_ENC_KEY`, `KARI_JOB_SIGNING_KEY`, `KARI_MODEL_SIGNING_KEY`, `SECRET_KEY`, `AUTH_SECRET_KEY`, `DATABASE_URL`, `POSTGRES_URL`, `AUTH_DATABASE_URL`, `REDIS_URL`, `EXTENSION_SECRET_KEY` and `EXTENSION_API_KEY` | KCON-160, KCON-730, KCON-750 | BLOCKED: provision authorized real production secrets/connections using Render environment controls; confirm deployed branch/SHA, boot, `/ready`, auth first-run and signed-in consumer browser. Do not introduce development defaults or claim this Render service is the Vercel-configured target until target correlation is verified |

| 2026-11-06 | `main@76379b56` | PR #679 merged: existing Render read-only environment inspector now rejects free/expiring PostgreSQL in `inspect-consumer` mode while retaining warnings for beta inspection; exact-head 3/3 CI checks passed; Redis remains an ephemeral STM cache | KCON-160, KCON-730 | Actual free database expires December 1, 2026; Render boot and authenticated browser NOT_RUN |

| 2026-11-06 | `main@a5f22a22` | PR #680 merged: validated public source URL cells are safe clickable links in the existing `data.table` renderer; persisted replay and hostile-link tests, plus signed-in browser assertions added; 8/8 exact-head checks passed | KCON-710, KCON-730 | Deployed signed-in first-send/replay NOT_RUN; Render FastAPI startup still blocked by required production configuration |

| 2026-11-06 | `fix/kcon-consumer-render-exact-live-sha-20261106` | Candidate: existing protected `inspect-consumer` preflight now requires read-only newest Render deployment to be `live` on exact reviewed main SHA, independently of env configuration, DB durability, migrations and browser proof | KCON-160, KCON-730, KCON-750 | Exact-head CI PENDING; real Render deploy remains failed/legacy branch, browser NOT_RUN; no deployment or secret mutation |

| 2026-11-06 | `main@1c496a64` | PR #682 merged existing read-only `inspect-consumer` latest Render deployment status and full expected main SHA verification; latest seven main commit checks successful. The currently observed canonical header previously lagged #675; #676 is a superseded old ledger-only PR, not a merge candidate. No Render apply/deploy or browser run verified in this audit | KCON-160, KCON-730, KCON-750, KCON-920, KCON-970 | Next: protected Render reconcile `apply` only on current reviewed `main` (manual approved workflow); then inspect-env, provision genuine production config and non-expiring PostgreSQL with operator approval, deploy explicitly, inspect-consumer on exact live SHA, verify auth/migration, and execute signed-in browser acceptance. Vercel/Render target link remains unverified |

| 2026-11-06 | `fix/kcon752-migration-history-fail-closed-20261106` | KCON-752 candidate: existing read-only `MigrationValidator` now rejects unexpected or duplicate Supabase history versions and returns credential-safe error classifications instead of raw DB exception details. Parameterized tests cover valid, missing, unknown, duplicate and connection-failure paths. Render still tracks Oct 31 branch, newest deployment failed, protected reconcile not run; PostgreSQL connection stays private | KCON-160, KCON-752, KCON-920 | SOURCE_ONLY, exact-head CI pending. Does not attest live Render schema, migration 43, durable Postgres, production boot or signed-in browser; retain release block |

**Maintenance note:** append *one short changelog entry per merged slice*, update the existing task row and checklist, and remove resolved blockers. Do not append a competing implementation plan, repeat the full matrix in PR comments or quietly check boxes on the strength of green mocks.

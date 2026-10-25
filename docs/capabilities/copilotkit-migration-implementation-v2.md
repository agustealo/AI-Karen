# CopilotKit-first migration: source-verified adversarial implementation plan v2

**Status:** Design and evidence audit; no frontend migration or SDK install claimed.
**Repository:** agustealo/AI-Karen
**Scope:** CopilotKit UI/agent interactions, AG-UI, canonical Karen runtime, plugin/Channels, approvals, historic cleanup and consumer UX.
**Decision:** CopilotKit takes precedence for overlapping *interaction* capabilities; Karen's governed execution/memory/persistence stays authoritative.
**Companion:** `docs/architecture/decisions/2026-10-25-copilotkit-first.md`, `docs/capabilities/copilotkit-legacy-retirement.md`, PR #553 capability baseline.

## A. Verified repository owners and architectural consequences

| Domain | Verified implementation | Canonical disposition |
| --- | --- | --- |
| Chat execution | `src/ai_karen_engine/core/runtime/chat_runtime.py` | All inference, provider/model selection, fallback, prompts, streams, persistence/degradation receipts remain here |
| AG-UI backend ingress | `src/ai_karen_engine/api_routes/chat/runtime.py` | Reuse; thin, authenticated, policy-governed; do not create another direct agent endpoint |
| AG-UI projection | `src/ai_karen_engine/core/runtime/ag_ui_event_projection.py` | Preserve event provenance, stream lifecycle and terminal integrity |
| AG-UI frontend proxy | `src/ui_launchers/Karen-AI-Theme/src/app/api/chat/ag-ui/route.ts` | Preserve auth header sanitization, response IDs, abort/terminal/SSE checks |
| AG-UI config | `src/ai_karen_engine/config/runtime.py` `FeatureFlags.enable_ag_ui_bridge=False` | Explicit authorized enablement and negative testing required; never override in React |
| Current chat mount | `src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx` | One active chat mount, cut over with a centrally governed feature gate |
| Current chat | `src/ui_launchers/Karen-AI-Theme/src/components/chat/assistant-ui/KarenAssistantChat.tsx` | Capture every consumer contract and replace rendering after parity |
| Conversation state | `src/ui_launchers/Karen-AI-Theme/src/components/chat/SessionProvider.tsx` | Reuse canonical session identities, bootstrap deduplication and APIs; no second conversation store |
| Persona, model, voice, history | `src/components/chat/assistant-ui/KarenPersonaSelector.tsx`, `KarenComposerRuntimeCatalog.tsx`, `KarenBrowserDictation.tsx`, `KarenLocalDictation.tsx`, `KarenHistoryRestoration.ts` | Move behavior into CopilotKit slots/adapters; do not throw away available functions |
| Presentation and rail | `KarenPresentationRegistry.tsx`, `KarenWeatherPresentation.tsx`, `observedAgentSteps.ts`, `src/components/chat/ConversationContextRail.tsx` | Reuse evidence-bound data schemas and layout; change rendering adapter, not canonical presentation meaning |
| UI design system | `src/ui_launchers/Karen-AI-Theme/src/app/globals.css`, `tailwind.config.ts` | Preserve the existing HSL tokens, dark theme, typography, breakpoints and three-panel composition |
| Plugin catalog/execution | `src/ai_karen_engine/extensions/plugin_kernel.py`, `extensions/platform/core/registry/plugin_registry.py`, `extensions/registry.py` | Single extension manifest/catalog/execution authority; do not add another plugin registry |
| Extension packages | `src/ai_karen_engine/extensions/plugins/*/manifest.json` | Existing package convention; reuse validator, permission and lifecycle contracts |
| Channel adapter contracts | `src/ai_karen_engine/extensions/channels/contracts.py` | Use current ChannelAdapter and native event/identity/delivery schema, extend only if needed |
| Channel host | `src/ai_karen_engine/services/channels/{host,activation,linking,ingress,execution,delivery,worker,credentials}.py` | ALREADY IMPLEMENTED host/ingress/worker lifecycle. CopilotKit Channels is a transport/native-UI adapter, not a replacement host |
| Channel persistence | `src/ai_karen_engine/persistence/repositories/channel_repository.py` | Durable inbox/outbox, identity and tenant ownership remain |
| Channel config | `src/ai_karen_engine/config/channels.py` | `ChannelHostSettings` disabled by default with validated installation/credential policy |
| Approval authority | `src/ai_karen_engine/services/approvals.py` | Reuse runtime-owned approval lifecycle and request fingerprinting |
| Approval store | `src/ai_karen_engine/persistence/repositories/approval_repository.py` | Reuse tenant-scoped durable one-shot approval receipts and RLS; no duplicate database |
| Approval API | `src/ai_karen_engine/api_routes/automation/approvals.py` | Reuse for policy-authorized approval decisions; no side effects in HTTP/controller |
| Plugin UI | `src/ui_launchers/Karen-AI-Theme/src/components/plugins/`, `src/ui_launchers/Karen-AI-Theme/src/plugin_host/` | Existing consumer plugin installation and navigation, never mount a new second plugin store |

These paths were read or enumerated from GitHub `main` on 2026-10-25. Existence is **not** live availability, package compatibility or readiness proof. Where a document says the plugin/approval owners are unknown, this table supersedes it.

## B. Confirmed adversarial issues

### P0-01: Duplicate chat execution and premature UI cutover
A second CopilotKit Runtime may be needed as a *thin SDK transport facade* but may not own providers, prompts, model selection, tools, memory, thread persistence or policy. Evaluate whether the current AG-UI endpoint can be used directly by the pinned v2 SDK; if not, create one authenticated, bounded bridge. Do not add another general chat API or node-based agent.

### P0-02: Disabled AG-UI backend behind a seemingly functional frontend
The runtime's `enable_ag_ui_bridge` defaults false. Define opt-in configuration and backend health/eligibility display before mount. Test disabled/unknown/misconfigured/allowed states and avoid client-side configuration overrides.

### P0-03: Existing conversation bootstrap versus CopilotChat automatic run
Current SessionProvider deduplicates conversation boots. CopilotChat v2 documentation describes running an agent on initial mount when not run; that behavior must not generate unintended initial answers, duplicate writes, reset session IDs or clear unsent drafts during transitions. Validate real installed SDK behavior and select the supported configuration/slot strategy.

### P0-04: Current design tokens conflict with CopilotKit v2 CSS expectations
Karen uses Tailwind 3 + HSL variables; CopilotKit v2 documents Tailwind 4/shadcn-style OKLCH scoped tokens. DO NOT upgrade the whole application to Tailwind 4 as a precondition unless necessary and regression-proven. First test isolated stylesheet import and scoped token conversions without overwriting Karen's global token values. Preserve sidebars, right rail scrolling, sticky composer, responsive breakpoints, font sizes, contrast and focus rings.

### P0-05: Existing Channels lifecycle could be forked
Canonical PluginKernel, ChannelHostSettings, ChannelIngressService, ChannelExecutionService, SqlChannelRepository, workers and ChannelAdapter contracts already exist. Building a new OpenTag-shaped channel runtime, manager, queue, retry worker, secret store, or conversation mapping would violate DRY/local-first. Use CopilotKit Channels SDK and OpenTag patterns as *adapter implementation inputs*, with explicitly mediated optional managed runner. Native cards cannot assert execution or persistence success.

### P0-06: Approvals already exist; frontend controls cannot become authority
ApprovalService/SqlApprovalRepository and runtime approval policy are real. Map CopilotKit `useHumanInTheLoop`/interrupt affordances to existing approval ID/state/transitions. Distinguish a chat execution approval from a granular side-effect tool approval before reusing the exact same contract; extend the canonical owner only when the schema cannot represent the necessary audited action. Test expiration, revocation, replay, one-shot consumption, concurrent approval and post-approval reauthorization.

### P0-07: Live/restored/streaming data parity could be lost
`KarenHistoryRestoration.ts` reconstructs `karen.presentation.v1` and `karen.execution_receipt.v1` parts from authenticated history. New CopilotKit renderers must consume real versioned events and durable history with the same evidence, source/ref and permission checks. Preserve requested versus actual provider/model and degradation metadata. Don't claim completion on RUN_FINISHED without canonical result.

### P0-08: Legacy removal can weaken security or delete unique features
Legacy `copilot.py` has compatibility predictors, and `copilotkit/safety_middleware.py` may still contain checks not reimplemented elsewhere. No blanket remove, shim-only replacement, simulated success, or unverified source deletion. Reference audit with runtime mount/manifest checks first; require verified successor, tests, and explicit removal in a follow-up commit within the same workstream.

### P1-09: Documentation and SDK v1/v2 API drift
Official docs have pages with different provider naming between versions; use a pinned `@copilotkit/react-core` version's published types and canonical versioned docs to settle `CopilotKitProvider` versus compatibility `CopilotKit`, `agentId`, `runtimeUrl`, styles and hooks. The v2 `CopilotChat` is in `@copilotkit/react-core/v2`; don't introduce the deprecated v1 `@copilotkit/react-ui` chat accidentally.

### P1-10: Lockfile and package manager drift
Web app has `package.json`, `package-lock.json` and `pnpm-workspace.yaml`. Decide and enforce one install/lockfile authority for reproducible CopilotKit releases; honor existing approved native dependency scripts and CI without blanket trust. Capture bundle output, React/Next/Tailwind compatibility and duplicate AG-UI dependency versions.

### P1-11: Feature inventory and CI fragmentation
PR #553 proposes a conservative capability baseline. Reconcile into one source of product truth and existing tests. Integrate migrations with Main Quality Gate, Chat System Burn, Presentation Contract, plugin-ci, relevant channel/approval tests and Playwright. Avoid a parallel gate not invoked by the canonical workflows.

## C. Non-negotiable UX preservation matrix

| Journey | Karen behavior to retain | CopilotKit replacement strategy | Evidence |
| --- | --- | --- | --- |
| Core chat | Run, cancel, retry, stream, scroll/resize and truthful error | v2 `CopilotChat` or `CopilotChatView` slots | Real authenticated AG-UI browser run and SSE abort |
| Conversation | Create/switch/delete/rename, stable ID, durable reload | Keep SessionProvider + repository; configure CopilotKit thread binding | `karen-durable-history-restoration.spec.ts`, `kchat-workspace-continuity.spec.ts` |
| Composer | Persistent draft, per-run provider and agent request, shared input across views | CopilotKit input slot + existing canonical draft/selection context | Switch pane/persona/reload without loss |
| Persona | Active persona, scope/revision and error truth | Existing selector in CopilotKit slot/toolbar | Authorized selection and scoped response |
| Models | Backend-reported inventory, request vs executed, fallback | Existing catalog component + CopilotKit component slot | Real provider receipt in live and history |
| Voice | Browser/local dictation and cancellation | Retain Karen dictation adapters in composer slot unless CopilotKit equivalent proven | Mic permissions, audio, error and interruption |
| Presentation | Weather/time/research/planner/evidence cards | `useRenderTool`/component slots + canonical `karen.presentation.v1` | Stream, restore, source trust and XSS |
| Agent activity | Medusa/LangGraph real steps, subagents, planning | CopilotKit tool/activity renderer using actual AG-UI events | Same activity IDs/status, no invented steps |
| Right rail | Intelligence cards, right scroll, typography parity, responsive behavior | Preserve Karen rail; CopilotKit occupies chat center only | Responsive screenshot/keyboard checks |
| Approvals | Pending/approve/reject/expire + durable receipts | CopilotKit approval UI; existing ApprovalService backend | One-shot, concurrent, unprivileged negative cases |
| Plugins and Channels | Enable/disable/uninstall, native cards, identity bindings | Existing PluginKernel + ChannelHost with CopilotKit SDK adapter | Real channel message and tenant/RBAC tests |
| Accessibility | Labels, focus, contrast, motion, keyboard | Scoped CopilotKit slots/tokens | axe/Playwright manual checks with screenshots |

UX dimensions to inspect: typography scale, density, line lengths, keyboard focus, scroll restoration, sticky footer/rail, action discoverability, empty/loading/degraded/success states, mobile viewport, reduced-motion, locale, screen readers. Screenshots supplement behavioral tests and must not be manipulated to hide differences.

## D. Implementation stages and acceptance

### CK-00: Baseline and owner reconciliation
- Merge/reconcile #553 only after its static verifier tests pass; preserve all existing features and link original PR decisions.
- Derive actual import, route, manifest, config and state graph from the repository, not filename guesses.
- Bind feature records to existing architecture and browser tests.
- Output: a baseline with known `implemented_unverified` vs `verified` distinctions; no production code changes.

### CK-01: SDK and visual compatibility spike
- In `src/ui_launchers/Karen-AI-Theme/`, validate pinned `@copilotkit/react-core/v2` exports, provider config, built-in `CopilotChat` slots, styles and AG-UI semantics against current React/Next/TS/Tailwind.
- Use package manager's locked install, without duplicating package managers or unnecessarily adding `@copilotkit/react-ui`.
- Test SSR boundary, CSP, bundle, css token conversion, dark/light, fonts and breakpoint screenshots.
- Proof: typecheck, unit tests, build, isolated Playwright captures and import-contract assertions.
- Rollback: dependency-only revert, no active-mount changes.

### CK-02: Canonical AG-UI/SDK connection
- Determine whether pinned v2 frontend speaks directly to `/api/chat/ag-ui`; document exact request/event compatibility and auth propagation.
- If SDK requires CopilotRuntime facade, use *one thin, local-only gateway* with fixed agent registration, bounded envelope, auth/correlation delegation to backend. No independent generator/orchestrator.
- Reuse backend `ChatRuntime`, `AGUIEventProjection` and existing Next proxy. Validate `enable_ag_ui_bridge` server-side.
- Proof: nonstream/stream parity, idempotent cancellation, invalid forwarding, tenant boundary, model request/reported identity, failures and replay.

### CK-03: Parallel rendering comparison without parallel execution
- Build CopilotKit UI under existing frontend app and guarded single mount. Do not run two mounted agents or both send requests.
- Preserve SessionProvider, conversation server truth, default persona, model catalog, voice and contextual rail.
- No independent local conversation cache except transient UI state; use server revision for conflicts.
- Golden tests: conversation creation/restore, cancel/retry, persona switch, provider request, long thread, draft persistence and accessibility.

### CK-04: One-active-mount CopilotKit cutover
- Switch `src/app/dashboard/page.tsx` to a single CopilotKit chat mount only after gates pass.
- Preserve responsive three-column visual arrangement and typography; validate both themes.
- Record before/after screenshots (desktop/tablet/mobile), measured bundle/latency and unchanged server request semantics.
- Then delete superseded assistant-ui component imports and adapter-only modules when reference and behavior audits approve.

### CK-05: Native agentic features and approved actions
- Implement app-context synchronization, suggestions, CopilotKit tool renderers and interrupts through existing governed runtime action APIs.
- Scoped frontend state can describe active document/task and selected panel; canonical backend must validate all privileged IDs/content independently.
- Use ApprovalService and current audit pipeline; no duplicated approval tables.
- Tests: hostile state, forged approval, stale permissions, revocation, expired nonce, concurrent execution, persistence and replay.

### CK-06: Generative presentation
- Keep one `karen.presentation.v1` registry and backend evidence semantics. Adapt the CopilotKit UI renderer, not the model/persistence schema.
- Verify compositional component allowlist, payload/URI budgets, source authenticity, no arbitrary model JS, safe text fallback and accessibility.
- Prove typed data on live AG-UI stream, nonstream, reload and persisted history.

### CK-07: Channels + OpenTag adapter
- Extend canonical ChannelAdapter in the existing `extensions/plugins/` convention and PluginKernel; use OpenTag as reference, not agent code/runner ownership.
- Investigate managed CopilotKit Intelligence or self-operated runner explicitly. Default remains local-first with optional managed delivery, not silently required hosted infrastructure.
- Slack read-only signed event/identity binding first, then native cards, authorized approvals, idempotent write, durable outbox and web-history continuity; Teams afterwards.
- Gate with `tests/extensions/test_channel_*`, webhook transport tests, `tests/integration/test_channel_claim_concurrency_postgres.py` plus live Slack and browser proof.

### CK-08: Reference-audited legacy retirement
- Remove dead `@assistant-ui/react` and `@assistant-ui/react-ag-ui` packages, import paths, obsolete renderers/stores, styles, flags and docs when proven superseded.
- Audit pseudo-provider `integrations/providers/copilotkit_provider.py` and historical `copilotkit/` task/session files for real references and security behavior before retiring.
- No duplicate channel worker, approval service, runtime/route/store or mirrored CopilotKit UI remains.
- Document each deletion's purpose, replacement, references, test evidence, risk and rollback; block resurrection with architecture contracts.

### CK-09: Consumer readiness and distribution
- Run existing CI and real provider/PostgreSQL/browser/channel tests on exact target commit.
- Include screenshot review, visual contrast/typography, keyboard/focus, responsive, offline/unavailable, missing auth, stale session, provider down, feature flag off and worker restarts.
- No release/distribution build until a human validates consumer readiness. No invented success receipts.

## E. Exact proof entry points already in repo

Backend:
```bash
python -m compileall src
pytest tests/api_routes/test_chat_ag_ui_transport.py tests/services/test_approval_service.py -q
pytest tests/architecture/test_runtime_approval_authority.py tests/architecture/test_plugin_runtime_authority.py -q
pytest tests/extensions/test_channel_host_lifecycle.py tests/extensions/test_channel_ingress_service.py tests/extensions/test_channel_execution_service.py -q
pytest tests/integration/test_channel_claim_concurrency_postgres.py -q
ruff check src tests
mypy src
```
Integration test environments (Postgres, channel credentials, live model) must be real when used to claim E2E success; a missing test dependency yields `not_run` or `blocked_environment`, never green.

Frontend (from `src/ui_launchers/Karen-AI-Theme`):
```bash
npm run lint
npm run typecheck
npm test
npm run build
npm run test:e2e -- e2e/karen-durable-history-restoration.spec.ts
npm run test:e2e -- e2e/kchat-workspace-continuity.spec.ts
npm run test:e2e -- e2e/ux-user-journeys.spec.ts
```
Use the resolved package-manager authority and supported CLI arguments in the checked-out project. Review generated screenshots, not just pixel-diff flags.

Existing workflow owners: `main-quality-gate.yml`, `chat-system-burn.yml`, `presentation-contract.yml`, `plugin-ci.yml`, `karen-history-browser-acceptance.yml`, `production-auth-security.yml`, `production-first-boot-smoke.yml`. Update their path triggers when new CopilotKit/channels files affect behavior.

## F. Decision gates

1. **Preserve:** if CopilotKit cannot match a Karen feature without weakening the user journey, keep the feature implemented via Karen extension/slot until it can.
2. **Prefer:** when CopilotKit built-in behavior is equivalent and verified, use it and remove bespoke duplicate UI.
3. **No accidental second owners:** every new source file must name its canonical module owner and who owns persistence, execution, RBAC and telemetry.
4. **Local-first:** external channel delivery may be optional; no mandatory CopilotKit-managed dependency for local chat, model execution, memory or core UI.
5. **No false success:** live request completion, provider identity, persistence and channel delivery claims originate in server receipts.
6. **Retire:** when both old and new implementation work, do not keep both indefinitely. Complete cutover + deletion with green contract tests.
7. **Honest status:** docs/plans vs code-installed vs wired vs E2E verified vs consumer-ready are distinct, always.

## G. New CI contract requirements

- Capability impact: relevant old capability tests are automatically selected when source paths change.
- Forbidden ownership imports: frontend cannot choose provider/fallback or persist memory; routes cannot invoke ungoverned plugins.
- Dependency lock: no duplicate CopilotKit v1 chat, no orphan assistant-ui packages after cutover, one compatible AG-UI graph.
- Approval policy: UI cannot report approved write success from a click or HTTP 200 alone.
- Channel contract: SDK integration cannot open a second inbox/outbox, identity ledger, agent runner or tenant mapper.
- Browser UX: first run, long conversations, overflow, scroll parity, draft retention and actual screen-reader accessible controls.
- Release: exact-head tests and manual certification required for consumer-ready state.

## H. References

- CopilotKit v2 API: https://docs.copilotkit.ai/reference/v2
- CopilotKit v2 chat slots: https://docs.copilotkit.ai/reference/v2/components/CopilotChat
- CopilotChatView slots: https://docs.copilotkit.ai/reference/v2/components/CopilotChatView
- CopilotKit CSS: https://docs.copilotkit.ai/agent-spec/custom-look-and-feel/css
- Channels SDK: https://github.com/CopilotKit/channels-sdk
- OpenTag: https://github.com/CopilotKit/OpenTag
- OpenTag setup: https://github.com/CopilotKit/OpenTag/blob/main/setup.md

**Evidence boundary:** Verified source paths and documented upstream behavior; no dependency install, code cutover, test run or UI screenshot claim in this plan.

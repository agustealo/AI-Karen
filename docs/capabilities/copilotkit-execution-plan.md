# CK-02 to CK-07: implementation and design-system migration plan

Status: adversarial plan update; no SDK installation or runtime execution claimed.
Date: 2026-10-25
Parent: `docs/architecture/decisions/2026-10-25-copilotkit-first.md`
Preservation ledger: `docs/capabilities/copilotkit-legacy-retirement.md`
Canonical preflight: `docs/capabilities/ck01-canonical-preflight.md`

## Fresh source evidence

- Web app: `src/ui_launchers/Karen-AI-Theme`, Next `15.5.23`, React `18.3.1`, TypeScript 5, Tailwind `^3.4.1`.
- `package.json` + `package-lock.json` use `@assistant-ui/react@0.15.29`, `@assistant-ui/react-ag-ui@0.0.70`, `@ag-ui/client@0.0.59`; no `@copilotkit/react-core` declared.
- The current visual authority is `src/app/globals.css` (CSS design tokens, light/dark colors, typography, radius, sidebar variables) and `tailwind.config.ts`; neither may be indiscriminately replaced.
- The current `KarenAssistantChat.tsx` composes server-backed model/agent catalog, persona, local/browser dictation, durable history, observed steps, governed presentation and intelligence rail. This is the functional baseline, not simply a textbox.
- `KarenComposerRuntimeCatalog.tsx` already requests `/api/runtime/providers` and `/api/agent-runtime/catalog`; model/agent controls must keep backend authority and visibility of actual execution.
- `src/ai_karen_engine/config/runtime.py` defaults `enable_ag_ui_bridge=False`, which requires explicit authorized enablement and a negative-path test.

## Upstream SDK considerations (verify against pinned release at implementation time)

- CopilotKit supports chat slots that can override classes, props, and subcomponents, enabling retention of Karen's exact UX rather than adoption of stock visuals: https://docs.copilotkit.ai/built-in-agent/custom-look-and-feel/slots
- CopilotKit Runtime offers authenticated discovery/middleware; dev-only `agents__unsafe_dev_only` must never be used in production. Documented `selfManagedAgents` is a different connection option with responsibilities and limitations: https://docs.copilotkit.ai/agno/backend/copilot-runtime
- CopilotKit's AG-UI integration uses standard events and runtime agent proxies; those features do **not** grant it Karen model, memory, auth or persistence authority: https://docs.copilotkit.ai/ag2/ag-ui
- Channels SDK is MIT licensed and supports Slack/Teams, using a platform delivery layer. This does not establish Karen's identity authorization, retention or self-hosted deployment automatically: https://github.com/CopilotKit/channels-sdk
- OpenTag includes Node CopilotRuntime plus Python LangGraph reference services; study behavior but never fork its complete execution stack into Karen: https://github.com/CopilotKit/OpenTag/blob/main/setup.md
- Tailwind 3 and current token syntax differ from documented current CopilotKit styling conventions. A version-pinned compatibility spike must prove generated CSS and visual behavior before proposing any global Tailwind migration.

## Architecture decision: one shell, one bridge, one runtime

**Interaction:** CopilotKit v2 chat/slots, shared *ephemeral* UI state, suggestions, agent actions, generative UI and approvals.

**Bridge:** Preferred production integration is a restricted CopilotKit Runtime bridge if required for supported SDK middleware/threads/channels, delegating to Karen's existing authenticated AG-UI runtime. It must be proxied at same origin, authenticate requests, preserve tenant identity and correlation, validate agent capability declarations, and remain unable to pick models, construct prompts, run plugins, persist messages or approve actions. Evaluate `selfManagedAgents` only as an explicitly secured alternative, not an automatic production shortcut.

**Runtime:** One `ChatRuntime` owns inference and authoritative event/persistence receipts. `CORTEX` decides eligibility. `RuntimePolicy` controls actions. Existing repository / NeuroVault own durable state.

**Channels:** SDK/runner is subordinate ingress in the existing plugin registration and permission model (owner discovery remains pending). No independent OpenTag agent.

## Appearance and UX preservation contract

Do not redesign Karen. Retain its identity: the three-panel layout, left conversation nav, central chat, right intelligence rail; consistent small sidebar headings and readable supporting text; current surface hierarchy; compact controls; desktop/mobile responsiveness; accessible focus and keyboard patterns.

Map CopilotKit visual slots onto **existing** Karen CSS variables for both themes. Never import broad SDK CSS overrides without scoping and visual-diff review. The user-visible composer must preserve provider/model request (automatic as default), agent eligibility, sticky persona selector, attachments if supported, browser/local dictation, pending content across tab/window navigation, cancellation and evidence-based execution receipts.

If CopilotKit lacks a specific native primitive, implement a narrow Karen-owned slot extending the supported SDK. Avoid adding a second chat renderer or moving backend authority to React.

For screenshots, use repeatable viewports, real UI state, golden references and meaningful tolerances. Do not alter snapshot dimensions or thresholds just to conceal regressions. Accessibility checks include keyboard focus, reduced motion, labels, contrast, and screen-reader live messaging.

## Full execution work packets

### CK-02A: Dependency and styling compatibility

- Inspect package-lock and current SDK peer dependencies, React/Next/Node compatibility, Tailwind styling imports and AG-UI library duplicates.
- Pin compatible CopilotKit versions and refresh the single chosen package-manager lock under current security policy.
- Build a versioned adapter compile test and isolated CopilotChat slot theme fixture using Karen's existing tokens, light/dark modes and typography.
- Reject dependency churn that requires an unapproved major global Tailwind migration.
- Proof: clean install, typecheck, lint, tests, build, browser/SSR hydration and visual fixtures.

### CK-02B: Runtime bridge and feature-gate proof

- Trace the FastAPI AG-UI mounted route, feature gate, session/tenant auth, request normalization, runtime event schema, history API and proxy termination.
- Integrate supported CopilotKit Runtime route or documented self-managed agent adapter using the existing same-origin web entry point and canonical backend AG-UI target.
- Allow no client-authored tools, arbitrary state, privilege flags, or unvalidated agent IDs.
- Persist no independent thread/message store and do not invent fallback answers.
- Validate enable/disable toggles from canonical `RuntimeSettings` and honest UI availability.
- Proof: authorized stream, refused scope, disabled bridge, disconnect, cancellation, replay, incomplete SSE, actual provider identity.

### CK-03: Feature-complete CopilotKit chat shell

- Inventory and migrate every dependency of `KarenAssistantChat.tsx`: provider and agent catalogs, persona, local/browser dictation, history and draft, tool/presentation registry, observed agent activity, context rail, streaming and restoration.
- Use CopilotKit chat slots and hooks for native equivalent behavior; use Karen-owned wrappers only for unique features.
- Mount exactly **one** chat renderer controlled by the canonical feature flag during rollout, with no competing active messages, socket or state store.
- Verify a per-capability before/after contract against assistant-ui on real authenticated paths.
- Proof: screenshots at desktop/mobile, theme parity, accessible UI, core flows, prompt routing, model selection, real inference, state rehydration.

### CK-04: Native agentic interactions

- Implement scoped UI-visible context and allowlisted agent state; never let UI state become authoritative memory, tenant scope or tool eligibility.
- Map suggestions, tool renderers, and user approval interrupts onto existing ToolBridge/RuntimePolicy action contracts.
- Trace the existing approval/transaction owner **before** adding a service/table; require final authorization gate and exactly-once side-effect semantics.
- Proof: approval, deny, expiry, revocation, race, cancellation, idempotent replay, audit and provenance.

### CK-05: Durable generative UI and replay

- Reuse the existing `karen.presentation.v1`/governed presentation contracts rather than invent another renderer registry.
- Generate evidence-bound typed parts and validate schemas, budgets, trusted sources and user-visible degradation.
- Store presentations and approval receipts through canonical conversation transactions; restore accurately in CopilotKit history.
- Proof: stream/non-stream/history equality, malformed/XSS/URL defense, cross-tenant rejection, valid tool receipts.

### CK-06: Channels first-class plugin

- First discover exact plugin manifest/loader/permissions/install and remove semantics. No guessed directory or second registry.
- Implement Slack-first through `@copilotkit/channels`, durable identity/tenant mappings and replay-safe runner delivery.
- Delegate execution to Karen, render platform-native cards, and preserve approvals in canonical action transaction.
- Make managed delivery an explicit opt-in deployment choice; assess self-hosted runner feasibility.
- Teams follows only after Slack contracts are stable.
- Proof: live authenticated platform test, duplication/race and worker-restart burn, revoke/uninstall semantics, browser replay.

### CK-07: Aggressive verified legacy retirement

- Remove `@assistant-ui/react`, `@assistant-ui/react-ag-ui`, obsolete chat files, wrappers, CSS, tests and lock entries only after CK-03 parity.
- Reference-audit and collapse historical `copilotkit_provider.py`, `AgentUIService`, in-memory thread/session managers and safety middleware only after consumer/security proof.
- Preserve migrations, RBAC, authenticated ingress, auditing and canonical recovery code; never blanket-delete.
- Update architectural docs, menus, feature flags, screenshots, README and CI checks to describe only reachable implementation.
- Proof: full import/reference graph, zero stale production imports, dynamic registration scans, exact-head tests and observed single active renderer.

## Release acceptance matrix

| Dimension | Gate |
| --- | --- |
| Capability | Preserve every currently supported user journey; missing feature gets explicit remediation, never silent drop |
| Styling | Both themes, fonts, density, sidebars, composer, responsive spacing, accessibility, screenshot parity |
| Runtime | Single ChatRuntime authority; real local model selection, traceable fallback/degraded metadata |
| Streaming | RUN_STARTED through authentic terminal completion/error; reconnect and replay parity |
| Security | Tenant/user/session and RBAC enforce from ingress to final durable side effect |
| Memory | User/assistant transcripts, persona state, conversation and UI receipts persist through existing owners |
| Agent UI | Verified shared state, suggestions, tool results and human approval interrupts |
| Plugins | Existing manifest, permission, lifecycle and uninstall ownership |
| Channels | Signed events, identity mapping, durable retries, native cards, authorized approvals |
| Cleanup | Remove dead artifacts and packages only after negative import/reference evidence |
| Observability | Correlation IDs, actual provider/model, event origin, action and persistence receipt |
| Delivery | Exact-head frontend/backend suites plus actual browser, provider and database proof |

## Explicit anti-patterns

- Installing CopilotKit as a popup while assistant-ui remains the real chat system.
- Using `agents__unsafe_dev_only` in production.
- Treating an AG-UI protocol connection as equivalent to full CopilotKit runtime middleware.
- Hosting OpenTag's standalone LangGraph runtime as a second Karen execution authority.
- Upgrading global Tailwind merely for cosmetic convenience without regressions.
- Building a second session store, prompt builder, policy checker, agent router or approval database.
- Deleting historic security or persistence code without proven authoritative replacement.
- Declaring a documentation PR or unit fixture to be working consumer functionality.

## Current proof status

This document records a source review and upstream documentation comparison. No CopilotKit package has been installed here, no application code was migrated, and no live test/build/browser check has been run by this plan update. Acceptance must remain open.

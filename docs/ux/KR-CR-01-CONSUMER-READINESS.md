# KR-CR-01: Consumer readiness evidence and execution handoff

**Date:** 2026-10-30  
**Status:** Baseline investigation, NOT consumer signoff  
**Scope:** Source-visible evidence on `main`; no authenticated production browser run was performed.  
**Authority:** `PROJECT_DEV_MANIFEST.md`; this is a traceability handoff, not a second architecture manifest.

## Confirmed entry-path findings

| ID | Evidence | Finding | Risk | Next proof |
| --- | --- | --- | --- | --- |
| CR-01 | `src/ui_launchers/Karen-AI-Theme/src/app/page.tsx` | Authenticated entry navigates to `/dashboard`, unauthenticated install paths use backend first-run status before `/setup` or `/login` | Installation bootstrap may be mistaken for consumer onboarding | Authenticated first-task journey |
| CR-02 | `src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx` | Active dashboard dynamically imports `assistant-ui/KarenAssistantChat` | CopilotKit is not yet active on ordinary dashboard chat | Prove real consumer CopilotKit cutover |
| CR-03 | `src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotChat.tsx` | Candidate declares itself gated acceptance-only; scopes provider by tenant/user/conversation and uses controlled chat | Candidate tests do not prove parity or release | Authenticated exact-revision browser run, no initial inference |
| CR-04 | `docs/architecture/governed-generative-ui.md` | Existing provenance, safety, presentation and replay ownership; text still refers to assistant-ui rendering | Documentation drift and presentation parity risk | Reconcile render adapter to CopilotKit, preserve contracts |
| CR-05 | `docs/capabilities/copilotkit-legacy-retirement.md` | Detailed candidate legacy ledger already exists | Premature deletion loses functions/security | Perform per-artifact import/route/permission/test reference audit |
| CR-06 | `docs/ux/intelligence-readiness-audit.md` | INT-01..10 explicitly NOT signed off | Chat/memory/intelligence consumer quality unproven | Execute real approved sanitized browser/provenance runs |
| CR-07 | `docs/presentation/PRODUCT_PRESENTATION_MANIFEST.md` | Brand/screenshot truth and trusted capture contracts already exist | Duplicate presentation plan/false screenshots | Reuse screenshot and presentation integrity gates |
| CR-08 | `docs/capabilities/copilotkit-execution-plan.md` and accepted ADR | CopilotKit-first owners and extensive parity matrix already defined | Another migration blueprint duplicates work | Reuse and update canonical implementation/retirement plans |

## Capability truth protocol

For every advertised capability, identify five independent statuses:
1. **Implemented:** source exists at a known commit.
2. **Wired:** active authenticated consumer route invokes it.
3. **Tested:** applicable unit/integration contract passes at exact commit.
4. **Consumer-verified:** authorized browser exercise observes real behavior, failure and recovery.
5. **Released:** deployment revision and human product acceptance proved.

Never map existence to release. Record evidence SHA, source path, test command, owner, failure class, outstanding PR and remediation.

## Execution order

### P0 A. Real consumer conversation
- Reconcile PR #553 baseline, PR #554 architectural decisions, PR #556 CopilotKit work and PR #572 persona isolation before starting another overlapping implementation PR.
- Prove active consumer route, feature gate, SDK/package compatibility, submitted-only generation, session creation, stream/stop/retry, durable reload, reconnect, model attribution, persona isolation and truthful errors.
- Preserve `SessionProvider`, `ChatRuntime`, canonical policy, AG-UI transport, and backend persistence. The CopilotKit renderer must not become another model, conversation or agent runtime.
- Protect drafts, voice features, right rail, typography, accessibility, mobile behavior and rich-history parity.
- Cut over active dashboard only after authenticated acceptance; retire assistant-ui per existing ledger *after* parity and reference proof.

### P0 B. Governed presentation
- Reuse current `karen.presentation.v1` and `karen.execution_receipt.v1` schemas and registry; inspect actual wire/persistence contracts before edits.
- Trace trusted evidence from tool receipt to stream, saved conversation, reconnect and restored UI.
- Add no independent renderer registry, memory store or response envelope.
- Require type/version, data-size budget, source authorization, tenant/persona scope, safe links, no executable model-authored code, text fallback, and accessible responsive behavior.
- Validate actual weather/comparison, structured analysis, and progress/approval examples from real runtime data. No fake cards.

### P0 C. User trust and consumer basics
- Execute the preexisting INT-01..10 natural language acceptance scenarios across local models and governed fallbacks.
- Verify first meaningful task without developer configuration; distinguish first-owner install from user onboarding.
- Audit settings: each visible control maps to one backend-owned persisted state and a test of its effect. Fail visibly on persistence error.
- Inventory empty/loading/error states, keyboard, screenreader, left/right sidebar scrolling, composer, session switching and mobile.

### P1 D. Durable work
- Trace existing artifacts API (`src/ai_karen_engine/api_routes/artifacts.py`) and persistence before proposing new artifact machinery.
- Prove create/edit/save/version/restore/export against real owned state before marketing durable workspace or living artifacts.
- Extend existing approval and task lifecycle contracts for real verified outcomes; never infer completion from a frontend event.


## CK-CUTOVER-02 source progress (2026-10-30)

- Added `KarenCopilotConsumerChat.tsx` using canonical `SessionProvider` for durable create/load and title search, with negative unauthorized-session handling and duplicate navigation suppression.
- Reused existing `KarenComposerRuntimeCatalog` to display backend-reported provider/models in the candidate consumer shell; any choice is a *request*, not verified execution. A targeted component test asserts forwarding; no claim of browser acceptance.
- Rich history already has `KarenCopilotVerifiedHistory.tsx` and `KarenCopilotHistoryGate.tsx`, which validate authoritative saved CUSTOM presentation/receipt events before hydration. This is partial existing implementation, **not absent functionality**. Confirm live streaming equivalence, actual owned history, and fresh account/tenant permissions in a real integration test.
- Existing `ConversationContextRail` is not yet wired to the candidate, and there is no established safe mapping from the candidate's live SDK event data to its observed event props. Do not pass synthetic empty events merely to make the rail look implemented.
- The candidate now reports synchronous submit-pending state and SDK running state to the canonical consumer shell; provider/model selection and conversation navigation are disabled during busy periods and request callbacks reject navigation while the runtime is active. Unit regression coverage added. This does **not** establish that CopilotKit dynamically updates provider properties correctly on an idle model change; real SDK/owned execution receipts are still required.
- Do not activate candidate dashboard mount while model override execution proof, rich replay, accessibility/visual/rail parity and authenticated browser journeys remain unverified.

## Mandatory security and observability
- Cross-user/tenant/persona denial at final backend boundary, including history and derived summaries.
- Reauthorization on sensitive actions, revocation, replay, cancellation and idempotency testing.
- Request/correlation IDs, user/tenant/session/conversation, intent, requested/actual model, response source, fallback/degraded state, memory recall count, presentation/tool receipt, persistence result and latency.
- No secrets in logs or screenshot captures.

## Acceptance and proof
Use existing **Main Quality Gate**, **Chat System Burn**, **Presentation Contract**, frontend lint/typecheck/tests/build, backend compileall/pytest/ruff/mypy and approved Playwright browser suites. Do not create a disconnected readiness gate or require distribution builds before human release signoff.

Pass requires:
- All critical consumer journeys green at the exact tested SHA, including reload/reconnect and error recovery.
- Evidence-bound rich rendering in live, persisted and restored history.
- Zero passing cross-scope access attempts.
- Accurate model and persistence receipts.
- Authenticated UX screenshots reviewed at native resolution with sanitized demo credentials.
- Documented human acceptance; any unrun gate remains **UNVERIFIED**, not passed.

## Current block and ownership
GitHub Issues are disabled for this repository (API 410), so this work is tracked by this branch/PR rather than a fabricated issue. Preserve existing audit and migration work; amend their owners rather than creating a competing architecture. Do not merge this documentation as proof that implementation or consumer acceptance has passed.

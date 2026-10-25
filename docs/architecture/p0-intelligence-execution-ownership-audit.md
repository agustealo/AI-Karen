# P0 canonical intelligence execution: adversarial ownership audit

Status: IN PROGRESS. Baseline: `main`, inspected 2026-10-24 through GitHub connector. This document is a verification worklist, **not** a claim of implemented integration, passing tests, or a line-by-line repository review.

## Objective

Ensure chat, search, research, tools, and Medusa execution converge on one runtime authority. Prove policy, streaming, persistence, event replay, and consumer-visible execution truth without replacing existing owners or adding a duplicate orchestrator.

## Direct observations

| Path | Observed role | Evidence | Disposition |
| --- | --- | --- | --- |
| `src/ai_karen_engine/config/web_search.py` | Defines search provider enablement/priority defaults and merges operator overrides with `build_provider_configs` | Read from current `main`; Wikipedia is currently enabled by default | Keep configuration authority; reconcile #531 rather than special-case in UI |
| `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/components/ResultsWorkspace.tsx` | Independently renders search states, tabs, sources, diagnostics and result panels | Read from current `main` | Audit whether it consumes canonical AG-UI projection; preserve valuable evidence presentation while eliminating duplicate chat execution |
| `docs/ux/user-journey-audit.md` | Canonical authenticated UX evidence register | Read from current `main`; journeys marked NOT RUN; synthetic stream test is not live browser proof | Reuse, extend with search/research journeys |
| PR #530 | Search copy/presentation update | GitHub PR metadata and changed filenames | Rebase or merge useful UI changes after contract comparison; do not treat as runtime proof |
| PR #531 | Wikipedia opt-in default and tests | GitHub PR metadata and changed filenames | Review as config change, not capability-routing completion |

Repository symbol search for `ChatRuntime`, `AGUI`, `CapabilityAwareMedusaPlanner`, and `DeepAgentsResearchSpecialist` returned no results in this connector lookup. **This does not establish absence:** inspect repository tree and files directly before making architecture claims.

## Ownership decisions to prove

1. API route: authentication, validation, tenant and correlation context, dispatch only.
2. ChatRuntime + RuntimePolicy: capability execution authority, authorization, budget, provider/model selection through canonical registry, streaming, persistence and audit.
3. CORTEX: intent, topology and permission eligibility decisions, never privileged execution.
4. Medusa / Deep Agents: bounded specialist/workflow coordination only, under runtime authorization.
5. Provider registry: canonical availability/config and fallback contracts; Wikipedia is neither hardcoded universal fallback nor universal ban.
6. AG-UI: canonical typed event projection, terminal semantics, activity, tool, approval, subagent, snapshot/delta and replay.
7. assistant-ui: one conversational thread/composer; typed evidence/artifact/tool renderers without frontend authorization logic.
8. NeuroRecall / NeuroVault: authorized recall versus governed storage; keep provenance, evidence and audit retention semantics distinct.

## Required call-graph artifact

For **both** a simple search request and a deep research request, populate the following with verified path, symbol, invocation evidence, and test names (no guesswork):

| Stage | Implementing file/symbol | Caller | Policy/tenant boundary | Test | Result |
| --- | --- | --- | --- | --- | --- |
| Frontend submit | TO VERIFY | | | | NOT RUN |
| API ingress | TO VERIFY | | | | NOT RUN |
| CORTEX decision | TO VERIFY | | | | NOT RUN |
| RuntimePolicy authorization | TO VERIFY | | | | NOT RUN |
| Provider/capability selection | TO VERIFY | | | | NOT RUN |
| Tool/Medusa dispatch | TO VERIFY | | | | NOT RUN |
| Event projection and transport | TO VERIFY | | | | NOT RUN |
| Conversation/evidence persistence | TO VERIFY | | | | NOT RUN |
| Frontend result and resume | TO VERIFY | | | | NOT RUN |

## Minimal typed execution contract

Before adding code, locate existing envelopes and extend their canonical schema if needed. Verify fields for task/request/correlation identifiers; user/tenant/session/conversation; capability/objective; consent/policy decision; resource budget; requested and actual provider/model; runtime engine; source provenance; tool/action receipts; degradation and error reason; execution terminal state; persistence and replay cursor. Do **not** create a second canonical envelope.

## Adversarial scenarios and proof gates

- Search content containing instructions must remain untrusted evidence; no elevation to runtime policy or lasting memory.
- Tenant mismatch, revoked permissions and revoked consent must prevent retrieval, delegation and mutation.
- Provider fallback cannot widen data egress scope or bypass runtime budget/security constraints.
- Concurrent cancel, expired approval, disconnect and resume must not double-execute actions.
- Duplicate AG-UI events and missing terminal events must never become fake completed results.
- Research citations must point to retrievable original evidence; unsupported conclusions remain marked unverified.
- Assistant-ui reload restores persisted task state, not invented frontend success.
- Cost/latency of multi-specialist paths must be compared against a single-agent baseline.
- Every attempted mutation emits an authorized action receipt; failed persistence is visible.

## Required verification

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
cd src/ui_launchers/Karen-AI-Theme
npm run lint
npm run typecheck
npm run test
npm run build
# Then run existing authenticated user-journey harness against an attested deployed SHA.
```

Mark each gate NOT RUN until actually executed; preserve unrelated baseline failures and prove regressions against exact-head tests. Use the existing screenshot provenance and UX evidence register.

## PR sequence

1. P0 ownership inventory and call graph, including reference audit and test map.
2. Canonical search/research ingress with RuntimePolicy proof.
3. AG-UI and assistant-ui event/rehydration contract.
4. Evidence ledger and verification contract.
5. Bounded Medusa specialist topology and outcome evaluation.

No deletions, new services, or integration claims are authorized solely by this document. Before deleting code: inspect references in runtime/UI/tests/docs/config/plugins; migrate to canonical owner; prove the replacement; document the risk.


## P0 inspection continuation: verified frontend ingress chain (2026-10-24)

These files were read from `main` using the connected GitHub repository. This is a **partial, source-backed chain**, not an assertion about the unseen backend wiring.

| Stage | Concrete owner/symbol | Observed behavior | Assessment |
| --- | --- | --- | --- |
| Search state and request initiation | `plugin_repo/intelligent-search/hooks/useIntelligentSearch.ts`, `useIntelligentSearch().executeSearch` | Keeps React query/mode/options/response/error state. Builds payload, awaits `IntelligentSearchApi.executeSearch` and guards against stale state updates using sequence counter | Active independent request hook. No visible AG-UI event subscription or canonical chat thread state in the inspected hook |
| Payload transformation | `plugin_repo/intelligent-search/hooks/useSearchPayload.ts`, `buildPayload` | Converts `mode, query, options` into `{mode,query,context,crawl?}`, separating crawler flags | UI-side serializing adapter; verify backend schema parity and policy validation. Not evidence of orchestration by itself |
| Plugin API ingress | `plugin_repo/intelligent-search/services/IntelligentSearchApi.ts`, `executeSearch` | POSTs to `/api/plugins/execute` with `plugin_name:'intelligent-search'` and parameters. Unwraps result/data/payload/response into search result shape | **Confirmed direct plugin execution ingress**, rather than explicit chat/AG-UI ingress in this client. Whether backend calls ChatRuntime must be traced |
| Article retrieval | Same API module, `fetchArticle` | GETs `/api/plugins/search/articles/{articleId}` and checks article identity | Must verify article ownership, permission, tenant and retention in backend route/store |
| User-visible result projection | `plugin_repo/intelligent-search/components/ResultsWorkspace.tsx` | Renders local tabs, excerpts, sources, and diagnostics using `IntelligentSearchState` | Useful typed presentation, but not demonstrated as assistant-ui tool renderer or AG-UI projection |
| Provider defaults | `src/ai_karen_engine/config/web_search.py` | `DEFAULT_PROVIDER_CONFIGS` with `build_provider_configs`; Wikipedia enabled in main pending #531 | Canonical config likely. Verify downstream registry and capability routing |

### Concrete contract vulnerabilities requiring tests

1. `IntelligentSearchApi.executeSearch` examines `envelope.error` but does **not** check `envelope.success === false`. An error-shaped response with a nested `result` could be projected as success. The backend envelope contract must be checked before selecting the precise repair; don't invent error semantics.
2. `normalizeSearchResponse` accepts any object containing a string summary OR any of several object fields as an apparently valid search response. It performs no verification of citation/source truth or terminal execution state. This is not necessarily wrong for a presentation adapter, but it must not serve as an authoritative success/verification gate.
3. `useIntelligentSearch` invalidates the local request sequence on query/mode change and unmount, yet the inspected code does not abort the network request. The backend job may continue and consume resources; cancellation ownership and transport semantics must be verified before wiring abort.
4. `useSearchPayload` is locally defined inside a hook and returns a freshly allocated callback each render. This can force changing dependencies; prioritize contract unification over a micro-optimization.
5. The frontend offers `deep_research`, `weather`, and `stock_market` modes in `configs/modeConfig.ts`. That proves mode availability in the UI but does not prove each mode routes through an appropriate capability, data provider, or policy gate. Explicitly test all three with actual backend provenance.
6. Frontend search response types include optional `can_execute`, `reason`, `diagnostics`, and `metadata`, but there is no required explicit terminal status, persistence receipt, or AG-UI cursor in the inspected `IntelligentSearchResponse`. These must be reconciled against canonical backend schemas rather than casually added to the plugin type.

### Immediate owner discovery still required

Locate the actual server handler for `POST /api/plugins/execute` and `GET /api/plugins/search/articles/{articleId}`, then trace `intelligent-search` plugin manifest and dispatch into RuntimePolicy, ChatRuntime, CORTEX, provider registry and any Deep Agents or Medusa specialist. Confirm from code and tests whether the plugin execution path delegates to canonical runtime or bypasses it. There is not enough inspected backend evidence yet to claim either outcome.

### Revised implementation boundary

Do not replace `IntelligentSearchApi.executeSearch` with a new unverified `/api/chat` transport. First identify an existing canonical client event/AG-UI adapter and server conversation ingress that supports tools. Then preserve the search-specific typed evidence renderer as a **tool presentation** while moving responsibility for orchestration, authorization, cancellation and persistence to the canonical runtime. A compatibility bridge is permissible only with explicit ownership, deprecation condition and parity tests.

### Verification status

- Read-only inspections of the listed frontend files: COMPLETE.
- Frontend search-to-plugin dispatch: VERIFIED by source.
- Backend plugin-to-runtime delegation: NOT VERIFIED.
- AG-UI event and replay parity: NOT VERIFIED.
- Authenticated browser journeys and test executions: NOT RUN.
- Production integration changes: NOT STARTED.

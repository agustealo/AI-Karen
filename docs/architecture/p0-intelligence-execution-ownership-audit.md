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

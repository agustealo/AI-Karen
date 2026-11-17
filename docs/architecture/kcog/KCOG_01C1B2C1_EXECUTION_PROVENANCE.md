# KCOG-01C1B2C1: selected-path provider/provenance drift containment

Status: source candidate, NOT an accepted B2C or an experimental selector. Base: `main@6f07fb877983ffd23a944c9787a3d3bef78e51fc`.

## Audit result

B2B1's runtime-owned `selected_strategy_execution_v1` projection checked the metadata fallback level, degraded state and a typed model-source receipt. It did **not** reject contradictory fallback/degradation fields *inside* the typed `ResponseProvenance`, nor an explicit requested/actual provider or model mismatch. The separate B2B2 real Ollama acceptance helper likewise accepted a typed fallback/degradation report when the projected metadata said primary execution.

Both paths can produce useful observed execution evidence, but those contradictions must never be promoted to a verified selected-strategy diagnostic.

## Correct source owner and scope

- Reuse `ChatRuntime._inspect_selected_strategy_execution` for the already-selected runtime path. It now requires the typed provider receipt to attest to no fallback/degradation, and denies inconsistent requested/actual provider/model, explicit used-fallback or generation-error metadata.
- Reuse `scripts/ci/verification_strategy_pair_live_proof.py` for the isolated installed-Ollama acceptance. The same typed contradictions now fail with the existing bounded `gateway_degraded_or_fallback` code.
- Keep the existing canonical `TrajectoryRecorder`, `OutcomeRecorder`, `OutcomeStore` and reviewer admission untouched. No new policy owner, learning ledger, provider adapter, API route, or speculative candidate execution.
- No additional raw prompts, identities, secrets, model response bodies, or new persisted metadata fields.

## Proof contract

The already-required Cognitive Proof workflow runs:
- `tests/core/runtime/test_selected_strategy_execution_evidence.py` for direct and verification negative scenarios: typed fallback, typed degradation, explicit requested provider/model drift, metadata fallback/error, cancelled/incomplete response and absent durable transcript;
- `tests/core/runtime/test_verification_strategy_pair_live_proof.py` for the same typed and projected fallback contradiction in the CI-only real-model receipt checker;
- existing selected-path, truthful reasoning attribution, provider-synthesis and durable-outcome regressions.

A passing source test is not a measured production cancellation. The existing Ollama Settings Live E2E remains required to prove actual nonstream direct, nonstream verification and stream verification execution on an installed model. Do not infer that a second action is runnable from a chosen-action receipt.

## Remaining B2C gates

1. Revalidate principal/session/RBAC, RuntimePolicy, provider capability and original shared model/step/deadline budgets **at execution**, without granting new actions or bypassing the central runtime.
2. Prove real streaming and nonstreaming cancellation, partial-output termination and concurrent requests preserve tenant isolation and record an accurate terminal status in the existing `TrajectoryStore`.
3. Prove exact frozen decision/feature lineage and RLS-backed `TrajectoryStore` / `OutcomeStore` links in real PostgreSQL, including restart and failed/duplicate writes.
4. Obtain independent factual-correctness, verification-need, safety, latency and cost judgments through the existing authenticated reviewer workflow. Require separate reviewers, held-out task families, frozen utility and baseline-relative evidence.
5. Only after the above and explicit approval, design a *separate*, default-OFF randomized experiment with immutable decision-time behavior probabilities and sampled action commitments. This patch does not authorize it.

### Explicit nonclaims

No independent quality proof, provider drift recovery, measured cancellation durability, held-out outcome gain, reviewer admission, randomized selection, off-policy eligibility or policy activation is established by this source guard.

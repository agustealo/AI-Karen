# KCHAT-AUTH-05B2B2A: canonical embedding admission is mandatory

**Status:** source candidate, not complete KCHAT-AUTH-05B2. Depends on
merged PR #991 and caller census PR #996.

## Scope and retained ownership

The existing `ModelManager.generate_embedding` is the sole canonical,
real-model-only embedding execution surface being repaired here. It now
requires the original, authenticated `GovernedToolModelAdmission` before
reading encoder state or invoking `embed_authoritative`; an absent/forged
grant fails closed. The original `AuthorizedExecutionPlan`,
`ChatExecutionContext` and `ExecutionBudgetMeter` are reused unchanged.

The caller census found two static Core production invocations of
`ModelManager.generate_embedding`, both already passing an authenticated
admission via `LLMUtils`. No second plan, meter, router, authorization
framework, or embedding fallback was introduced.

## Behavioral contract

- Missing/invalid grant, foreign tenant, or replaced original budget:
  permission denial before encoder calls, quota consumption or fallback.
- Valid grant with bad input, unavailable encoder, or unsupported kwargs:
  explicit failure before budget reservation.
- Valid registered local encoder: one actual real-model attempt, charged
  once to the original shared meter, invoked off the event loop.
- No new network permission; existing provider allow/deny and model
  restrictions remain enforced by Core admission.

The public direct `ModelManager.generate_chat` compatibility branch,
`invoke_provider` and `invoke_embedding` raw helpers, raw local
OpenAI-compatible client, and `EmbeddingManager` legacy hashed/simple
fallbacks are **still outstanding**. No claim is made that all embedding
consumers have migrated, or that final DNS/socket egress is certified.

## Proof

`tests/core/model_runtime/test_model_execution_truth.py` retains real
encoder worker-thread proof under an authenticated grant.

`tests/core/model_runtime/test_governed_core_inference_admission.py`
asserts zero encoder calls on missing/forged/foreign grant and equal-value,
different-object meters, and retains exact per-vector quota/provenance
checks on the working Core facade. Chat System Burn already runs both
suites. Full exact-head Main Quality, Ollama, Medusa, First-Boot and
independent reviewer acceptance are required before merging.

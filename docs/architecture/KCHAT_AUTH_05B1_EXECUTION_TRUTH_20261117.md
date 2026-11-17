# KCHAT-AUTH-05B1: execution truth and Core invocation safety

Status: source candidate awaiting exact-head CI, code review, merge and post-merge acceptance.
Date: 2026-11-17. Depends on merged KCHAT-AUTH-05A (#982).

## Existing responsibility owners
ModelManager remains the sole Core provider selector and actual invocation owner.
ModelManagerInferencePort consumes a typed observed execution receipt instead of selecting a provider again after execution.
EmbeddingManager exposes a real-model-only embedding method for the canonical Core path. It never returns synthetic lexical/hash/zero vectors when the model is absent or fails.
ModelManager rejects caller-supplied model identities outside the selected registry model before runtime resolution.
Cached provider runtimes are invalidated when the registered endpoint or selected model changes. Clients with an environment credential are rebuilt so key rotations cannot reuse stale bearers.
Synchronous generation and embedding methods execute in worker threads, while genuinely async methods stay on the event loop.
Chat System Burn executes adversarial regressions for source attribution, early denial, cache drift, credential rotation, and authentic embeddings.

## Not certified
This slice is factual execution behavior, not a RuntimePolicy admission grant.
It does not propagate authenticated ChatExecutionContext, AuthorizedExecutionPlan and the original ExecutionBudgetMeter to every local model, external model, retry, nested call and embedding.
Legacy EmbeddingManager compatibility APIs and LLMUtils direct invocation remain outside this repaired canonical model-only embedding contract.
Never label the broader KCHAT-AUTH-05B authorization boundary complete based solely on this change.

## Next acceptance slice
Audit all active InferencePort, ModelManager, LLMUtils and SDK callers. Reuse the original request-scoped RuntimePolicyEnforcer decision and shared meter at every actual provider/model attempt, including external and local models, retries and embeddings. Fail closed on absent, forged, disabled or mismatched scope before transport construction. Preserve RBAC, tenant isolation, provenance, audit and cancellation. Migrate and delete only after reference and exact-head test proof.
DNS resolution/socket pinning, link-local host packet capture, DNS rebinding and independent SDK egress remain separate host-level gates.

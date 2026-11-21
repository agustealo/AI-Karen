# KIS-GRAPH-01C2P: Runtime memory evidence publication freshness

## Live authority trace

Source inspected on live `main` at `abe8a33c2aa6b99da86b1683cd5e08bdfbf96be7`:

1. `NeuroRecall.recall` performs scoped selection and invokes the current external-source `SourceLineageAuthorizer` for graph-derived external memories. It emits selected memories and their provenance.
2. `MemoryRuntimeManager.recall_context` invokes NeuroRecall for each call and serializes the current selection. No result cache was observed in this method.
3. `RuntimeEvidenceResolver._resolve_memory` calls `MemoryRuntimeManager.recall_context` and translates selected items into `CognitiveContext.evidence`, preserving retrieval authority and source metadata. It does not fetch graph event IDs directly.
4. `PromptAssembler` serializes supplied prompt components but does **not** independently authenticate or reauthorize a previously selected memory.
5. `MemoryFetchNode` invokes an injected recall callback on each node invocation. A `CognitiveContext` or `RecallResult` is a point-in-time snapshot, not a permanent authorization grant.

## Added adversarial runtime contract

`tests/core/runtime/test_graph_evidence_freshness_boundary.py` uses the *actual* NeuroRecall and RuntimeEvidenceResolver with a deterministic, isolated in-test retriever and source ACL. It verifies that:

- A newly resolved runtime context includes graph evidence only when the current authorizer grants it.
- A second runtime context for the same request after source revocation contains **no** graph memory, provenance, or count despite the first context having contained it.
- The runtime resolver performs a new recall per context, and NeuroRecall calls the source authorizer on each resolution.
- Already denied external-source evidence never enters the runtime context.

This is an in-process contract, not an integration claim about a deployed tenant/session. The lightweight manager in the test serializes actual NeuroRecall results into the documented `recall_context` envelope; it does not replace production `MemoryRuntimeManager` or its provider composition.

## Risk retained / next gate

The evidence resolver is a retrieval-to-context adapter, not a publication-time source authorization service. A cached or reused prior `CognitiveContext`, `RecallResult`, assembled prompt or already visible UI fragment could retain stale content after a permission change. A full solution requires auditing the exact runtime model-execution/publication boundary, source-change invalidation semantics and cancellation behavior. Do not add a second permissions database, TTL masquerading as source authorization, a frontend-only purge, or a false success response.

## Proof

- `pytest tests/core/runtime/test_graph_evidence_freshness_boundary.py -q`
- `pytest tests/core/memory/retrieval/test_graph_selection_adversarial_boundary.py -q`
- `pytest tests/core/memory/test_neuro_recall_scope.py -q`
- Mandatory Main Quality / Backend Quality runs the new test.
- Exact-head CI and review required before merge.

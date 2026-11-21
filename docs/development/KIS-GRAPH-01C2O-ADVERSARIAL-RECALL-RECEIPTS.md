# KIS-GRAPH-01C2O: Graph-to-response adversarial authorization proof

## Authority and observed behavior
Source reviewed on live `main` `ed765e1bb34c6d35d575118ad6b1eadb5cc268f4`:
- `core/memory/retrieval/neuro_recall.py` owns scoped candidate filtering, external-source live authorization, selection and provenance. A graph candidate with an external source reference must pass its injected live `SourceLineageAuthorizer`; metadata's self-reported authorization status is not a grant.
- `core/memory/retrieval/selected_graph_projection.py` is a synchronous, read-only projector of an already selected `RecallResult`, validating scope, event identity, receipt consistency and direct `MENTIONS` depth before outputting bounded opaque nodes.
- Existing tests covered authorization and graph projection separately. The new tests cross the full **NeuroRecall selection to projector** boundary, exercising the same injected authorizer and retriever across both allowed and revoked recalls. This is in-process adversarial contract proof; it is not a claim to have run a deployed, authenticated browser or live PostgreSQL integration test.

## Adversarial proof
- Granted external graph memory produces a single bounded selected edge without content, event ID or source reference in the graph.
- After revocation, a **new** NeuroRecall recall denies all memory and provenance; projecting that new result emits no nodes or edges. Live source ACL is called once for each recall.
- Forged `authorization_status=authorized` metadata cannot override an actual denied authorizer.
- Exception text from the source authorizer cannot enter the selected result or projected graph.
- Cross-tenant graph candidates are rejected prior to consulting external-source authorization.
- Tampered event receipts and requests with changed tenant/query cannot emit graph evidence.

## Important temporal boundary and outstanding risk
A previously selected `RecallResult` is a point-in-time snapshot. The synchronous `project_selected_memory_graph` does not and cannot independently re-run source authorization. Callers **must not** re-use cached selection results after a source permission change, nor treat projector output as a durable grant. The runtime should obtain a freshly authorized selection at the point of prompt or UI publication. This slice does not add a duplicate authorization owner or claim to invalidate old client-side output. A distinct future integration audit should verify prompt/publication freshness and revocation propagation through real user sessions.

## Proof
- `pytest tests/core/memory/retrieval/test_graph_selection_adversarial_boundary.py -q`
- `pytest tests/core/memory/retrieval/test_selected_graph_projection.py tests/core/memory/test_neuro_recall_scope.py -q`
- Mandatory Main Quality / Backend Quality invokes the new adversarial contract.
- `python -m compileall -q src`
- Exact-head review, complete required CI, and verified `main` merge are mandatory before release.

# KIS-GRAPH-01C2M: Raw graph traversal data at the recall boundary

## Source examination

Verified from the AI-Karen live-main source as of `e9d77b73cdcc486d367522100e3796af66c97af4`:

- `LeanGraphService.get_entity_context` and `get_related_context` call their configured graph repository. Their results are **candidates**, not trusted, selected user-visible evidence. The configured production graph repository is PostgreSQL.
- `HybridRetrievalRouter._query_graph` looks up graph event IDs using scoped entity cues, and rehydrates candidate **content** through `event_source.fetch_many(tenant_id, user_id, event_ids)`. It skips IDs for which no canonical event is returned.
- Before this change, the router also copied `graph_row["path"]` unchanged into both `metadata.custom.provenance.graph_path` and `metadata.custom.graph_path`. Intermediate traversal node/edge IDs are not themselves separately rehydrated or permission-checked. Propagating them into generic memory metadata could leak unverified references to downstream consumers of the candidate metadata.
- `project_selected_memory_graph` has its own strict NeuroRecall selected-result, scope, receipt and provenance validation and does not need raw traversal paths. The distinct internet search evidence graph is outside memory recall.
- The graph-provenance expansion test incorrectly wrote its fake graph to `router.leangraph` although the current router reads `router.graph`; this concealed regression coverage of the actual graph candidate path.

## Correction

Do not propagate the adapter's raw traversal `path` into recall entries, provenance or custom metadata. Preserve candidate event ID, relationship kind, depth, entity cue and canonical rehydrated event content so NeuroRecall and existing authorized selected-graph projection can continue operating. Correct the fixture and add a direct assertion that an unverified intermediate identifier is absent. The no-canonical-event test continues to require an empty candidate result.

No new graph storage, source authorizer, ranking authority, plugin adapter or output graph contract is introduced.

## Proof and residual risks

- `pytest tests/core/memory/retrieval/test_graph_provenance_expansion.py -q`
- `pytest tests/core/memory/retrieval/test_selected_graph_projection.py -q`
- `pytest tests/core/memory/graph/test_postgres_graph_consent_contract.py -q`
- Mandatory Main Quality runs the focused graph provenance test.
- `python -m compileall -q src`
- Exact-head CI, review, merge conflict audit, and verified live-main commit required for release.

**Audit boundary:** This slice removes unverified traversal paths from one canonical candidate builder. It does not prove every direct `LeanGraphService` consumer or plugin/UI path is absent; additional direct-consumer inventory and any active caller remediation must remain separately scoped. External source ACL and final evidence selection remain NeuroRecall's authority.

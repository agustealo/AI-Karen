# KIS-GRAPH-01C2N: external graph consumer authority

## Live-source observations
Reviewed `agustealo/AI-Karen` source on `main` at `550ea1e2d84eff30202936988a3900fb3618fdf2`.

- Canonical memory graph writes are owned by `core/memory/projections/memory_graph_worker.py` and `core/memory/graph/service.py`. These are internal graph projection components, not user-facing authorization.
- Canonical graph candidate expansion in `core/memory/retrieval/retrieval_router.py` rehydrates candidate events before NeuroRecall, which owns final memory selection and source authorization. The prior KIS-GRAPH-01C2M slice removed unverified traversal paths from its metadata.
- `core/memory/retrieval/selected_graph_projection.py` validates tenant/user/query, selected memories, matching selection receipts and direct `MENTIONS` provenance before rendering a bounded, opaque graph.
- `services/search/evidence_graph_projection.py` is a **different** bounded, public internet search provenance diagram based on already selected search results. Its UI `plugin_repo/intelligent-search/components/EvidenceGraphPanel.tsx` displays the server-authored graph and does not select memory storage.
- Inspected `api_routes/memory/memory.py`, `api_routes/memory/control.py`, `api_routes/admin/memory.py`, `api_routes/users/memory_controls.py`, and `core/langgraph_orchestrator/nodes/memory_fetch.py`. No direct LeanGraphService graph read was confirmed in these inspected route/UI paths. The retired `users/memory_controls.py` is explicitly unmounted and fail-closed.

## Contract added

The repository now tests external Python execution boundaries under `api_routes`, `mcp`, internal plugin directories and the root plugin directories for direct imports of GraphRepository/LeanGraphService storage owners, canonical *candidate* retrieval router, and calls to raw graph query methods. It separately scans the Karen UI source for graph-storage implementation names.

This is a *prohibition* against bypassing existing runtime authorization, not an added API endpoint or a new security service. Calls that legitimately need evidence must receive NeuroRecall-selected results from the authoritative runtime. The existing selected projection remains the only governed personal-memory graph display contract. The test checks that this projection remains distinct from public internet search evidence graph.

## Proof and limits

- `pytest tests/architecture/test_graph_consumer_authority_contract.py -q`
- `pytest tests/core/memory/retrieval/test_selected_graph_projection.py -q`
- `pytest tests/architecture/test_legacy_neo4j_graph_boundary.py tests/architecture/test_retired_kuzu_graph_authority.py -q`
- Mandatory Main Quality invokes the new test on the exact PR head.
- `python -m compileall -q src`

A static source test does not establish the absence of dynamically calculated imports, code outside scanned roots, non-Python backend clients or external applications. It must not be mistaken for a successful live tenant/source-ACL integration test. No graph store, source permissions, persisted data, migrations or UI features are removed. Any CI finding from this new contract must be audited and migrated to its canonical owner rather than excluded merely to turn CI green.

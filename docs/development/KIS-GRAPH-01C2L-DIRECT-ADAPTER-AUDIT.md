# KIS-GRAPH-01C2L: direct graph adapter authorization audit

## Live-main ownership
- Canonical graph service: `src/ai_karen_engine/core/memory/graph/service.py`, with the validated `LeanGraphConfig`. Production backend: PostgreSQL graph repository.
- Canonical graph candidate flow: `core/memory/retrieval/retrieval_router.py`, which retrieves governed PostgreSQL event records. `NeuroRecall` owns external-source permission checks, final selection and abstention.
- Display: `core/memory/retrieval/selected_graph_projection.py` requires a scope-matched selected result and receipt provenance.
- Distinct internet evidence graph: `services/search/evidence_graph_projection.py` operates on InternetCapabilityService-selected public source/passages, not stored personal memory events. It is not a replacement for memory source permissions.
- The integration retrieval router is a compatibility alias to the canonical Core implementation.

## Confirmed bypass
`LeanGraphConfig.validate` already rejects `graph_backend="kuzu"` because the retired implementation was ephemeral rather than durable. Yet `adapters/__init__.py` exported `KuzuGraphAdapter` directly. Constructing the legacy class bypassed config validation, permitting process-local recording of event dictionaries and direct returns of raw event IDs from graph traversal without current canonical event consent or source permissions.

## Disposition
Keep the historical class name importable but reject instantiation before filesystem changes or memory-event storage. Retire its unscopeable read/write methods rather than supplying invented results. The `in_memory` graph repository remains available for explicitly configured tests and development; Kuzu is not a supported backend. Do not introduce another store, controller, fallback or source authorizer.

## Proof and limits
- `pytest tests/architecture/test_retired_kuzu_graph_authority.py -q`
- `pytest tests/core/memory/graph/test_leangraph_config.py -q`
- The mandatory Main Quality graph contract step executes the new regression.
- A Python runtime tree scan covers direct identifier and module references under `src`, `server`, `scripts`, `plugins`, `free_plugins`, excluding the retired implementation and its export only. It does not prove absence of external clients, dynamic imports, or non-Python references.
- No PostgreSQL graph, memory-event, consent, migrations or RBAC authority is deleted.

## Related paths for later review
Direct calls to `LeanGraphService.get_related_context` and `get_entity_context` remain *candidate-only*, not permission to display data. Any new API/plugin/visualization consumer must pass final evidence through the authorized runtime selection and project only selected evidence. The remaining adapters should be checked against production registry restrictions before reuse.

# KIS-GRAPH-01C2J: direct graph consumer boundary

## Scope and evidence

Audit based on live source in `agustealo/AI-Karen` after PR #1150.

- `src/ai_karen_engine/core/memory/retrieval/retrieval_router.py` rehydrates PostgreSQL graph candidates as governed events. `NeuroRecall` owns final candidate selection and live external-source ACL checks.
- `src/ai_karen_engine/core/memory/retrieval/selected_graph_projection.py` accepts `RecallRequest` and selected `RecallResult`, enforces tenant/user/query agreement, requires matching provenance and restricts exported relationships to direct `MENTIONS` evidence. This is the sanctioned visualization path.
- `src/ai_karen_engine/platform/memory/postgres/graph_repository.py` applies canonical current consent checks to raw event references after KIS-GRAPH-01C2I (#1150). These IDs remain candidates, **not** selected evidence or external-source ACL grants.
- `src/ai_karen_engine/core/reasoning/graph/reasoning.py` previously kept a process-object-lifetime `CapsuleGraph`, inserting query hashes, unverified `ReasoningTrace.memory_matches` text hashes, timestamps and ranking scores after synchronous and asynchronous calls. No tenant/user scoped graph identity, current event proof, or source-revocation check was present. Its `capsule_graph`, CLI visualization and DOT export made stale data readable from later calls.

## KIS-GRAPH-01C2J disposition

Classify the legacy `ReasoningGraph` automatic mirroring path as **dangerous and superseded**. Disable it fail-closed, retain the existing inference path, and return `None` from compatibility graph presentation readers. Explicit `enable_graph_mirroring=True` is rejected, rather than creating an unauthorized fallback. No replacement graph repository, source authorizer, or model router is introduced.

The existing `project_selected_memory_graph` is the only appropriate memory-evidence display owner. Future explainability work must route verified, scoped `NeuroRecall` receipts there, not recreate an independent graph.

## Outstanding audit: legacy Neo4j knowledge client

`src/ai_karen_engine/services/knowledge/knowledge_graph_client.py` exposes generic Neo4j traversal, raw Cypher and graph paths without the memory domain's tenant/user/source-verification contract. It also has a legacy graph-deletion method with permissive handling of missing RBAC context. This file has **not** been proven to have an active runtime consumer, nor proven dead. Do not delete it, assume that it is safe for memory evidence, or silently replace it until complete import/route/plugin references and tests are audited. A separate scoped remediation should either migrate active use to canonical PostgreSQL/NeuroRecall or deny ungoverned access with compatibility impact explicitly tested.

## Proof

- `pytest tests/core/reasoning/graph/test_reasoning_graph_authority.py -q`
- `python -m compileall src`
- `ruff check src tests`
- Mandatory Main Quality job invokes the targeted regression test.
- Review active references to `ReasoningGraph`, `CapsuleGraph`, `KnowledgeGraphClient`, `get_entity_context`, `get_related_context`, and `execute_cypher` prior to any subsequent legacy removal.

The final acceptance of this change requires exact-head CI, source review, and live-main merge verification.

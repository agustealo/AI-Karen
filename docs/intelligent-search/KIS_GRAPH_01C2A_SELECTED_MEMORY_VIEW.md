# KIS-GRAPH-01C2A: Bounded selected-memory graph projection

**Stage:** Internal, read-only library and contract tests. **Not** connected to Intelligent Search consumer response and **not** evidence of live graph access or consumer release.

## Source and responsibility

Implementation: `src/ai_karen_engine/core/memory/retrieval/selected_graph_projection.py`.
Tests: `tests/core/memory/retrieval/test_selected_graph_projection.py`.

This module belongs alongside NeuroRecall because only NeuroRecall can select, deduplicate and guard candidates. It does not query PostgreSQL, instantiate another memory retriever, invent a graph store, rank candidates, persist events or make provider decisions.

The sole public function, `project_selected_memory_graph(request=..., result=...)`, consumes `RecallRequest` and the matching completed `RecallResult`. It requires explicit non-default tenant and user and the same query scope. It drops candidate memories lacking a matching selection provenance receipt. No intermediate graph path, canonical event identifier, user identifier or original content is included in the returned view.

## Current edge contract

Only already-selected `postgres_graph` memory events with `record_type: memory_event`, `store: postgres`, `event_id` equal to the selected memory ID, direct `MENTIONS` and depth 1 can produce `memory_event -> entity` relationships. The entity label is the already-extracted matched entity cue, capped at 120 characters. Raw event IDs become scope-derived opaque IDs. Limit is 12 selected memories. A duplicate entity is represented once.

Output kind `selected_memory_graph` with `version:1`, `status: available|empty`, `nodes`, `edges`, `truncated`, `degraded`, `degradation_reason`.

The library does **not** authorize a caller to fabricate a RecallResult, nor does an opaque SHA-derived identifier constitute cryptographic confidentiality against guessed labels. It must only be invoked from a trusted runtime path **after** NeuroRecall has applied scoped selection and the live SourceLineageAuthorizer check. The browser cannot supply RecallResult.

## Not yet implemented

- Integration with `InternetCapabilityService` or plugin response, authorization and user consent for combining personal memories with public web results.
- Real source-revocation and historical source-ACL verification in a graph-facing endpoint; current source-lineage authorization remains NeuroRecall-owned.
- Canonical entity identifiers or disambiguation across events; this projection conservatively coalesces exact casefolded cues only for a transient view and should not be used to mutate entity identity.
- Temporal/contradiction/supersession/cause graphs, graph expansion, durable investigation state, or workflow execution.
- Runtime acceptance, database integration, browser acceptance, provider proof or production rollout.

## Minimum proof

```bash
pytest tests/core/memory/retrieval/test_selected_graph_projection.py -q
python -m compileall src/ai_karen_engine/core/memory/retrieval
ruff check src/ai_karen_engine/core/memory/retrieval/selected_graph_projection.py tests/core/memory/retrieval/test_selected_graph_projection.py
```

Test contract covers invalid/mismatched tenant/user/query; foreign memory exclusion; missing/tampered selected provenance receipt; non-graph source, non-direct/casual relations; oversized/empty entity cues; bounded event count and deterministic opaque IDs; absence of source event IDs, content, raw graph path, and explicit degraded state.

**Future integration acceptance:** runtime wiring must prove NeuroRecall is invoked with authenticated scope, live ACL is present for source-derived content, graph display data is revalidated on every read, and no raw database traversal can bypass the selected result. No permission to merge a release claim from passing unit tests alone.

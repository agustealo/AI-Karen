# KIS-GRAPH-01C2B: Live source authorization gate for graph recall

**Status:** Focused backend security PR. This does **not** enable a consumer cognitive-memory graph.

## Canonical owner

`src/ai_karen_engine/core/memory/retrieval/neuro_recall.py` owns candidate admission and recall selection. `HybridRetrievalRouter._query_graph` retrieves tenant/user-scoped graph paths, rehydrates canonical PostgreSQL event records through `PostgresEventSource.fetch_many`, and carries the event's `source_type` and `source_ref` in the candidate's provenance.

`PostgresEventSource` already applies `recallable_memory_event` and tenant/user constraints, but **event consent/scope does not prove current access to an external source**. The previously existing `SourceLineageAuthorizer` is live only for candidates with `source_lineage` or `derived_source_ids` keys, and the runtime composition currently does not inject a concrete source authorizer. Non-conversation graph events without those keys must not bypass verification.

## Security contract

For graph candidates identified as `postgres_graph`, require provenance `store=postgres`, `record_type=memory_event` and an `event_id` equal to the selected canonical memory ID. This protects the graph-specific authorization branch against missing/forged provenance.

For non-conversation source types, including unknown or missing `source_type`, require a non-empty `source_ref` **and** a live `SourceLineageAuthorizer.authorize(memory, request) is True` decision. When no authorizer is composed, deny such candidates. Verifier errors, denials or ambiguous decisions deny recall. Explicit `source_lineage` and `derived_source_ids` still follow the original strict structural checks and live verifier.

For `source_type=conversation`, retain the existing tenant/user and consent-filtered canonical event expansion path, plus NeuroRecall's persona and guardrail checks. This is *not* a grant to share conversation memories across personas or tenants.

## Verification

```bash
pytest tests/core/memory/test_neuro_recall_scope.py -q
pytest tests/core/memory/retrieval/test_selected_graph_projection.py -q
pytest tests/core/memory/retrieval/test_graph_provenance_expansion.py -q
python -m compileall src/ai_karen_engine/core/memory/retrieval
ruff check src/ai_karen_engine/core/memory/retrieval/neuro_recall.py tests/core/memory/test_neuro_recall_scope.py
```

Tests cover: valid same-scope conversation graph event; source types web/plugin/uploaded_document/empty/unknown without explicit lineage; missing graph event receipt; missing `source_ref`; live authorizer true/false/nonboolean; verifier exception; no leak of verifier secrets in result diagnostics.

## Explicit remaining boundaries

- A real production source-grant repository and ACL/revocation verifier are **not** constructed here. This PR keeps non-conversation graph recall closed until the canonical owner can supply one.
- No new external-search API, consumer graph endpoint, browser permission control or cross-source memory sharing is added.
- A string `source_type=conversation` is not independently verified by this selector; graph events come from the scoped canonical PostgreSQL event source. Any future untrusted graph candidate producer must supply an issuer-authenticated evidence envelope, not metadata alone.
- Before enabling external graph recall, audit every source family for grant ownership, deletion, revocation, source scope, query-time permissions, and graph publication consent. The live verifier must be injected through `MemoryRuntimeManager` composition and tested against PostgreSQL revocation races.
- RuntimePolicy remains responsible for whether memory is requested. NeuroRecall remains responsible for which already-authorized memory candidates can be selected. No new graph or authorization authority is created.

**Release status:** Internal recall hardening only; requires exact-head CI and security review before merge. Consumer readiness is unchanged.

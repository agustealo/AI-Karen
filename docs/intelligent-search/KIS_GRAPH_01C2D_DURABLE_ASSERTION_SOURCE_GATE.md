# KIS-GRAPH-01C2D: Canonical durable assertion source-provenance gate

## Security finding

Before this change, `PostgresRecallRetriever` joined `MemoryAssertion` to the canonical `MemoryEvent` but selected only the event payload, not `MemoryEvent.source_type` or `MemoryEvent.source_ref`. NeuroRecall's graph-specific source gate could reject graph-derived external events while the same external content, promoted to a durable assertion, lacked its source origin and could be selected as an ordinary memory.

## Ownership-preserving implementation

- **PostgreSQL** remains source of truth: the assertion query selects `MemoryEvent.source_type` and `MemoryEvent.source_ref` beside the same scoped, consent-filtered event. No untrusted event-payload metadata becomes authority.
- **PostgresRecallRetriever** attaches the canonical event source identity to the pre-existing `memory_assertion` provenance receipt. It does not make ACL decisions or create a new permission store.
- **NeuroRecall** validates that the receipt binds to the candidate's assertion ID and a nonempty event ID and source type. Direct `chat` and `conversation` event origins retain existing selection behavior. Any other source type must contain a source reference and receive an explicit `True` from the existing current-access verifier; missing verifier, ambiguous origin, error and denial all fail closed.
- **MemoryRuntimeManager** retains the existing optional source-authorizer composition path, with no source allowed by default.

The direct-origin allowlist intentionally excludes unclassified and historical external sources. A source named `user`, `plugin`, `web` or `uploaded_document` is not silently recast as chat.

## Proof and limitations

Unit tests cover canonical receipt formation independent of spoofed event-payload metadata, direct-chat retention, external-origin denial, invalid receipts, missing source references, and a live authorizer changing allow to deny between recalls.

The disposable PostgreSQL baseline now includes an external-source memory event. The canonical SQL still sees this valid event, but NeuroRecall must exclude its assertion without a current source authorizer, while continuing to select permitted chat assertions. Existing tenant, consent-revocation, and temporal eligibility checks remain in place.

```bash
pytest tests/core/memory/test_postgres_persona_provenance.py tests/core/memory/test_neuro_recall_scope.py -q
KAREN_TEST_POSTGRES_MEMORY=1 pytest tests/integration/test_live_canonical_memory_recall_baseline.py -q
ruff check src/ai_karen_engine/platform/memory/postgres/recall_retriever.py src/ai_karen_engine/core/memory/retrieval/neuro_recall.py tests/core/memory/test_neuro_recall_scope.py tests/core/memory/test_postgres_persona_provenance.py
```

This patch does **not** certify live external-source ACLs, durable profile-fact source permissions, all derived projection types, or consumer graph publication. Those must be inspected and governed separately. No generic source-grant table, bypass, or consumer route is added.

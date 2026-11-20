# KIS-GRAPH-01C2C: Canonical source-authorizer composition

## Objective

Enable the existing `MemoryRuntimeManager` to receive a **trusted, issuer-composed** implementation of the existing `SourceLineageAuthorizer` contract and pass it to the one `NeuroRecall` selector. This is a dependency-composition repair, not a new authorization service or permissions database.

## Ownership

- **RuntimePolicy** determines whether a request may retrieve memory at all.
- **MemoryRuntimeManager** constructs canonical memory adapters; its optional `source_authorizer` argument exists for trusted runtime composition, not request metadata or an API route.
- **NeuroRecall** checks tenant, user, persona, provenance and candidate guardrails; for source-derived data it delegates current source eligibility to `SourceLineageAuthorizer.authorize`.
- **PostgresEventSource** applies existing event consent and temporal predicates, but memory consent does not prove access to an external source.

The manager rejects an authorizer that does not expose `authorize`; it rejects simultaneously passing a preconstructed `recall_service` and a separate `source_authorizer`, so that one authority cannot silently shadow the other. A manager without an explicit verifier constructs NeuroRecall with `source_authorizer=None`. Existing fail-closed behavior is unchanged.

## Verification contract

- Construct the manager with an issuer-supplied verifier and observe a real NeuroRecall selection: a denied or non-true authorization returns no external graph memory, while an explicit true decision can admit the same tenant/user-scoped candidate.
- Construct without a verifier and verify non-conversation graph sources are excluded even when `source_ref` is supplied.
- Assert invalid and conflicting composition is rejected before initialization.
- Preserve existing NeuroRecall lineage, graph-provenance, tenant/persona and consent tests.

```bash
pytest tests/core/memory/test_neuro_recall_scope.py tests/core/memory/retrieval/test_selected_graph_projection.py -q
python -m compileall src/ai_karen_engine/core/memory
ruff check src/ai_karen_engine/core/memory/memory_runtime_manager.py tests/core/memory/test_neuro_recall_scope.py
```

## Release boundary

This change **does not** supply a production external-source grant/revocation verifier. In particular, no provider is allowed merely because it has a `source_ref`, `source_lineage` metadata, or a recorded grant. A real verifier must independently read the current source-specific ACL, owner and revocation state, and be composed by the trusted application startup. No source family is enabled by default. No consumer API or UI graph is enabled.

Before enabling external graph evidence, add source-specific live permission checks with real-source PostgreSQL revocation tests, including cross-tenant/user denial, grant revocation between requests, missing source records and verifier errors. Keep graph projection selected-only and read-only.

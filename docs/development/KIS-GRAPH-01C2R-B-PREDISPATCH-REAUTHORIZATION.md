# KIS-GRAPH-01C2R-B: Live memory source reauthorization before inference

**State:** Implementation candidate. Not a publication-time revocation certification.

## Authority

- Selection: canonical NeuroRecall and scoped `CognitiveContext`.
- Event and derived record: `PostgresEventSource` reading `memory_event` and the selected canonical projection in the same scoped transaction.
- Consent: existing `recallable_memory_event` predicate, including current `consent_scope`.
- Dispatch: existing `ChatRuntime` and `ExpressionGateway`; ReasoningExecutor cannot consume selected memory before the same check succeeds.

## Source contract

From NeuroRecall-selected `MemoryEntry`, `MemoryRuntimeManager.recall_context` now propagates `updated_at` as a top-level selected-record revision. `RuntimeEvidenceResolver` attaches it to a validated origin record. The revision is not taken from stored custom metadata or request metadata.

The platform reader rechecks event visibility plus derived row identity, tenant/user, linked event, validity, applicable lifecycle/consent state and exact updated_at. The absence of a verified event origin or record revision for a declared PostgreSQL memory raises `memory_source_revoked_or_unverifiable`. Non-PostgreSQL/ephemeral sources remain under their existing scope gates, not an invented SQL event grant.

The returned `True` means only that the selected sources passed a fresh read at that point in time. It is not a lock or lease over generation.

## Proof

- `pytest tests/core/runtime/test_graph_live_reauthorization.py -q`
- `pytest tests/core/runtime/test_runtime_evidence_resolution.py -q`
- `KAREN_TEST_POSTGRES_MEMORY=1 pytest tests/integration/test_live_memory_publication_reauthorization.py -q -rs` against an isolated migrated PostgreSQL database
- Existing Main Quality and live PostgreSQL memory workflow include those modules.

## Remaining security gates

A source can be revoked after this check while the provider is still running. Streaming token publication, non-stream cancellation, terminal receipts, transcript persistence, source revision races, HTTP disconnect and multi-instance event invalidation require an observed, supported cancellation/lease contract. Prior streaming deltas cannot be withdrawn. Do not label publication-time revocation complete until those cases are proven on a real host.

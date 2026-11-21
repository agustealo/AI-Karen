# KIS-GRAPH-01C2R-C: Observed revocation before content publication and finality

**Status:** Draft security candidate. This is not an atomic revocation or user-readiness certification.

## Existing source of truth

The canonical `PostgresEventSource.authorize_selected_records` from KIS-GRAPH-01C2R-B checks durable consent, selected row validity, and revision. `ChatRuntime` remains the execution, streaming, cancellation and transcript-finality owner. No duplicate memory registry or cancellation orchestrator is introduced.

## Implementation

1. Recheck after `ExpressionGateway.generate` before treating the returned text as eligible for successful persistence.
2. Recheck selected memory immediately before each `execute_stream` outward content yield. This also covers reasoning, graph and other execution topologies that publish content through the outer stream.
3. Treat `memory_source_revoked_or_unverifiable` as terminal: do not invoke the fallback model or persist a successful response.
4. Recheck after stream completion, before streamed memory persistence and before transcript write. This narrows the interval between selection and finalization, but does not eliminate a commit-to-revocation race.
5. Reuse existing asynchronous generator cancellation and queue backpressure; no new provider response synthesis.

## Proof

- `pytest tests/core/runtime/test_chat_runtime_stream_contract.py -k "revoked_memory_between_stream_deltas or revocation_after_final_stream_delta or post_provider_and_finality_source_fences" -q`
- `pytest tests/core/runtime/test_graph_live_reauthorization.py -q`
- `KAREN_TEST_POSTGRES_MEMORY=1 pytest tests/integration/test_live_memory_publication_reauthorization.py -q`
- Exact-head Main Quality, Chat System Burn, real PostgreSQL proof, production first boot and independent review.

## Explicit limitations

These source checks are not PostgreSQL transaction-bound authorization leases. Revocation committed just after a successful check can still race the next byte or the canonical transcript transaction. They perform a database check per outward content chunk for durable selected records, which must be measured under load before deployment. They do not retract previously emitted content or prove cross-instance revocation notification or bounded cancellation latency. The runtime's error path must never promote revoked output to a fallback, transcript, or memory success; observed host trials and database-concurrency acceptance remain required.

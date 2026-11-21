# KIS-GRAPH-01C2R-D: Concurrent revocation and streaming cost acceptance

**Status:** Acceptance contract only. No implementation or performance certification is claimed by this document.

## Baseline and owner

This work follows merged PR #1191 (`f159009d0bbca68272918fd1a10c47cb24727ece`) and the explicit limitations in `KIS-GRAPH-01C2R-C-STREAM-FINALITY.md`. `PostgresEventSource.authorize_selected_records` is the durable consent/revision authority; `ChatRuntime` owns publication, cancellation, denial, fallback, and finality. The existing persistence owner controls transcript and memory writes. Do not add an authorization cache, competing memory registry, route-level fallback, or duplicate orchestrator.

## Observable security contract

1. **Revocation before publication:** after a committed revoke is observed by the canonical check, no subsequent outward content chunk is emitted. An explicit `CHAT_MEMORY_SOURCE_REVOKED` denial is emitted and no success finality is recorded.
2. **Revocation between chunks:** chunks already sent cannot be retracted. Subsequent publication must be blocked at the next reauthorization boundary; the producer must close and execute its finalizer.
3. **Revocation after final chunk, before persistence:** success transcript/memory finality must not be recorded after an observed denial.
4. **Revocation between persistence and transcript finality:** record the exact durable side effects, their commit ordering and any irreducible race. Do not claim rollback or atomicity unless transactions prove it.
5. **Unverifiable source:** missing/revised rows, authorization DB failure, connection-pool exhaustion and timeout must fail closed; no alternate model/fallback may turn the denial into successful content.
6. **Cross-tenant:** selected row authorization must remain tenant-scoped, with no cross-tenant recall, denial metadata leakage, or unauthorized mutation.

## Deterministic PostgreSQL proof

Use two separate committed database connections and synchronization barriers, never sleeps, to interleave the revocation transaction with each publication/finality boundary. Test at least two independent runtime instances against the same database, including overlapping sessions, cancellation, and repeated revocation. Assert outward chunk sequence, denial receipt, producer finalizer, persisted user/assistant records, memory records, tenant isolation, and audit metadata. Keep fixtures isolated and clean up all rows and sessions. Existing mocked stream tests are complementary, not a substitute.

## Streaming performance protocol

Measure **p50, p95, p99** and sample counts for per-chunk authorization query latency, first-byte latency, inter-chunk delay, throughput, cancellation-to-finalizer latency, connection pool wait, DB errors, and end-to-end response latency. Compare memory-free, authorized-memory, and revoked-memory cases at concurrency 1, 8, 32, and 64 with consistent output chunk counts and record counts. Report host CPU/RAM, database version and pool size, network topology, token/chunk sizes, warm-up, run duration, and repeat count. Never omit failed or timed-out samples. Set numerical release thresholds from measured product requirements before declaring a pass, rather than fabricating thresholds afterward.

## Required observability

Use the canonical structured telemetry path with correlation/request/session/tenant IDs, provider/model, runtime engine, fallback level, authorization duration/count, denial code, cancellation status and persistence outcome. Redact memory text, prompts, tokens and secrets. Avoid high-cardinality IDs in Prometheus labels.

## Merge gates

- New real-PostgreSQL integration tests with deterministic interleavings and tenant/RBAC coverage.
- Existing `test_chat_runtime_stream_contract.py`, `test_graph_live_reauthorization.py` and `test_live_memory_publication_reauthorization.py` remain green.
- Reproducible measured load report, including errors and hardware/configuration.
- `python -m compileall src`, `ruff check src tests`, targeted `pytest`, exact-head Main Quality, Chat System Burn, PostgreSQL memory, Production First-Boot, independent review.
- No production readiness claim until the above evidence is attached.

## Explicit non-goals

No atomic PostgreSQL-to-network guarantee is implied; bytes already emitted cannot be withdrawn. Any stronger lease or transactional design requires a separately reviewed ownership, security and consistency proposal.

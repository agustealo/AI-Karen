# KCR-04F | Canonical PostgreSQL recall at exact temporal boundaries

## Ownership and scope
The existing PostgresRecallRetriever selects memory_assertion JOIN memory_event. The existing recallable_memory_event predicate owns source-event consent. NeuroRecall retains final selection/ranking authority. This adds executable integration evidence, not a second store, schema, orchestration layer, or runtime policy.

## Risk and executable proof
Both the assertion and its source event must satisfy half-open UTC temporal validity at one selection instant. The exact valid_to endpoint is expired; the exact valid_from endpoint is eligible. Current consent denial applies before ranking and LIMIT. Foreign tenant/user rows must never be returned.

The new test inserts real PostgreSQL event/assertion rows with distinct starts/ends, future states, consent denial, revocable custom scope, and foreign tenant/user records, then reads at one microsecond before, at, and after the boundary. It injects a deterministic UTC clock only in the test, asserting one selection instant, live revocation, and top_k isolation. Every fixture is cleaned up under its original tenant.

## Workflow
Existing live-postgres-memory-proof.yml profile-memory-postgres job runs the test with KAREN_TEST_POSTGRES_MEMORY=1. A skip does not count as acceptance. The test uses the canonical SQL retriever without replacing it with a mocked query.

## Evidence limitations
This verifies SQL-level tenant/user predicates and current consent on a disposable database connection, NOT FORCE RLS with a least-privilege DB role, production as-of retrieval, user-facing quality, or actual migration parity. A separate migration-owner/RLS review is required for the stronger database-enforced isolation claim.

## Proof commands
- python -m compileall -q tests/integration/test_live_memory_recall_boundary_contract.py
- PYTHONPATH=src KAREN_TEST_POSTGRES_MEMORY=1 pytest tests/integration/test_live_memory_recall_boundary_contract.py -q -rs
- Full profile-memory-postgres workflow and exact-head Main Quality

# KCR-04A | Observed PostgreSQL canonical recall baseline

**Status:** Test and CI implementation submitted; exact-head PostgreSQL acceptance pending. This page does not claim a benchmark result until the workflow executes successfully.

## Architectural owner and scope
- Real durable candidates: `PostgresRecallRetriever` over `memory_assertion JOIN memory_event` with `recallable_memory_event` policy and consent-scope checks.
- Final recall selection: actual `NeuroRecall`, instantiated over the production PostgreSQL retriever in isolation to avoid introducing a second selector.
- Canonical memory runtime/Redis/graph: unchanged. **A whole-runtime probe has not yet been performed**.
- Database: existing disposable `pgvector/pgvector:pg16` CI service, initialized with canonical ledger SQLAlchemy schema and existing profile-memory RLS setup. No production or unrelated Supabase access.

## Executable proof
[`tests/integration/test_live_canonical_memory_recall_baseline.py`](../../../tests/integration/test_live_canonical_memory_recall_baseline.py):
1. Commit six disjoint real PostgreSQL memory events and assertions: public/current, private/current, other-user, other-tenant, expired, and not-yet-valid. No mocked session or fake SQL.
2. Execute `PostgresRecallRetriever.recall` across scoped candidates and assert source-event lineage.
3. Capture **the same SQLAlchemy SELECT constructed by the actual retriever**, compile with synthetic-only literal values, and execute `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` in the same tenant-scoped connection. A report records the real query plan type and elapsed timing, but makes **no percentile claims from a single observation**.
4. Exercise the real `NeuroRecall` selector over the PostgreSQL retriever. Confirm source-event provenance and scoped selection before/after private scope revocation.
5. Inventory available/installed PostgreSQL extensions, whether `memory_items` exists in the isolated ledger DB, and actual index names. These observations are **not** production index measurements.
6. Delete only fixture event/assertion/scope records under their original tenant IDs.

## Important distinction
- The canonical durable SQL currently reads **`memory_assertion`** and uses `contains()` substring predicates, **not** a native pgvector distance operator or `to_tsvector / ts_rank` on `memory_items`.
- The canonical migrations may define `memory_items` vector/HNSW and FTS/GIN features. This workflow initializes the *ledger schema*, not every historical migration, so it cannot report production index health.
- A successful run proves the query and selected candidates against live disposable PostgreSQL. It does **not** establish HNSW use, full end-to-end graph/STM behavior, quality against paraphrases, or production p95.

## Acceptance and next step
- `profile-memory-postgres` must execute the test with `KAREN_TEST_POSTGRES_MEMORY=1`; skips are not accepted.
- Workflow publishes a sanitized JSON observation and JUnit report as a short-lived CI artifact. The JSON contains no stored content, private user data, or emitted SQL.
- GitHub exact-head checks and review must pass before merge.
- A subsequent migration-complete run must verify actual pgvector and FTS **query** execution and indexed scoring under tenant/consent policy at `MemoryRuntimeManager`. Do not invent providers, fork a new memory repository or ship a native full-text/vector change before the source-writer lineage and migration ownership are audited.
- RLS against a least-privilege role is already exercised for `profile_fact` by existing CI, **not yet proven for `memory_assertion`** by this particular test.

**New runtime packages/services:** none.

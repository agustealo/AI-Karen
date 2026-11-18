# KCR-01 | Retrieval storage and evidence wiring audit

**Status:** source inspection complete; SQL compiler and synthetic NeuroRecall fixture tests proposed. **Live database query execution is not proven.**  
**KAREN baseline:** [merged research wiki](README.md), commit `0e6b0b8473f075c1b6d994ebb8a7fb0e81f2d7ac` (2026-11-17).  
**Scope:** audit-only, no new persistence service, model, package, route, or runtime authority.

## Precise finding

KAREN's checked-in Supabase migration creates a pgvector/FTS **`memory_items`** index path. The current canonical NeuroRecall durable retriever selects from **`memory_assertion JOIN memory_event`** with substring/SQLAlchemy `.contains()`, tenant/user scope, consent, valid-time and confidence/recency ranking.

These are distinct tables and execution paths. The existence of pgvector and FTS indexes **does not** establish that canonical memory recall uses them. Nor does the runtime diagnostics string `"storage": "postgres_pgvector_fts"`.

| Layer | Confirmed source | Confirmed behavior | Evidence status |
| --- | --- | --- | --- |
| Migration pgvector | [`03_memory.sql`](https://github.com/agustealo/AI-Karen/blob/main/supabase/migrations/20260827030000_03_memory.sql) | `CREATE EXTENSION vector`; `memory_items.embeddings` HNSW cosine index | Migration defined; deployed state unverified |
| Migration FTS | [`05_schema_security_finalization.sql`](https://github.com/agustealo/AI-Karen/blob/main/supabase/migrations/20260827050000_05_schema_security_finalization.sql) | Generated `memory_items.content_tsv` tsvector and GIN index | Migration defined; live query usage unverified |
| Canonical durable candidates | [`recall_retriever.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/platform/memory/postgres/recall_retriever.py) | `memory_assertion` SQL + event consent/validity + substring filtering | Production composition confirmed; not HNSW/FTS query |
| Runtime composition | [`memory_runtime_manager.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/memory_runtime_manager.py) | NeuroRecall combines assertion/profile/user-state/procedural/STM+graph candidates | Wired source, live host unverified |
| Entity matching | [`entity_resolver.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/platform/memory/postgres/entity_resolver.py) | PostgreSQL trigram similarity on scoped entities/aliases | Source implementation confirmed; independent backend proof pending |
| Embeddings | [`embedding_manager.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/model_runtime/embedding_manager.py) | Canonical real-only embed function exists, but legacy `get_embedding` path contains synthetic fallback methods | Verify all consumers and never promote synthetic vectors to governed semantic evidence |

**No schema migration or rewrite should occur until the write/read lineage of both `memory_items` and `memory_assertion` is traced.** A historical schema must not be removed just because it is not used in one composition path.

## Code-backed first probes

- [`test_recall_query_contract.py`](../../../tests/benchmarks/memory/test_recall_query_contract.py) compiles the real `PostgresRecallRetriever` statement with an injected test session. It proves the *query is built with tenant/user, consent and valid-time predicates*, without a live DB. It deliberately **does not** prohibit a future FTS/vector implementation.
- [`test_recall_quality.py`](../../../tests/benchmarks/memory/test_recall_quality.py) exercises the real NeuroRecall candidate governance and selection against labeled *synthetic* retriever output. It can detect a regression in final ranking/guardrails but cannot measure search quality of pgvector, FTS or actual graph traversal.

**Caution:** Code-based probes are stronger than `assert True` but still weaker than a live PostgreSQL and real embedding/model acceptance test. These probes are not the final sprint benchmark.

## Required live acceptance follow-up
1. Identify every writer and reader of `memory_items`, `memory_assertion`, `memory_event`, and vector metadata, plus the canonical embedding provider and model revision.
2. On an isolated *real* PostgreSQL instance with applied migrations and RLS, insert consented scoped events, source revisions and embeddings. Compare actual `EXPLAIN (ANALYZE, BUFFERS)` plans for vector / FTS / current substring retrieval; sanitize query plans and private data.
3. Run the *real* `MemoryRuntimeManager.recall_context` path under authenticated scope. Capture retriever sources, generated SQL, actual vector similarity and full event IDs, redacted in public reports.
4. Test no-leakage across tenants/users, source revocation, deleted/corrected entries and projection replay. Never use raw `memory_items` results outside NeuroRecall/NeuroVault policy.
5. Produce baseline R@5/10, nDCG, MRR, as-of correctness, p50/p95, footprint and failure rates with reproducible fixtures.
6. Only then propose consolidation or algorithm adaptation. If pgvector/FTS are not wired, **repair existing PostgreSQL path** before considering an outside framework.

**Outcome:** no external framework adoption; focus on proof of existing KAREN database/search capabilities.

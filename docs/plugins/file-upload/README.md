# KFILE-UPLOAD-01: Universal Upload Platform

> Status: proposed architecture, **not shipped or certified**. This is the canonical implementation roadmap distilled from the 2026-11-22 KFILE-UPLOAD-01 specification. The full source plan remains an external planning artifact until verified against live repository code. Track proof per slice.

## Decision

**Upload once, reference anywhere authorized.** Keep three independent extensions: **File Upload** for contextual destination selection, resumable transfers, batch progress and receipts; **File Explorer** for authorized navigation and selection; **Content Intelligence** for explicitly requested parsing, analysis and indexing. None owns canonical bytes, ACLs or policy decisions. Reuse existing ArtifactStore, plugin kernel, runtime policy, PostgreSQL persistence, and NeuroRecall. Do not assume Milvus, Elasticsearch or live LlamaIndex.

## Current evidence versus missing behavior

| Source | Verified from main | Not established |
| --- | --- | --- |
| `extensions/plugins/file-explorer` and `extensions/file_explorer_inventory.py` | Host-gated metadata inventory, source references, owner revalidation | Complete upload/download integration and production browser acceptance |
| `services/database/repositories/artifact_store.py` | Canonical artifact identity, lifecycle and `ArtifactUploadRequest.data: bytes` | Resumable streaming |
| `core/langgraph_orchestrator/context/file_upload_service.py` | Local file writes, in-memory `_processing_jobs`, `asyncio.create_task` | Durable recovery and canonical authority |
| `core/langgraph_orchestrator/context/file_context_store.py` | Process-local compatibility context | Durable artifact metadata |
| `extensions/plugins/content-intelligence` | Bounded inline lexical analysis/search/compare | Durable ingestion and indexing |
| `platform/memory/postgres/recall_retriever.py` | Scoped SQL substring recall | Production vector ranking |

See [KFILE-UPLOAD-01A ownership audit](08-migration-and-legacy-audit.md) for the reference map and proof gaps.

## UX: contextual Upload to…

Entry points: Chat composer, File Explorer, Knowledge, Writing Studio, Code Workspace, global Upload to…, drag-and-drop/paste, and advanced Bulk Import. The current workspace suggests an authorized destination, but never grants it. If exactly one destination is authorized, use a compact upload action. If several exist, show a chooser. Explicitly disclose sharing, durable knowledge indexing, publication, retention and agent execution. Show server-derived limits, not model-token limits. The UI must not invent successful transfers or indexing.

User-visible processing recipes: `store_only`, `conversation_reference`, `extract`, `index`, `analyze`, `code_project`. Only advertise supported and authorized recipes. The upload manager supports progress, pause, resume, retry, cancellation, batch manifests, per-file errors, and durable receipts. A browser reload must reconstruct server truth.

## Architecture and ownership

```text
Chat / Explorer / Knowledge / Studio / Code / Global Upload
       -> File Upload extension (UX and transfer workflow)
       -> authenticated thin API
       -> canonical runtime authorization + plugin kernel eligibility
       -> trusted upload session/transfer authority (PostgreSQL)
       -> canonical ArtifactStore (storage bytes, identity, revisions, ACL)
          -> File Explorer (metadata references)
          -> Content Intelligence (optional governed processing)
          -> Chat/Studio/agents (freshly authorized references)
          -> NeuroRecall (authorized retrieval candidates)
```

The plugin cannot receive unrestricted storage credentials, invent an ACL, or read arbitrary host paths. Runtime owns execution; CORTEX decides eligibility only. Deactivation denies new plugin work but must not delete canonical artifacts. Every consumer rechecks current source authorization and revision.

## Proposed contracts, not existing endpoints

- `GET /api/uploads/destinations`: policy-, tenant-, workspace- and plugin-state-scoped destination discovery. Descriptor includes destination ID, kind, allowed MIME types, per-file/batch limits, recipes, retention, sharing support, confirmation requirement and policy version.
- `POST /api/uploads/sessions`: authenticated principal-derived session with manifest, destination, recipe and idempotency key; return opaque session ID, server-defined part limits and expiry.
- `PUT /api/uploads/sessions/{id}/parts/{part}`: bounded streaming part with validated byte range, digest and ownership; short-lived scoped transfer capability if direct multipart storage is supported.
- `POST /api/uploads/sessions/{id}/commit`: idempotent final verification and atomic publish, recheck current ACL/policy/quota and return durable canonical artifact receipts.
- `GET /api/uploads/sessions/{id}`, `POST /.../cancel`, `POST /.../resume`, `GET /api/uploads/activity`: durable owner-scoped state and activity.

These paths require an API contract audit before implementation; do not add competing routes. Proposed upload states: created, receiving, verifying, committed, failed, cancelled, expired, quarantined. Processing states are separate: queued, extracting, extracted, indexing, ready, failed, revoked. `committed` must never mean `indexed`.

## Storage and recovery invariants

Use PostgreSQL for durable session/part/job/receipt state, reusing existing schema where possible; Redis may coordinate but cannot be the only ledger. Enforce bounded-memory streaming, quotas while receiving bytes, idempotent part and commit retries, cryptographic integrity, content inspection, atomic publish, safe staging cleanup, and crash recovery. Archives require path/symlink, expanded-size, depth, count and ratio limits. Deduplication cannot reveal cross-tenant existence or ownership. Content SHA is not an ACL revision. All processing and references are tied to source identity and revision.

## Security and observability

Authorize before part write, commit, processing, retrieval, reference sharing and reactivation. Reject forged tenant/owner, destination, source ID, receipt, cursor, stale policy and stale revision. Apply existing RBAC, tenant RLS, consent, retention, audit, plugin lifecycle and source ACL checks. Emit structured events (session_created, part_received, part_verified, upload_committed, upload_failed, retry_scheduled, upload_cancelled, processing_queued, extraction_complete, index_ready, source_revoked, cleanup_complete). Include correlation/request IDs, principal scope, session/job/artifact IDs, destination, recipe, state, bytes, attempt, timings, policy decision and sanitized error code. Do not log contents, filenames or secrets.

## Delivery gates

1. **U0 ownership audit**: active imports, routes, adapters, UI, migrations, tests and overlapping PRs; classify legacy paths; zero unresolved duplicate-authority decisions.
2. **U1 extension and destination registry**: governed discovery and contextual UI only; prove disabled-plugin, RBAC, tenant, forged-destination denial; no storage mutation yet.
3. **U2 durable transfer**: streaming/multipart ArtifactStore contract, PostgreSQL ledger, idempotent commit, quota, digest, recovery and cancellation; prove on real Postgres/storage.
4. **U3 workspace integration**: File Explorer, Chat, Studio, Knowledge, Code and activity center; prove browser keyboard/focus and 390/768/1024/1440px, reconnect and stale-principal cancellation.
5. **U4 processing recipes**: durable extraction/index jobs, optional adapters, source-lineage and revocation; no mandatory LlamaIndex.
6. **U5 bulk/retrieval**: folder/archive batches, incremental reindex, measured throughput, memory, recovery, recall and source revocation. Evaluate PostgreSQL FTS/pgvector with real query plans; no assumed vector backend.
7. **U6 cleanup**: remove duplicate legacy code only after verified replacement, tests, reference audit and migration compatibility. Preserve security, recovery and migration history.

## Adversarial acceptance

2 GiB reconnect/resume without duplicate commit; destination ACL revoked mid-transfer; cross-tenant session/digest/cursor probes; uncertain commit retry; source replacement while indexing; consent/deletion after indexing; archive bomb; plugin deactivation mid-job; Content Intelligence unavailable during store-only upload; 429 bounded backoff; large chat paste handled without silent truncation or invented model limits.

## Proof commands

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
# From the frontend package directory:
npm run lint && npm run typecheck && npm run test && npm run build
docker compose config
```

Run focused tests and real-service acceptance for each slice, then exact-head CI and post-merge checks. A documentation commit does **not** certify functionality.

## Related docs

- [File Explorer](../file-explorer/README.md)
- [Content Intelligence](../content-intelligence/README.md)
- [U0 ownership audit and migration register](08-migration-and-legacy-audit.md)

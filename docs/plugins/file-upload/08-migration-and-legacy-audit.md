# KFILE-UPLOAD-01A: Canonical Upload Ownership and Dependency Audit

**Status:** Initial source-level audit on `main`, 2026-11-22. **Partial, not U0 exit-certified.** No runtime behavior or deployment was changed by this documentation slice. The unresolved checks below are blockers to U1/U2 mutations.

## Source ownership register

| Component | Evidence observed | Classification | Proposed action |
| --- | --- | --- | --- |
| `services/database/repositories/artifact_store.py` | `ArtifactStore` interface and `ArtifactUploadRequest.data: bytes`; metadata, owner paging and lifecycle | Active canonical contract candidate | Preserve; audit backend and migrate toward bounded streaming via compatible extension |
| `services/database/repositories/supabase_artifact_store.py` | `SupabaseArtifactStore` implements upload/download, owner metadata, bounded owner-text, lifecycle and storage-client access | Existing concrete backend, production deployment not proven | Reuse and audit atomicity, streaming, storage quotas, rollback and credential boundaries |
| `core/langgraph_orchestrator/context/file_upload_service.py` | Local `./file_uploads` writes, `_processing_jobs` dict, `asyncio.create_task`, extract/analyze/index methods | Legacy or misplaced **candidate**, active call sites not yet exhaustively traced | Do not remove or plugin-wrap directly; establish imports, routes and compatibility first |
| `core/langgraph_orchestrator/context/file_context_store.py` | Process-local `_contexts` compatibility state | Compatibility candidate | Keep until active references and replacement proof |
| `extensions/plugins/file-explorer/` | Host-injected bounded inventory, list/select, artifact metadata adapter | Correct owner of navigation/selection | Preserve; no second explorer |
| `extensions/file_explorer_inventory.py` | Typed plan and kernel eligibility checks, source revalidation | Correct host integration | Reuse |
| `docs/plugins/file-explorer/README.md` | Describes authenticated owner inventory API and outstanding browser integration | Documentation with mixed historical status sections | Reconcile after real browser proof |
| `ui_launchers/Karen-AI-Theme/src/plugin_repo/file-explorer/FileExplorerPage.tsx` | Controlled authorized inventory props, loading/error and pagination handling | Correct UI projection | Reuse; confirm actual host binding and browser acceptance |
| `extensions/content_intelligence_sources.py` | Host-verified owner-text admission through canonical store and plugin kernel | Correct bounded content consumer | Reuse for authorized processing; do not infer general ingestion |
| `extensions/plugins/content-intelligence/` | Inline bounded lexical analyze/search/compare | Correct plugin with incomplete durable ingestion | Extend only after governed job and source contracts |
| `platform/memory/postgres/recall_retriever.py` | Tenant/user-scoped assertion recall using substring predicates | Correct existing retrieval | No assumption of vector-index production readiness |

## Security boundary already visible

The File Explorer adapter returns source identity/revision metadata, not storage credentials or bytes. The host validates kernel eligibility and authorized execution plans. The Content Intelligence host uses owner-verified source reads. Preserve these checks at every new upload, commit and processing boundary. Never let upload destination choice or File Explorer selection act as an ACL grant.

## Key architecture risks

1. The historical upload service's process-local job map cannot survive restarts; its detached `asyncio.create_task` work is not durable.
2. Both the historical upload path and canonical `ArtifactUploadRequest.data: bytes` indicate potential whole-file buffering; no proven bounded-memory resumable path exists.
3. Existing `SupabaseArtifactStore` is a real implementation class, but repository presence does not prove the configured production storage backend, transaction atomicity or upload endpoint routing.
4. Content Intelligence currently does not provide durable indexing; do not report a stored artifact as knowledge-ready.
5. File Explorer's owner inventory and UI component exist, but actual deployed browser wiring and full acceptance remain separate proof obligations.
6. Source SHA-256 proves content revision, not authorization revision.
7. Do not assume Milvus, Elasticsearch, active LlamaIndex, pgvector query execution or a distributed worker merely from legacy files/configuration.

## Unresolved U0 checks, required before implementation

- [ ] Search **all imports and dynamic references** of `FileUploadService`, `FileContextStore`, `ArtifactStore.upload`, `SupabaseArtifactStore`, and attachment-related entry points, including plugins and tests.
- [ ] Enumerate actual authenticated upload routes, request models, frontend chat attachment actions and direct-storage paths; identify route-level policy bypasses.
- [ ] Confirm runtime repository factory bindings and deployed storage configuration, without treating a source default as live service evidence.
- [ ] Inventory existing PostgreSQL upload/artifact tables, migrations, RLS, retention, idempotency and queue infrastructure before proposing schema.
- [ ] Inspect extension manifest and host/UI registration patterns; choose a single canonical destination registry owner.
- [ ] Check overlapping open/merged PRs and live main drift before any code changes.
- [ ] Run baseline focused tests, real PostgreSQL tests and browser File Explorer acceptance; record exact-head checks and actual failures.
- [ ] Resolve whether any historical processing steps are actively used and preserve them or migrate with contract tests.
- [ ] Document legacy retirement map with replacement path, risk, import/reference audit and rollback strategy.

## Proposed implementation dependency graph

```text
U0 reference and deployment audit (this document; incomplete)
  -> U1 plugin capability + backend destination discovery (no storage writes)
  -> U2 canonical streaming adapter + PostgreSQL transfer ledger
  -> U3 contextual UI and Explorer/Chat/Studio references
  -> U4 Content Intelligence processing recipes and durable receipts
  -> U5 measured bulk/retrieval acceptance
  -> U6 guarded legacy cleanup
```

## Proof plan

Focused tests already in repository include:

```bash
pytest tests/extensions/test_file_explorer_artifact_source.py tests/extensions/test_file_explorer_host_inventory.py tests/api/test_file_explorer_inventory_api.py -q
pytest tests/extensions/test_content_intelligence_owner_sources.py tests/extensions/test_content_intelligence_plugin.py -q
pytest tests/architecture/test_shared_file_explorer_ui_boundary.py -q
```

Also run `python -m compileall src`, `ruff check src tests`, `mypy src`, full backend tests, frontend lint/typecheck/test/build, `docker compose config`, real Postgres/storage integration, exact-head CI and real browser acceptance. **These commands are prescribed, not claimed executed by this source inspection.**

## U0 exit decision

**Not passed.** The inspected source establishes the correct separation and highlights unsafe legacy patterns, but a complete import graph, active deployment wiring, storage capability proof and baseline test run remain outstanding. Do not delete or redirect production upload paths until those facts are proven.

[Return to Universal Upload plan](README.md).


## U0 follow-up: authenticated artifact ingress discovered

**Confirmed source:** `src/ai_karen_engine/api_routes/artifacts.py` defines `APIRouter(prefix="/artifacts")`, with `POST /artifacts/upload`. The route obtains `tenant_id` and `user_id` from `get_current_user` via `_artifact_principal`, resolves the canonical store from `DatabaseServiceFactory.get_service("artifact_store")`, constructs `ArtifactUploadRequest`, and invokes `store.upload(request)`. This is a **real existing upload ingress**; the universal extension must integrate rather than invent a competing storage route.

**P1 design blocker (source-level):** `data = await file.read()` materializes the entire upload before calling the repository, with no visible size bound in this handler. `ArtifactUploadRequest.data: bytes` carries the same whole-buffer contract. A multipart parser or upstream proxy limit may exist elsewhere but has **not** been verified, so do not claim an unlimited exploit or production OOM. Before U2, establish and test enforced end-to-end limits, then add bounded streaming and resumable session capability to the canonical authority.

**Existing API scope:** This module also exposes owner-page, metadata, archive, restore, delete and purge operations. `_require_owned_artifact` checks current tenant/user ownership before per-artifact lifecycle operations. Preserve this behavior, and separately verify RBAC/quotas, upload content inspection, audit and authorization of `conversation_id`/`message_id` attachments. Authenticated ownership of the upload does not automatically prove permission to attach it to an arbitrary conversation.

**Concrete implementation decision:** U1 destination discovery is additive and read-only; it must not replace `POST /artifacts/upload` until compatible streaming and security acceptance is proven. U2 should extend canonical artifact storage and transaction semantics, not duplicate `SupabaseArtifactStore` inside the plugin.

**Additional evidence:** `src/ai_karen_engine/services/database/repositories/supabase_artifact_store.py` implements `SupabaseArtifactStore` with upload/download, owner metadata paging and bounded owner-text methods. `src/ai_karen_engine/extensions/content_intelligence_sources.py` uses kernel-governed owner text reads. These are implemented source paths, **not proof that production Supabase or processing jobs are healthy**.

**Audit status remains open:** exhaustive dynamic imports, exact runtime configuration, actual storage limits, route registration, migration/RLS coverage, browser acceptance and exact-head CI are not yet established.


## U0 follow-up: canonical storage transaction and key risks

Inspected `SupabaseArtifactStore.upload()` on live `main`:

1. **Orphan-object risk (confirmed code path):** object storage `_bucket().upload(storage_key, data, ...)` completes **before** the `files` PostgreSQL INSERT and commit. If database persistence fails, the broad exception handler returns failure without compensating object deletion. This is a non-atomic cross-system write. U2 requires a durable staging/finalization protocol and orphan reconciliation, not an imaginary distributed transaction.
2. **Untrusted filename in storage key (confirmed):** `storage_key = f"{request.tenant_id}/{artifact_id}/{request.filename}"` directly interpolates the request filename. The route passes `file.filename` without visible normalization. Object-store path semantics, backend validation and traversal impact require testing; do **not** assert filesystem traversal without proof. U2 must use server-generated opaque keys and store display names only as validated metadata.
3. **Unbounded byte materialization (confirmed):** repository uses `data = request.data or b""` and `_bucket().upload(..., data, ...)`; download also materializes storage bytes into `io.BytesIO(data)`. The new transfer contract must enforce streaming bounds for both upload and download where applicable.
4. **Failure information exposure (requires ingress trace):** storage errors include `str(exc)` in `RepositoryResult.error`; upload API passes `result.error` into HTTP 500. Verify secret/path redaction and stable client-safe error codes.
5. **Cross-resource binding (requires proof):** `conversation_id` and `message_id` are copied from request parameters to artifact metadata without visible conversation-ownership validation in the upload route. Add owner-scoped binding checks before associating an artifact with a conversation/message.

**Priorities:** P1 orphan reconciliation and filename/key hardening; P1 bounded memory and transfer quotas; P1 authenticated cross-resource binding; P2 sanitized errors. Severity is provisional until deployment controls and exploitation conditions are established.

**Do not hot-patch by replacing the canonical route with a new plugin endpoint.** First write focused failing tests against the actual `SupabaseArtifactStore` and artifact route, then implement compatible hardening and exact-head validation.

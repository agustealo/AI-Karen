# Content Intelligence: Standalone Plugin Developer Wiki

**Status:** v0.2.0 implementation scope and roadmap. This documentation distinguishes shipped behavior from proposed work.

## 1. Non-negotiable architectural boundary

The feature is a standalone KAREN extension. All feature-owned code lives under `src/ai_karen_engine/extensions/plugins/content-intelligence/`. Core remains unchanged. The plugin uses the existing extension host, runtime authorization, provider access and audit contracts. Disabling the extension must not disable or change Karen's memory, chat, plugin lifecycle or file storage.

Canonical owner separation:

| Area | Owner |
| --- | --- |
| Plugin discovery, enablement, RBAC, execution policy | Existing extension kernel |
| Chat, prompts, provider selection | Existing runtime |
| Global memory, final recall | Existing NeuroRecall / memory services |
| Canonical uploaded file bytes and ACL | Existing authorized file owner |
| Content parsing/indexing/relationship hints | Content Intelligence extension |
| Document-specific derived projections | Plugin, once durable storage is authorized |
| Source permissions and source revisions | Canonical file authority, never index metadata |

The plugin must never turn index metadata into file access permissions. An index hit is only a candidate until its live source ACL and revision are checked.

## 2. Current implementation (v0.2.0)

The manifest is `plugin_manifest.json` with entrypoint `handler:MainExtension`. It is disabled by default and requests no memory, user-data, or network permissions. It uses the canonical extension host's `run(params, execution_context)` invocation.

Four read-only operations are functional on **inline invocation-supplied text**, not on arbitrary files:

- `browse`: groups already-authorized documents by optional opaque `folder_id` values, returns inventories and content fingerprints. Folder labels do not grant access.
- `analyze`: SHA-256 text fingerprints, character counts, deterministic term frequencies and shared-term document pairs.
- `search`: bounded line-level lexical matching with input-text character offsets.
- `compare`: term intersection/differences and Jaccard similarity between two documents.

These are strictly lexical features. Shared terms are **not** verified entity edges or causal relationships. Excerpts are raw user-supplied text, not generated or attested facts. The plugin does not save, index, or memorize supplied documents.

## 3. Execution contract

`operation` is `analyze`, `search`, `compare`, or `browse`; `documents` is an array of 1 to 12 objects, each with required keys `id`, `name`, and `text` and optional `folder_id` (a bounded opaque label, not a filesystem path or authorization claim). `search` additionally requires `query`. `compare` requires `left_id` and `right_id`.

Limits: 100,000 characters per document, 300,000 characters total, 512 characters per query, and 12 returned search results. Each search excerpt is an exact substring of the supplied document, with `offset`, `end_offset`, and SHA-256 fingerprint for source-coordinate verification. Browse groups only the documents explicitly supplied in the authorized invocation. No filesystem paths, remote URLs, arbitrary object metadata or unrestricted field names are allowed.

Execution context must be an instance of the host's `ExtensionExecutionContext` with explicit UUID tenant and user identifiers. It must be supplied by the trusted host; request data must not manufacture one. Host RBAC and invocation policy remain mandatory. A caller must not pass confidential content until the canonical upload owner has authorized its disclosure to this plugin.

## 4. Processing architecture (proposed, not implemented)

1. Canonical upload owner verifies actor, tenant, workspace, file/folder ACL, retention and source revision.
2. Existing kernel invokes the plugin with a trusted source-resolution capability, never an arbitrary path.
3. Plugin parses permitted file types into source-referenced elements; optionally uses LlamaIndex adapters as installed/configured.
4. Plugin creates rebuildable chunk, lexical, vector, and graph projections with source and revision lineage.
5. Search returns bounded source candidates; fresh source ACL/retention/revision verification happens before evidence is disclosed.
6. NeuroRecall remains the final memory-recall authority when the runtime chooses to incorporate this plugin's candidate evidence.
7. Delete, ACL changes, source updates and deactivation revoke access and/or invalidate projections before search responses can expose stale content.

**No direct LlamaIndex query bypass.** `src/ai_karen_engine/integrations/sr_llamaindex_adapter.py` is a deliberately fail-closed compatibility adapter. Do not re-enable it.

## 5. Planned independent plugin modules

`adapters/parsing`: format-specific adapters (PDF, DOCX, XLSX, PPTX, images via an approved OCR or vision capability), with source-coordinate mapping.

`adapters/llamaindex`: an **optional** version-pinned document extraction and retrieval backend; cannot independently authorize a document.

`services/ingestion`: revision-pinned, retry-safe, idempotent, cancellable jobs with durable receipts.

`services/document_graph`: source-backed entity and relation candidates, temporal facts, contradiction metadata and traceable confidence.

`services/retrieval`: authorized keyword, semantic, graph and mixed retrieval with stable citation coordinates.

`ui/`: file/folder Content Explorer, indexing health, graph browsing, cited answers and policy-aware review actions.

Do not add these modules until their actual service boundaries and contracts are proven against existing host capabilities. No parallel file store, memory layer, task orchestrator, API authorization or model router.

## 6. Data and governance contracts (required before persistence)

Use immutable source identifiers and content revisions. A derived chunk includes: tenant ID, canonical source ID, revision, chunk ID, source coordinates, extraction engine/version, visibility lease and provenance. The source identity must survive file move/rename; source revision changes must invalidate stale derived evidence. Folder inheritance must be checked against authoritative ACLs at access time.

Entity edges must record their source spans, extraction engine/version, confidence, valid-time bounds and approval state. Graph relationships cannot establish permission, employee role or legal status on their own.

Read and index operations must have bounded resource budgets; log request/correlation IDs, tenant, source revision and count metrics without private document contents. Reprocess only on canonical source events or an authorized refresh.

## 7. Plugin lifecycle

Install through the existing plugin host; validate manifest and dependency constraints. Activate only after host authorization. Shutdown disables new execution. Since v0.2.0 is stateless, no document projections require cleanup. Future uninstall behavior must retain original uploaded files under their canonical owner and delete or retain *plugin-owned* derived data according to approved policy and durable deletion receipts.

## 8. Acceptance gates

**Implemented scope:** closed schema, no filesystem/network I/O, explicit tenant/user execution context, deterministic bounded analysis, source-offset lexical retrieval, no accidental durable memory writes.

**Not yet accepted:** actual uploaded-file registration, source ACL adapters, persistent indexing, LlamaIndex integration, graph extraction, UI, async worker jobs, file lifecycle invalidation, source-aware citation verification, and external connector acceptance.

Next PRs must provide real local tests and PostgreSQL-backed integration evidence as applicable, not synthetic claims of deployed production capability. Include adversarial tests for tenant crossover, stale ACLs, superseded revisions, deletion races, malformed documents, processing cancellation and duplicate job replay.

## 9. Proof

Run local test slice: `pytest tests/extensions/test_content_intelligence_plugin.py -q`. Before production acceptance also run `python -m compileall src`, `ruff check src tests`, and all relevant exact-head plugin CI checks. The existence of a PR does not establish mergeability or user-ready UX.

## 10. Existing source references

- Extension contracts: `src/ai_karen_engine/extensions/contracts.py`
- Host base: `src/ai_karen_engine/extensions/platform/core/host/base.py`
- Manifest schema: `src/ai_karen_engine/extensions/platform/core/manifest.py`
- Existing sample plugin: `src/ai_karen_engine/extensions/plugins/pocket-tts/`
- Retired unscoped adapter: `src/ai_karen_engine/integrations/sr_llamaindex_adapter.py`
- Memory authority: `src/ai_karen_engine/core/memory/README.md`

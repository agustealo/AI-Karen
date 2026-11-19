# KAREN File Explorer: Shared Plugin Developer Wiki

**Status: v0.2.0 host-inventory and reusable UI contracts implemented; live uploaded-file integration not implemented.**

## Ownership

File Explorer is one standalone, reusable extension under `src/ai_karen_engine/extensions/plugins/file-explorer/`. It is the **only** owner of the explorer browsing UI, folder navigation, file listing and selection behavior. Content Intelligence, Writing Studio, agents, business plugins and future extensions use its governed capability instead of creating file explorers.

The core runtime remains authoritative for authorization, provider use, tools, policy and audit. The canonical file provider owns file bytes, durable source identity, ACL and revisions. File Explorer neither hosts the bytes nor becomes a new file storage backend. Content Intelligence owns document analysis, extraction, derived graph relationships and LlamaIndex adapters, but not explorer navigation.

## Current API

Declared `file-explorer` extension entrypoint: `handler:MainExtension`. Plugin disabled by default; no filesystem, network, memory or user-data permissions are requested.

Invocation operation `list` takes optional `parent_id` and returns sorted immediate children with identifier, folder membership, kind, size, revision and optional SHA-256. Invocation operation `select` takes `source_ids` (1–24) and returns opaque source/revision references, never document content or filesystem paths.

The trusted host must inject `resource_scope.file_explorer_entries` (up to 200 entries) and `resource_scope.file_explorer_grant="host_verified"` into a valid `ExtensionExecutionContext` with a real policy decision and `file-explorer` in allowed capabilities. Caller-supplied inventory is forbidden. This is an intended integration gate, **not verified host wiring**. The current implementation does not query uploaded files.

Inventory entries use exact fields `source_id`, `parent_id`, `kind` (`file` or `folder`), `name`, `revision`, `size_bytes` and `sha256`. IDs are opaque, bounded, and path separators are invalid. The engine checks duplicates and malformed fields but **does not certify** ACLs, source freshness or complete folder trees.

## Cross-plugin contract

A consumer asks the kernel for the `file-explorer` capability, receives authorized selection references, and passes those references to the existing authoritative source owner for a fresh permission and revision check. It never trusts selection receipts alone as read permission. Read-by-ID and processing must enforce current tenant/actor/document ACL, retention, consent and revision before accessing bytes.

The standalone UI contribution provides one shared controlled file picker and navigator, embeddable through the existing plugin host when authorized inventory props are supplied. Provider-specific stores must be adapters behind its source registry, never hardwired into every consuming plugin.

## Required next slices

1. Audit and identify the actual durable source/ACL authority for uploads. The historical `FileContextStore` alone is not a sufficient governed enterprise source.
2. Add a host-issued trusted inventory provider capability with source ACL/revision checks and server-side paging. Do not invent grants in a client or plugin.
3. Connect the implemented [reusable explorer UI](02-shared-ui.md) to a trusted live host inventory provider; prove keyboard/focus behavior, pagination, and no fake provider availability.
4. Integrate Content Intelligence by reference after reauthorization; preserve source lineage and prove tenant, revision and deletion boundaries.
5. Expand backends through optional adapters (local file authority and explicitly connected cloud sources) with consistent capabilities and no duplicate explorer.

## Threat model

Untrusted `parent_id`, `source_ids`, labels and file metadata never grant authority. Reject traversal IDs, overlarge inventories, duplicate IDs, missing scope, missing policy decisions, arbitrary paths, and unknown selections. Avoid logging document names/content. File/folder moves should not change canonical IDs. A deactivated plugin must no longer return new references. Never advertise the snapshot as a fresh authorization check.

## Proof

`pytest tests/extensions/test_shared_file_explorer_plugin.py -q` followed by repository quality gates, exact-head CI, and production host integration acceptance. Passing pure-engine tests does not mean live file browsing is ready. No KAREN Core changes are part of this plugin slice.


## Canonical ArtifactStore adapter (implemented, not host-wired)

The optional `artifact_source.py` adapter uses KAREN's existing `ArtifactStore` repository contract rather than storing file bytes. It can list **owner-owned** files from a tenant-scoped artifact listing and freshly revalidate `source_id` plus SHA-256 content revision against canonical metadata. It never returns a storage key, raw bytes, or an ACL grant. Archived/deleted records and mismatched owner or tenant are excluded or denied. Failure to retrieve metadata is an authorization failure, not an empty successful result.

This adapter must be injected by the trusted host after execution policy resolution. Existing `ArtifactStore.list_artifacts()` lists all artifacts in a tenant and has no owner-scoped cursor; the adapter filters to the authenticated owner and fails closed if more than 200 owner records would be needed. It **does not yet provide scalable pagination**, authorized cross-user sharing, virtual folders, or a live registered UI. An artifact content checksum is not an ACL revision: consumers must perform fresh checks before opening bytes. Do not wire an untrusted plugin payload directly into the repository constructor or grant selection by metadata alone.

Tests: `pytest tests/extensions/test_file_explorer_artifact_source.py -q`.

## Frontend integration

See [Shared UI and selection contract](02-shared-ui.md). It is a controlled component, not a separate backend or an authorization source.

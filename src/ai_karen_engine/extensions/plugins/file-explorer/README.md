# File Explorer: Shared standalone extension

**v0.1.0 scope:** a governed navigation/selection projection over a host-authorized, bounded inventory. It does NOT yet connect to live uploaded files, access the filesystem, offer a UI, or resolve source bytes.

All file/folder navigation belongs to this extension. Content Intelligence, Writing Studio and other plugins consume its canonical selection references through the existing governed plugin execution mechanism. No plugin may implement a competing explorer.

The host must supply an authenticated `ExtensionExecutionContext` with a nonempty policy decision, explicit tenant/user UUIDs, the `file-explorer` allowed capability and a trusted `resource_scope.file_explorer_entries` snapshot with `file_explorer_grant=host_verified`. This is a **host integration contract**, not an assertion that the current runtime supplies it. Consumer plugins must reauthorize current source ACLs and source revisions before reading.

See [developer wiki](../../../../../docs/plugins/file-explorer/README.md).


## Canonical ArtifactStore adapter (implemented, not host-wired)

The optional `artifact_source.py` adapter uses KAREN's existing `ArtifactStore` repository contract rather than storing file bytes. It can list **owner-owned** files from a tenant-scoped artifact listing and freshly revalidate `source_id` plus SHA-256 content revision against canonical metadata. It never returns a storage key, raw bytes, or an ACL grant. Archived/deleted records and mismatched owner or tenant are excluded or denied. Failure to retrieve metadata is an authorization failure, not an empty successful result.

This adapter must be injected by the trusted host after execution policy resolution. Existing `ArtifactStore.list_artifacts()` lists all artifacts in a tenant and has no owner-scoped cursor; the adapter filters to the authenticated owner and fails closed if more than 200 owner records would be needed. It **does not yet provide scalable pagination**, authorized cross-user sharing, virtual folders, or a live registered UI. An artifact content checksum is not an ACL revision: consumers must perform fresh checks before opening bytes. Do not wire an untrusted plugin payload directly into the repository constructor or grant selection by metadata alone.

Tests: `pytest tests/extensions/test_file_explorer_artifact_source.py -q`.

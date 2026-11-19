# File Explorer: Reusable Plugin UI Contract

**Status: controlled frontend component implemented; live host inventory integration not implemented.**

## Single owner

Only the File Explorer extension contributes the reusable file navigator and picker UI. Content Intelligence, Writing Studio and other KAREN plugins consume its selection contract rather than implementing their own navigation pages.

The GUI manifest is `src/ai_karen_engine/extensions/plugins/file-explorer/manifest.json`, and the React entrypoint is `ui/FileExplorerPage.tsx`. The existing validated plugin UI materialization process must publish it; do not edit the generated import map or Core routes.

## Host integration

The `SharedFileExplorer` component accepts `authorized`, `items`, `loading`, `error`, `selectedSourceIds`, `multiSelect`, `onSelect`, and `onRefresh`. It renders an honest unavailable state when `authorized` is not true, and it performs no network calls or filesystem reads.

The host must obtain the inventory using a trusted authenticated action, validate tenant/user/resource ACL and revision, and pass only authorized entries. The `authorized` prop is a UI display hint, **not an authorization decision**. The selectable view is restricted to 200 entries for this slice and supports up to 24 selections. A selection returns `source_id`, `revision`, `sha256`, and `kind` only.

Other plugins must reauthorize every source at the source owner when accessing bytes. The client callback cannot confer access rights, and stale references must fail.

## Accepted UI behaviors

Responsive file/folder listing, folder navigation, text filtering, single or multiple selection, callback events, loading, error, empty and unavailable states. Native buttons/inputs provide keyboard interaction and accessible names.

## Not accepted

Live uploaded-file listing, pagination, standalone backend UI API, authorized preview/download, nested folder permissions, automated plugin-to-plugin mount, visual browser regression, and third-party cloud stores. They must not be advertised as working without host integration and observed acceptance.

## Controlled keyset-page navigation (implemented UI contract)

The existing `SharedFileExplorer` now accepts `hasMore`, `nextCursor`, `onNextPage(cursor)` and `pageKey` from the trusted authenticated host, in addition to the original controlled inventory and selection props. It never fetches data, caches cursors, or treats pagination evidence as authorization. A missing callback, absent/oversized cursor or inconsistent terminal-page evidence makes the explorer unavailable instead of silently presenting an incomplete inventory as complete. Selecting **Next page** clears local selection and filters and asks the host to retrieve the next server-authorized page. The UI remains limited to 200 entries per supplied page and 24 selections per page.

The host **must** produce a new `pageKey` on every accepted page or identity/authorization-scope transition. That remounts the controlled viewer and clears local folder, filter and selection state. Host callers must also cancel or ignore stale/out-of-order responses, never combine pages from different users, tenants or authorizations, and resolve errors separately from genuinely empty inventories. `onRefresh` clears selection before the host requests a fresh authorized page. This is not an authorization boundary: consumers still revalidate source ACL, deletion status and revision at the canonical owner before bytes are accessed.

**Outstanding:** The authenticated UI host has not yet connected these props to `FileExplorerInventoryHost` through a canonical runtime endpoint. No successful live uploaded-file browser acceptance, cross-page persistent selection or authorized download is claimed. UI contract regression: `pytest tests/architecture/test_shared_file_explorer_ui_boundary.py -q`.

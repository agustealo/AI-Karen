# File Explorer: Reusable Plugin UI Contract

**Status: dashboard host and selection-to-analysis API wiring implemented in source; consumer release acceptance remains outstanding.**

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

**Outstanding:** No successful hosted browser/real-database acceptance, cross-page persistent selection or authorized download is claimed. The authenticated dashboard host wiring described below is now present in source. UI contract regression: `pytest tests/architecture/test_shared_file_explorer_ui_boundary.py -q`.

## Authenticated dashboard host wiring

The canonical dashboard plugin route now wraps the existing dynamically loaded `PluginHost` only when its catalog-provided plugin ID is `file-explorer`. The host is `src/ui_launchers/Karen-AI-Theme/src/components/plugins/FileExplorerInventoryHost.tsx`; the plugin component itself continues to receive only controlled presentation props through `PluginHost.componentProps`. There is **no second explorer UI, plugin route registry, file-store client, or bearer grant**.

The authenticated browser API client retrieves `/api/plugins/file-explorer/inventory` from the existing plugin router. The host validates the reference-only response, displays only the currently authorized server page (maximum 200 entries), carries the exact continuation cursor to Next page, clears selection on refresh and page changes, and assigns `pageKey` from the authenticated principal and accepted page generation. It gates rendering on tenant/user/role/permission identity and ignores late responses from unmounted, previous-page, or previous-principal fetches. An unavailable or malformed response never becomes an authorized empty list; the UI visibly reports loading, errors, and retry. The browser never calls storage APIs, uploads files, or uses localStorage for inventory.

This is UI source integration, **not yet certification** of real hosted login/API/production PostgreSQL use. Before consumer-ready status, perform authenticated end-to-end browser acceptance with a real owner account and multiple pages, concurrent refresh/navigation, logout or tenant switch during pending requests, disabled plugin, removed artifact/revision, and responsive/focus behavior at 390, 768, 1024 and 1440 pixels. The source fetch uses the canonical `apiClient`, which owns authentication and token refresh; unresolved promises are ignored by generation/cleanup guards rather than granting access to old responses. Any later byte consumer must freshly revalidate owner and revision in backend runtime.

## Current-page selection integrity

The dashboard's `FileExplorerInventoryHost` treats `onSelect` references as
untrusted presentation events. It now requires **each** selected entry to
match the authenticated current page on `source_id`, `revision`, `sha256`,
and `kind`. Duplicate IDs, stale revisions, altered digests, foreign-page
IDs, forged kinds, oversized selections and mixed valid/invalid lists fail
closed with selection cleared. This guard does not convert a selection into a
storage authorization receipt; all future byte consumers still need fresh
server-side owner and revision checks. Regression coverage lives in the
existing `FileExplorerInventoryHost.test.tsx` suite.

## Content Intelligence analysis recovery

The dashboard-owned `FileExplorerInventoryHost` passes only the selected `source_id` and SHA-256 `revision` to the existing Content Intelligence source endpoint. This is a request, not a transferable storage grant. The consuming runtime independently reauthorizes the caller and reads the current owner-active artifact only after kernel admission; changed bytes, revoked ownership, deleted sources, and failed checks do not produce analysis success.

When analysis fails, the panel never displays synthetic or partial results. The user may retry a transient failure against the current selection, or choose **Refresh inventory and reselect**. That action invalidates the in-flight presentation attempt, clears the prior selection, and requests a new owner-scoped inventory page through the authenticated host. The user must select the new reference before another analysis; the browser never silently substitutes a new revision for the requested one. A denial does not disclose whether a particular source exists, changed, or belongs to a different owner.

Source integration tests cover a rejected stale revision, metadata refresh with a changed SHA-256, mandatory re-selection, a new analysis request carrying the refreshed revision, a transient retry, and suppression of private API errors. This is mock-backed frontend regression evidence, **not** observed production PostgreSQL or browser certification. The independent backend output-lineage validation is separately tracked in PR #1206 and must not be duplicated in this UI slice.


## KPLUG-08 disposable PostgreSQL handoff acceptance

The existing CK-GEN artifact PostgreSQL proof runs the
`test_real_postgres_explorer_selection_to_content_revision_and_owner_races`
case in `tests/integration/test_live_code_artifact_revocation_postgres.py`.
It uses canonical migrated `files` rows, the existing `SupabaseArtifactStore`,
`ArtifactSourceAdapter`, `FileExplorerInventoryHost`,
`ContentSourceHost`, and the Content Intelligence lexical engine. No new
source owner, schema, RLS policy, database provisioning, or release workflow
is introduced. The test-only kernel shim does **not** substitute for the
separate kernel/RBAC authorization tests.

The proof covers real committed metadata revisions, rejecting stale selected
hashes before analysis publication, requiring refreshed source references,
revoked ownership, and a concurrent PostgreSQL `FOR UPDATE` writer racing
the canonical `FOR SHARE` owner-read path. Analysis never claims that an old
selected digest automatically follows a newly committed source revision.

The existing `.github/workflows/ckgen-artifact-postgres-proof.yml` creates
the dedicated `karen_code_artifact_test` database with canonical migrations
and seeded tenants, then runs this test along with its established PostgreSQL
revocation and RLS proofs. Test Storage bytes are an in-process fixture.
A passing run is **real PostgreSQL authorization/revision evidence**, not
live Supabase object-store integration, a production runtime deployment,
or authenticated browser consumer acceptance. Those remain separate gates.

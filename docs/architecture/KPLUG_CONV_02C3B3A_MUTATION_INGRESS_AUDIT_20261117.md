# KPLUG-CONV-02C3B3A: Physical mutation caller inventory and ingress denial

**Status:** Source-scoped ingress hardening. Not a global lifecycle-release certification.
**Repository:** `agustealo/AI-Karen`. Owner: canonical `PluginService`,
`RuntimePolicyEnforcer`, `ApprovalService`, `PluginLifecycleLedger`, and `PluginKernel`.
**Rule:** An administrator role and an HTTP verb never substitute for a
fresh authenticated action-bound human approval and one-shot global revision.

## Active caller census

| Surface / owner | Before | B3A behavior | Remaining acceptance |
| --- | --- | --- | --- |
| `api_routes/plugins/plugins.py` POST `/{plugin_name}/enable` | Thin HTTP handler called `PluginService.enable_plugin` directly | Explicit, audited HTTP 409. No raw enable | Implement reviewed admin confirmation and canonical backend context/approval binding |
| Same, POST `/{plugin_name}/disable` | Direct `PluginService.disable_plugin` | Explicit, audited HTTP 409. No raw disable | Same as enable, with separate revision-bound approval |
| Same, POST `/reload` | `PluginService.refresh_plugins` could update runtime eligibility | Explicit, audited HTTP 409. No refresh | Govern multi-plugin refresh/reconciliation with global claim rules |
| `api_routes/plugins/store.py` POST `/install` | `PluginService.enable_plugin` used as local-catalog install | Preserve existence/version/quarantine checks, then audited HTTP 409 until exact approval. Never return fake activation | Distinguish package publication from local activation; implement real confirmed activation contract |
| `api_routes/extensions/extensions.py` POST `/{extension_name}/load`, `/unload` | Called platform manager's unapproved compatibility loader | Both return audited HTTP 409; manager is not invoked | Expose real actor/session-bound review and execution, not fake request metadata |
| `extensions/platform/core/manager.py` `load_extension`, `unload_extension` | Called raw PluginService enable/disable | Require typed `ChatExecutionContext`, exact `PluginLifecycleApprovalScope`, nonempty approval ID; delegate to `PluginService.execute_approved_lifecycle`, demand `verified_committed` | Connect only through a trusted authenticated caller with a real approval |
| Same, `reload_extension` | Implicit enable after refresh | Refuse; reload is a sequence of separately approved physical transitions | Define a multi-operation plan with committed intermediate revision |
| Same, `refresh_registry` / `reload_runtime` | Rebuilt live runtime without durable lifecycle admission | Refuse until governed | Implement safe registry reconciliation with one authoritative global fence |
| Same, `refresh_extensions` | **GET catalog reads invoked `PluginService.refresh_plugins`** | Reads canonical service snapshot without refresh | Prove startup snapshot consistency with durable global observations |

The ordinary HTTP handlers continue requiring their existing authenticated
RBAC dependencies before returning approval-required. No new untrusted
request field, approval token or fake authenticated session is accepted.
The response is intentionally an explicit failure. Existing UI consumers
already surface backend errors; any action control implying instant success
needs a separate approval-flow UX update before activation is re-enabled.

## Explicitly NOT complete or certified in this slice

1. `PluginService.enable_plugin` and `disable_plugin` remain legacy low-level
   compatibility methods that call `PluginKernel.enable`/`disable` directly.
   They are still used by existing local runtime tests and may have more
   internal callers. They must not be exposed as public management grants.
2. `PluginService.refresh_plugins`, `PluginKernel.refresh` and initial
   `PluginKernel.initialize(auto_discover=True)` still rebuild live runtime
   registrations, including manifest-default-enabled plugins. Initial bootstrap
   and recovery need a distinct lifecycle-state reconciliation contract.
3. `PluginService.install_uploaded_archive` and
   `uninstall_plugin_package` publish/move filesystem packages under local
   installation locks and refresh the kernel. Those are **not**
   enable/disable and need an application-global package revision/fence
   contract, not unsafe reuse of a ready-state enable approval.
4. `extensions/platform/core/plugin_lifecycle_manager.py` retains legacy
   registry load/unload code. Its active import/production-call status requires
   a whole-repository reference audit before removal or delegation. Do not
   delete this file or security logic based on its name.
5. The global PostgreSQL advisory lock serializes only participating callers.
   Existing local plugin roots are not proven shared across all production
   hosts. A lost connection releases advisory ownership even while the durable
   `in_flight` state remains unresolved. Do not advertise universal physical
   mutation safety or distributed plugin deployment readiness.
6. Channel and voice plugins have separate governed lifecycle owners; generic
   plugin enable/disable cannot borrow their permissions.
7. Conversational activation, admin approval issuance and frontend execution
   controls are **not released**. The approved-host method from B2B remains
   backend-only until authentic session and approval handoff is implemented.

## Proof and regression guards

- `tests/extensions/test_plugin_lifecycle_ingress_fence.py`: HTTP rejection
  audit, no raw kernel transition, extension facade exact-action delegation,
  no silent registry refresh in catalog reads.
- `tests/extensions/test_plugin_store_runtime_status.py`: Plugin Store
  management permission alone does not enable the plugin; quarantine remains
  a separate rejection.
- `tests/extensions/test_extension_catalog_http_auth.py`: an authorized
  admin HTTP load receives explicit approval-required rather than fake
  `enabled`.
- `tests/architecture/test_plugin_lifecycle_ingress_fence.py`: AST guards
  against reintroducing direct manager/PluginService writes in the affected
  mounted HTTP routes and platform facade. It also asserts that the existing
  governed executor still follows the policy/approval/SQL/kernel CAS chain.
- `.github/workflows/plugin-ci.yml`: runs the new architecture proof with
  Plugin Backend. Existing tests still prove runtime/backward-compatible
  code from B2A/B2B and real PostgreSQL claims.

**Proof commands:** `pytest tests/extensions/ tests/architecture/test_plugin_lifecycle_ingress_fence.py -q`,
`pytest tests/integration/test_plugin_lifecycle_ledger_postgres.py -q`
(with dedicated real PostgreSQL), `python -m compileall src`,
`ruff check src tests`, `docker compose config`, and exact-head Main
Quality / Plugin Backend / Security / first-boot. No source-only scan can
prove a cross-worker production installation is shared or prevent a new
unscanned internal caller.

## Next logical slices

**B3B, durable approved admin UX:** implement server-authoritative preflight
and policy decision, approval creation/decision, authenticated session and
conversation binding, and one-shot management execution through
`PluginService.execute_approved_lifecycle`. UI displays pending, rejected,
unknown and `verified_committed` truth. No browser-side policy fallback.

**B3C, global kernel/refresh/package control:** reconcile initial state
and runtime refresh; govern package publication/removal with separate
global serializable locks and immutable evidence; audit and consolidate
legacy manager references; use real PostgreSQL concurrent workers,
crash/restart and multi-host physical root acceptance. Only afterward
consider conversational plugin mutation release.

# 04. Installation, lifecycle, provenance and trust

[Wiki index](README.md) · [Architecture](01-architecture.md)

**Status: Implemented trust boundary. A secure third-party execution sandbox is not yet verified.**

## Discovery is not execution

The canonical built-in root is
"src/ai_karen_engine/extensions/plugins/". The
[PluginKernel](../../src/ai_karen_engine/extensions/plugin_kernel.py)
controls discovery and admission. It must not be shadowed by a plugin-specific
registry or hardcoded path. Discoverable, installed, enabled, running, and
ready are different states and must be reported separately.

| State | Meaning | Executable? |
| --- | --- | --- |
| Discovered | An installed manifest was found | No |
| Validated | Manifest and dependencies satisfy their validators | Not by itself |
| Installed | Package exists with recorded provenance | Not by itself |
| Enabled | Host has accepted its lifecycle configuration | Only if all gates pass |
| Loaded | Approved implementation has been resolved | Still requires request-time admission |
| Ready | Verified runtime and dependencies can handle an action | Subject to authorization |
| Disabled | Explicit local policy or current eligibility prevents use | No |
| Quarantined | Provenance or isolation requirements not met | No |
| Unavailable | Dependency/model/DB/network resource not healthy | No |

Status words in legacy handlers may differ. UI must use the host's actual
lifecycle and readiness evidence instead of assuming an instance return value
is enough.

## Built-in reviewed code versus ZIP upload

A first-party plugin is shipped through an operator-controlled source review
and trusted release process. Only an explicitly approved first-party built-in
may use the existing in-process Python executor.

Manual ZIP upload via "/api/store/upload" records
".karen-upload-origin" and publishes a disabled package. That marker is
**permanent provenance evidence**, not a togglable preference. Upload alone
does not authorize code execution; the uploaded package cannot self-promote
to first-party by changing its own manifest, role declaration, or paths.

The current executor does **not** provide a verified OS-level sandbox for
untrusted code. Requests for untrusted, subprocess, container or WASM
execution fail with "isolation_unavailable" rather than executing in the
application process. The historical "ExecutionMode.SANDBOX" argument is a
compatibility name, **not** a sandbox security guarantee.

## Durable manual enable/disable

For approved built-ins, "rbac.default_enabled" is an initial default, never
permission to erase later user choices.

- Explicit successful enable publishes ".karen-manual-enabled" with exact
  verified "enabled" contents.
- Disable publishes ".karen-manual-disabled" before changing runtime state.
- If enabled and disabled markers both exist after a crash, disable wins.
- Invalid, symlinked, malicious or uploaded markers cannot grant permission.
- Catalog refresh retains valid explicit intent but rechecks trust, dependency
  resolution, channel rules and policy.
- Disabling or refreshing cannot race active execution admission or unload
  live code unsafely.

Only the authorized host may alter lifecycle markers. A plugin must never
create or delete them as part of a self-enable routine.

## Dependency and update policy

Declare dependencies in "dependencies.plugins" or
"dependencies.extensions". Kernel graph checking detects missing plugins and
dependency cycles. A declaration is not an installer: dependencies must
actually be installed, compatible and enabled under policy.

Updates require verifying changed source fingerprints, module eviction and
termination of the old implementation before a replacement becomes eligible.
Do not retain stale Python handler modules after an update or copy assets into
a second active plugin root. Use atomic publication, rollback on a failed
revision, and revision/identity fencing. Model artifacts and native binaries
require separate checksum, source and license evidence.

## Lifecycle runbook

1. Review the proposed source, license, dependencies, manifest and trust tier.
2. Confirm installation path and quarantine marker state.
3. Validate manifest, GUI assets (if any), prompt contracts and permission
   declarations.
4. Confirm allowed tenant/actor and, for configured plugins, persisted
   nonsecret settings and Vault credential **status**.
5. Verify all required services, models and runtime implementations are ready.
6. Enable through the canonical PluginService/PluginKernel action, not a
   handler endpoint.
7. Run authorized smoke execution and inspect structured audit events.
8. On disable/uninstall, reject new work, drain in-flight operations,
   revoke session access, unload safely and retain required audit records.
9. Confirm catalog/UI truth after restart and upgrade.

## Migration and data retention

Database schemas are migration-owned. A plugin must not create tables during
runtime initialization. Database migration plans need version fences, tenant
RLS, backup/restore, data retention policy, and safe rollback. Uninstall
does **not** imply deletion of user data, encrypted credentials, or audit
history without an explicitly authorized lifecycle operation.

## Evidence and negative tests

Required denial cases: forged built-in provenance; uploaded ZIP with manually
created enable marker; symlinked package; missing dependency; circular
dependency; malformed manifest; disabled plugin; concurrent refresh during
execution; stale module after upgrade; untrusted requested subprocess.
Every denial should be a real runtime denial, not just a UI warning.

Sources: [PluginKernel](../../src/ai_karen_engine/extensions/plugin_kernel.py),
[PluginService](../../src/ai_karen_engine/services/plugin_service.py),
[plugin developer guide history](../DEVELOPER_PLUGINS.md),
[governed UI materialization](../../src/ai_karen_engine/extensions/platform/core/registry/ui_materialization.py).

# Extension Kernel Authority Map

The extension tree is consolidated under `src/ai_karen_engine/extensions/`, but
physical colocation does not by itself prove a single runtime authority. This
file records the active ownership model after PLUGIN-KERNEL-2.

## Active ownership

| Responsibility | Owner | Notes |
| --- | --- | --- |
| On-disk plugin/catalog manifest | `extensions/platform/core/manifest.py` | Preserves UI, prompt, RBAC, config, dependency, marketplace, and catalog metadata. |
| Filesystem/catalog discovery | `extensions/platform/core/registry/` | The platform registry and discovery service are the only plugin filesystem discovery authority. |
| Catalog-to-runtime normalization | `extensions/plugin_kernel.py` | Projects the catalog manifest into the typed execution contract once. It does not discover independently. |
| Runtime execution registration | `extensions/registry.py` | Typed in-memory execution projection only. It is not a filesystem/catalog registry. |
| Lifecycle state | `extensions/contracts.py` + `extensions/registry.py` | `ExtensionLifecycleState` is authoritative for enabled/disabled execution state. |
| Invocation | `extensions/executor.py` | `ExtensionExecutionService` is the only plugin invocation path. |
| Action authorization | RuntimePolicy + `ActionExecutionGate` | User, tenant, session, policy decision, plugin identity, RBAC, and permissions remain fail-closed. |
| HTTP/application facade | `services/plugin_service.py` | Adapts API requests/results and metrics; does not select a second executor or registry. |

## Manifest rule

A plugin has one catalog manifest source on disk. The platform manifest is the
catalog schema because shipped plugins and UI materialization depend on its
prompt, RBAC, configuration, UI, and marketplace fields.

The execution manifest in `extensions/contracts.py` is a typed runtime
projection. It is intentionally narrower and contains execution governance such
as capabilities, tenant scope, trust tier, isolation, schemas, and side effects.
It is not a competing file format.

New code must not parse the same plugin manifest into an independent service
registry or construct an alternate execution policy model.

## Removed compatibility authorities

`services/plugin_discovery.py` and `services/plugin_execution.py` are removed.
Do not recreate service-layer filesystem discovery, sandboxing, provider/routing,
or plugin invocation logic. Application callers go through `PluginService`, and
execution reaches `ExtensionExecutionService` through `PluginKernel`.

The duplicate top-level `extensions/discovery.py` and `extensions/manifest.py`
loaders are also removed. Catalog discovery and manifest normalization belong to
the platform registry/manifest implementation above.

## Shipped plugin root

The canonical bundled plugin root is:

```text
src/ai_karen_engine/extensions/plugins/
```

Only that bundled root may be projected as first-party trust by the kernel.
Custom roots are projected as untrusted unless a separate signed/trust process
explicitly promotes them.

## Proof requirements

Changes to the extension kernel must prove at minimum:

```bash
python -m compileall src
pytest tests/extensions -q
ruff check src tests
mypy src
```

The repository's exact-head CI remains the merge authority. Plugin Ecosystem,
Main Quality, Production First-Boot, Agent/Medusa burns, and any automatically
triggered architecture/security gates must be green before merge.

This document supersedes the former 2025 claim that the migration was fully
complete. The earlier document described directories and files that no longer
matched the live repository and overstated the absence of duplicate authority.

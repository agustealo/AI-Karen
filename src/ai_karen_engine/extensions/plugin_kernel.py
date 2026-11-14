"""Canonical bridge between extension catalog truth and governed execution.

The extension platform manifest and registry own on-disk catalog truth. The
runtime registry is a typed execution projection of that catalog, not a second
discovery authority. All invocation is delegated to ExtensionExecutionService.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ai_karen_engine.extensions.contracts import (
    DataClassification,
    ExtensionCapability,
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionExecutionResult,
    ExtensionLifecycleState,
    ExtensionManifest as RuntimeExtensionManifestBase,
    ExtensionRegistration,
    RiskClass,
    ResultTrust,
    SideEffectLevel,
    TenantScope,
    TrustTier,
)
from ai_karen_engine.extensions.executor import ExtensionExecutionService
from ai_karen_engine.extensions.lifecycle import ExtensionLifecycleManager
from ai_karen_engine.extensions.platform.core.host.loader import ExtensionLoader
from ai_karen_engine.extensions.platform.core.manifest import (
    ExtensionManifest as CatalogExtensionManifest,
)
from ai_karen_engine.extensions.platform.core.registry.plugin_registry import (
    PluginRegistry as CatalogPluginRegistry,
)
from ai_karen_engine.extensions.registry import ExtensionRegistry

logger = logging.getLogger("kari.extensions.plugin_kernel")
_CANONICAL_PLUGIN_ROOT = Path(__file__).resolve().parent / "plugins"


class RuntimeExtensionManifest(RuntimeExtensionManifestBase):
    """Execution projection with explicit manifest-level policy fallbacks."""

    risk_class: RiskClass = RiskClass.LOW
    data_classification: DataClassification = DataClassification.PUBLIC


class _NormalizedExtensionLoader(ExtensionLoader):
    """Load host manifests through the platform compatibility normalizer."""

    def load_manifest(self, extension_name: str) -> CatalogExtensionManifest:
        extension_dir = self._resolve_extension_dir(extension_name)
        if extension_dir is None or not extension_dir.exists():
            raise FileNotFoundError(
                f"Extension directory for '{extension_name}' does not exist"
            )
        manifest_file = self._find_manifest_file(extension_dir)
        if manifest_file is None:
            raise FileNotFoundError(
                f"Manifest file not found for extension '{extension_name}'"
            )
        raw = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Extension manifest must be a JSON object")
        return CatalogExtensionManifest.from_dict(raw)


class _RuntimeInstanceAdapter:
    """Adapt existing ExtensionBase handlers to the canonical executor contract."""

    def __init__(self, instance: Any) -> None:
        self._instance = instance

    async def execute(
        self,
        payload: Dict[str, Any],
        context: ExtensionExecutionContext,
    ) -> Any:
        handler = getattr(self._instance, "execute", None)
        if not callable(handler):
            handler = getattr(self._instance, "run", None)
        if not callable(handler):
            raise RuntimeError("Extension exposes neither execute() nor run()")

        parameters = list(inspect.signature(handler).parameters.values())
        accepts_varargs = any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL
            for parameter in parameters
        )
        positional = [
            parameter
            for parameter in parameters
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        result = (
            handler(payload, context)
            if accepts_varargs or len(positional) >= 2
            else handler(payload)
        )
        return await result if inspect.isawaitable(result) else result


class _LazyRuntimeInstanceAdapter:
    """Resolve plugin code only when the canonical executor invokes the handler.

    The object itself is safe to register before authorization because it does
    not import or initialize plugin code. ``ExtensionExecutionService`` reaches
    this adapter only after plan, action, permission, RBAC, tenant, schema, and
    budget gates have passed.
    """

    def __init__(self, loader: _NormalizedExtensionLoader, plugin_id: str) -> None:
        self._loader = loader
        self._plugin_id = plugin_id
        self._adapter: Optional[_RuntimeInstanceAdapter] = None
        self._lock = asyncio.Lock()

    async def _resolve(self) -> _RuntimeInstanceAdapter:
        if self._adapter is not None:
            return self._adapter
        async with self._lock:
            if self._adapter is not None:
                return self._adapter
            instance = self._loader.load_extension(self._plugin_id)
            initialize = getattr(instance, "_initialize", None)
            is_initialized = getattr(instance, "is_initialized", None)
            already_initialized = (
                bool(is_initialized()) if callable(is_initialized) else False
            )
            if callable(initialize) and not already_initialized:
                await initialize()
            self._adapter = _RuntimeInstanceAdapter(instance)
            return self._adapter

    async def execute(
        self,
        payload: Dict[str, Any],
        context: ExtensionExecutionContext,
    ) -> Any:
        adapter = await self._resolve()
        return await adapter.execute(payload, context)


@dataclass(frozen=True)
class PluginCatalogRecord:
    manifest: CatalogExtensionManifest
    path: Path
    status: str
    checksum: Optional[str]
    error_message: Optional[str]
    is_valid: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "manifest": self.manifest,
            "path": self.path,
            "status": self.status,
            "checksum": self.checksum,
            "error_message": self.error_message,
            "dependencies_resolved": self.is_valid,
            "compatibility_checked": self.is_valid,
        }


class PluginKernel:
    """One bridge from catalog discovery to typed, governed execution."""

    EXECUTE_CAPABILITY = "execute"

    def __init__(
        self,
        extensions_root: Path,
        *,
        audit_sink: Any = None,
    ) -> None:
        self.extensions_root = Path(extensions_root)
        self._audit_sink = audit_sink
        self.catalog_registry = CatalogPluginRegistry(
            extensions_dir=str(self.extensions_root)
        )
        self.loader = _NormalizedExtensionLoader(str(self.extensions_root))
        self.runtime_registry = ExtensionRegistry()
        self.lifecycle = ExtensionLifecycleManager(self.runtime_registry)
        self.executor = ExtensionExecutionService(
            registry=self.runtime_registry,
            lifecycle=self.lifecycle,
            audit_sink=self._audit_sink,
        )
        self._catalog_manifests: Dict[str, CatalogExtensionManifest] = {}
        self._disabled: set[str] = set()
        # Retained even after a failed refresh updates catalog fingerprints.
        # Only a verified shutdown and module eviction can clear this fence.
        self._retirement_pending: set[str] = set()
        self._active: Dict[str, str] = {}
        self._initialized = False
        # Serialize catalog projection and explicit lifecycle mutations so
        # dependency eligibility cannot race enable/disable or refresh.
        self._state_lock = asyncio.Lock()

    @staticmethod
    def canonical_extensions_root() -> Path:
        """Single source of installed built-in extension package location."""
        return _CANONICAL_PLUGIN_ROOT

    @property
    def initialized(self) -> bool:
        return self._initialized

    def _is_builtin_root(self) -> bool:
        try:
            return self.extensions_root.resolve() == _CANONICAL_PLUGIN_ROOT.resolve()
        except OSError:
            return False

    async def initialize(self, *, auto_discover: bool = True) -> None:
        if self._initialized:
            return
        if auto_discover:
            await self.refresh()
        self._initialized = True

    @staticmethod
    def _dependency_ids(manifest: CatalogExtensionManifest) -> list[str]:
        dependencies = manifest.dependencies
        raw = [
            *list(getattr(dependencies, "plugins", []) or []),
            *list(getattr(dependencies, "extensions", []) or []),
        ]
        normalized: list[str] = []
        for value in raw:
            dependency_id = str(value).split("@", 1)[0].strip()
            if dependency_id and dependency_id not in normalized:
                normalized.append(dependency_id)
        return normalized

    @classmethod
    def _dependency_errors(
        cls,
        manifests: Dict[str, CatalogExtensionManifest],
    ) -> Dict[str, list[str]]:
        graph = {
            plugin_id: cls._dependency_ids(manifest)
            for plugin_id, manifest in manifests.items()
        }
        errors: Dict[str, list[str]] = {}
        available = set(manifests)

        for plugin_id, dependencies in graph.items():
            missing = sorted(dep for dep in dependencies if dep not in available)
            if missing:
                errors.setdefault(plugin_id, []).append(
                    "Missing extension dependencies: " + ", ".join(missing)
                )

        visiting: list[str] = []
        visited: set[str] = set()

        def visit(plugin_id: str) -> None:
            if plugin_id in visited:
                return
            if plugin_id in visiting:
                cycle_start = visiting.index(plugin_id)
                cycle = visiting[cycle_start:] + [plugin_id]
                message = "Circular extension dependency: " + " -> ".join(cycle)
                for member in set(cycle):
                    errors.setdefault(member, []).append(message)
                return
            visiting.append(plugin_id)
            for dependency_id in graph.get(plugin_id, []):
                if dependency_id in graph:
                    visit(dependency_id)
            visiting.pop()
            visited.add(plugin_id)

        for plugin_id in graph:
            visit(plugin_id)
        return errors

    async def refresh_with_new_plugin_disabled(self, plugin_id: str) -> int:
        """Refresh after explicit upload without auto-enabling the new package."""
        async with self._state_lock:
            self._disabled.add(plugin_id)
            return await self._refresh_unlocked()

    async def refresh(self) -> int:
        """Refresh catalog and runtime eligibility under one lifecycle lock."""
        async with self._state_lock:
            return await self._refresh_unlocked()

    async def _refresh_unlocked(self) -> int:
        """Rebuild a complete execution projection without publishing partial state."""
        # Only an explicit user disable is persisted through the marker.
        # Default-disabled, channel-gated and dependency-blocked states are
        # derived, never promoted into permanent manual disablement.
        # Never retire an instance or rebuild registry while any execution is
        # in flight. The same state lock fences the execution admission.
        if self._active:
            raise RuntimeError("Cannot refresh plugins with active executions")
        previous_hashes = {
            plugin_id: (
                metadata.file_hash if metadata is not None else None
            )
            for plugin_id in self.catalog_registry.list_discovered()
            for metadata in [self.catalog_registry.get_metadata(plugin_id)]
        }
        await self.catalog_registry.refresh()
        # Uninstalled IDs must not retain in-memory lifecycle state. An
        # installed plugin's persisted disabled marker is read below.
        self._disabled.intersection_update(self.catalog_registry.list_discovered())

        runtime_registry = ExtensionRegistry()
        lifecycle = ExtensionLifecycleManager(runtime_registry)
        executor = ExtensionExecutionService(
            registry=runtime_registry,
            lifecycle=lifecycle,
            audit_sink=self._audit_sink,
        )
        catalog_manifests: Dict[str, CatalogExtensionManifest] = {}

        for plugin_id in self.catalog_registry.list_discovered():
            if (self.extensions_root / plugin_id / ".karen-manual-disabled").is_file():
                self._disabled.add(plugin_id)
            metadata = self.catalog_registry.get_metadata(plugin_id)
            if metadata is None:
                continue
            try:
                raw = json.loads(
                    Path(metadata.manifest_path).read_text(encoding="utf-8")
                )
                catalog_manifests[plugin_id] = CatalogExtensionManifest.from_dict(raw)
            except Exception as exc:
                metadata.is_valid = False
                metadata.validation_errors.append(
                    f"Manifest normalization failed: {type(exc).__name__}"
                )
                logger.error("Failed to normalize manifest for %s: %s", plugin_id, exc)

        valid_manifests = {
            plugin_id: manifest
            for plugin_id, manifest in catalog_manifests.items()
            if (
                self.catalog_registry.get_metadata(plugin_id) is not None
                and bool(self.catalog_registry.get_metadata(plugin_id).is_valid)
            )
        }
        dependency_errors = self._dependency_errors(valid_manifests)
        for plugin_id, plugin_errors in dependency_errors.items():
            metadata = self.catalog_registry.get_metadata(plugin_id)
            if metadata is None:
                continue
            metadata.is_valid = False
            for error in plugin_errors:
                if error not in metadata.validation_errors:
                    metadata.validation_errors.append(error)

        # Dependency declarations are required runtime prerequisites, not
        # merely installation-time hints. Compute the fixed point of plugins
        # that may be enabled. A disabled or invalid dependency disables all
        # of its transitive dependents; never activate it as a side effect.
        enabled = {
            plugin_id
            for plugin_id, manifest in catalog_manifests.items()
            if (
                (metadata := self.catalog_registry.get_metadata(plugin_id)) is not None
                and metadata.is_valid
                and plugin_id not in self._disabled
                and plugin_id not in self._retirement_pending
                and manifest.capabilities.communication_channel is None
                and manifest.rbac.default_enabled
            )
        }
        while True:
            blocked = {
                plugin_id
                for plugin_id in enabled
                if any(
                    dependency not in enabled
                    for dependency in self._dependency_ids(catalog_manifests[plugin_id])
                )
            }
            if not blocked:
                break
            enabled.difference_update(blocked)

        for plugin_id, catalog_manifest in catalog_manifests.items():
            metadata = self.catalog_registry.get_metadata(plugin_id)
            if metadata is None or not metadata.is_valid:
                continue

            registration = ExtensionRegistration(
                manifest=self._project_runtime_manifest(catalog_manifest),
                state=ExtensionLifecycleState.DISCOVERED,
                checksum=metadata.file_hash,
                instance=_LazyRuntimeInstanceAdapter(self.loader, plugin_id),
            )
            await runtime_registry.register(registration)
            # Channel transports must remain inactive until the governed
            # Gateway supplies admission, identity binding and delivery fencing.
            target = (
                ExtensionLifecycleState.ENABLED
                if plugin_id in enabled
                else ExtensionLifecycleState.DISABLED
            )
            await runtime_registry.update_state(plugin_id, target)

        # A successful catalog projection may replace a Python package in
        # place, or remove it entirely. Retire only invalidated loaded
        # instances; unchanged loaded plugins retain their resources.
        for plugin_id, instance in self.loader.get_loaded_extensions().items():
            metadata = self.catalog_registry.get_metadata(plugin_id)
            if (
                metadata is None
                or not metadata.is_valid
                or not metadata.file_hash
                or previous_hashes.get(plugin_id) != metadata.file_hash
                or plugin_id in self._retirement_pending
            ):
                await self._retire_loaded_plugin(plugin_id, instance)

        self.runtime_registry = runtime_registry
        self.lifecycle = lifecycle
        self.executor = executor
        self._catalog_manifests = catalog_manifests
        self._initialized = True
        return len(self.catalog_registry.list_discovered())

    @staticmethod
    def _declared_permissions(manifest: CatalogExtensionManifest) -> list[str]:
        permissions = manifest.permissions
        declared: list[str] = []

        def add(permission_id: str) -> None:
            normalized = str(permission_id).strip()
            if normalized and normalized not in declared:
                declared.append(normalized)

        boolean_permissions = {
            "memory_read": "memory_read",
            "memory_write": "memory_write",
            "user_data_read": "user_data_read",
            "user_data_write": "user_data_write",
            "system_config_read": "system_config_read",
            "system_config_write": "system_config_write",
        }
        for attribute, permission_id in boolean_permissions.items():
            if bool(getattr(permissions, attribute, False)):
                add(permission_id)

        if list(getattr(permissions, "tools", []) or []):
            add("tool_access")
            for tool_id in getattr(permissions, "tools", []) or []:
                add(f"tool_access:{tool_id}")

        for category in (
            "data_access",
            "plugin_access",
            "system_access",
            "network_access",
        ):
            values = list(getattr(permissions, category, []) or [])
            if not values:
                continue
            add(category)
            for value in values:
                add(f"{category}:{value}")

        return declared

    def _project_runtime_manifest(
        self, manifest: CatalogExtensionManifest
    ) -> RuntimeExtensionManifest:
        schema: Dict[str, Any] = {}
        if manifest.config_schema is not None:
            schema = manifest.config_schema.model_dump()
            if "additional_properties" in schema:
                schema["additionalProperties"] = schema.pop("additional_properties")

        roles = [
            getattr(role, "value", str(role))
            for role in (manifest.rbac.allowed_roles or [])
        ]
        required_permissions = self._declared_permissions(manifest)
        channel = manifest.capabilities.communication_channel
        if channel is None:
            capabilities = [
                ExtensionCapability(
                    id=self.EXECUTE_CAPABILITY,
                    input_schema=schema,
                    required_permissions=required_permissions,
                    required_roles=roles,
                    risk_class=RiskClass.LOW,
                    data_classification=DataClassification.PUBLIC,
                    provides_ui=manifest.capabilities.provides_ui,
                    provides_api=manifest.capabilities.provides_api,
                    provides_background_tasks=manifest.capabilities.provides_background_tasks,
                    provides_webhooks=manifest.capabilities.provides_webhooks,
                    prompt_contract_id=manifest.prompt_files.contract_id,
                )
            ]
        else:
            # Host-discovered transport contract, never generic plugin execute.
            # This remains disabled until a separate governed Gateway exists.
            capabilities = [
                ExtensionCapability(
                    id="communication_channel",
                    version=channel.version,
                    required_permissions=required_permissions,
                    required_roles=roles,
                    risk_class=RiskClass.HIGH,
                    data_classification=DataClassification.CONFIDENTIAL,
                    side_effect_level=SideEffectLevel.EXTERNAL,
                    result_trust=ResultTrust.UNTRUSTED_EXTERNAL,
                    requires_network=bool(manifest.permissions.network_access),
                    requires_credentials=True,
                    supports_streaming=channel.supports_streaming,
                    provides_webhooks="webhook" in channel.ingress,
                )
            ]

        metadata = {
            "display_name": manifest.display_name,
            "author": manifest.author,
            "license": manifest.license,
            "category": manifest.category,
            "tags": list(manifest.tags),
            "catalog_api_version": manifest.api_version,
        }
        if channel is not None:
            metadata["communication_channel"] = channel.model_dump()
        trust_tier = (
            TrustTier.FIRST_PARTY if self._is_builtin_root() else TrustTier.UNTRUSTED
        )
        return RuntimeExtensionManifest(
            id=manifest.name,
            name=manifest.name,
            version=manifest.version,
            plugin_api_version=manifest.api_version,
            description=manifest.description,
            entrypoint=manifest.entrypoint or "handler:MainExtension",
            capabilities=capabilities,
            required_permissions=required_permissions,
            required_roles=roles,
            tenant_scope=TenantScope.SINGLE,
            input_schema=schema,
            prompt_contract_id=manifest.prompt_files.contract_id,
            enabled_by_default=manifest.rbac.default_enabled and channel is None,
            trusted_ui=False,
            trust_tier=trust_tier,
            metadata=metadata,
            risk_class=RiskClass.HIGH if channel is not None else RiskClass.LOW,
            data_classification=(
                DataClassification.CONFIDENTIAL if channel is not None
                else DataClassification.PUBLIC
            ),
            side_effect_level=(
                SideEffectLevel.EXTERNAL if channel is not None
                else SideEffectLevel.NONE
            ),
            requires_network=(
                bool(manifest.permissions.network_access) if channel is not None
                else False
            ),
            requires_credentials=channel is not None,
        )

    def get_catalog_manifest(self, plugin_id: str) -> Optional[CatalogExtensionManifest]:
        return self._catalog_manifests.get(plugin_id)

    def get_channel_activation_manifest(
        self, plugin_id: str,
    ) -> Optional[CatalogExtensionManifest]:
        """Read canonical installed channel truth without enabling plugin execution.

        Communication capabilities deliberately remain DISABLED to the generic
        ExtensionExecutionService. Channel Gateway authorizes each tenant-owned
        connection separately. A manually disabled or invalid installation
        overrides any connection-enabled state.
        """
        record = self.get_record(plugin_id)
        registration = self.runtime_registry.get(plugin_id)
        manifest = self.get_catalog_manifest(plugin_id)
        if (
            record is None
            or record["is_valid"] is not True
            or registration is None
            or registration.state is not ExtensionLifecycleState.DISABLED
            or manifest is None
            or manifest.capabilities.communication_channel is None
        ):
            return None
        marker = self.extensions_root / plugin_id / ".karen-manual-disabled"
        if marker.is_symlink() or marker.exists():
            return None
        return manifest

    def is_canonical_channel_adapter(self, plugin_id: str, adapter: Any) -> bool:
        """Require installed, host-loaded channel code, never a caller stub.

        Generic extension registrations stay disabled for execution. This
        strictly checks object identity against the canonical loader's
        process-local installed extension instance, after catalog gating.
        """
        if self.get_channel_activation_manifest(plugin_id) is None:
            return False
        try:
            return self.loader.load_extension(plugin_id) is adapter
        except Exception as exc:
            logger.warning(
                "channel.adapter_resolution_failed",
                extra={"installation_id": plugin_id, "error_type": type(exc).__name__},
            )
            return False

    def get_required_permissions(self, plugin_id: str) -> list[str]:
        registration = self.runtime_registry.get(plugin_id)
        if registration is None:
            return []
        return list(registration.manifest.required_permissions)

    def get_record(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        metadata = self.catalog_registry.get_metadata(plugin_id)
        manifest = self._catalog_manifests.get(plugin_id)
        if metadata is None or manifest is None:
            return None
        registration = self.runtime_registry.get(plugin_id)
        status = (
            registration.state.value
            if registration is not None
            else "error" if not metadata.is_valid else "discovered"
        )
        error_message = (
            "; ".join(metadata.validation_errors)
            if metadata.validation_errors
            else None
        )
        return PluginCatalogRecord(
            manifest=manifest,
            path=metadata.directory,
            status=status,
            checksum=metadata.file_hash,
            error_message=error_message,
            is_valid=bool(metadata.is_valid),
        ).as_dict()

    def list_records(self) -> list[Dict[str, Any]]:
        records: list[Dict[str, Any]] = []
        for plugin_id in self.catalog_registry.list_discovered():
            record = self.get_record(plugin_id)
            if record is not None:
                records.append(record)
        return records

    async def _retire_loaded_plugin(self, plugin_id: str, instance: Any) -> None:
        """Shutdown a loaded plugin before evicting its Python module cache.

        If cleanup fails, revoke the previous registry's permission to run
        the stale instance and retain its cache for explicit recovery.
        """
        shutdown = getattr(instance, "_shutdown", None)
        is_shutdown = getattr(instance, "is_shutdown", None)
        if callable(shutdown) and not (
            callable(is_shutdown) and is_shutdown()
        ):
            try:
                await shutdown()
            except BaseException as exc:
                self._retirement_pending.add(plugin_id)
                previous = self.runtime_registry.get(plugin_id)
                if previous is not None:
                    await self.runtime_registry.update_state(
                        plugin_id, ExtensionLifecycleState.DISABLED
                    )
                logger.error(
                    "plugin.kernel.retirement_failed",
                    extra={"plugin_id": plugin_id,
                           "error_type": type(exc).__name__},
                )
                raise
        self.loader.forget_loaded_extension(plugin_id)
        self._retirement_pending.discard(plugin_id)

    def _required_by_enabled_plugin(self, dependency_id: str) -> bool:
        """Check direct and transitive registered requirements, without imports."""
        for plugin_id, manifest in self._catalog_manifests.items():
            registration = self.runtime_registry.get(plugin_id)
            if (
                plugin_id == dependency_id
                or registration is None
                or registration.state is not ExtensionLifecycleState.ENABLED
            ):
                continue
            remaining = list(self._dependency_ids(manifest))
            visited: set[str] = set()
            while remaining:
                required = remaining.pop()
                if required == dependency_id:
                    return True
                if required not in visited:
                    visited.add(required)
                    found = self._catalog_manifests.get(required)
                    if found is not None:
                        remaining.extend(self._dependency_ids(found))
        return False

    async def enable(self, plugin_id: str) -> bool:
        async with self._state_lock:
            return await self._enable_unlocked(plugin_id)

    async def _enable_unlocked(self, plugin_id: str) -> bool:
        if plugin_id in self._retirement_pending:
            raise RuntimeError("Plugin retirement incomplete; cannot enable")
        registration = self.runtime_registry.get(plugin_id)
        if registration is None:
            return False
        manifest = self._catalog_manifests.get(plugin_id)
        if manifest is not None:
            missing = [
                dependency
                for dependency in self._dependency_ids(manifest)
                if (
                    (required := self.runtime_registry.get(dependency)) is None
                    or required.state is not ExtensionLifecycleState.ENABLED
                )
            ]
            if missing:
                raise ValueError(
                    "Required plugin dependencies must be enabled first: "
                    + ", ".join(sorted(missing))
                )
        if any(
            capability.id == "communication_channel"
            for capability in getattr(registration.manifest, "capabilities", ())
        ):
            raise ValueError(
                "Communication channel activation requires the governed Channel Gateway"
            )
        marker = self.extensions_root / plugin_id / ".karen-manual-disabled"
        # A successful explicit enable must be durable across restart.
        if marker.is_symlink():
            raise ValueError("Unsafe plugin activation marker")
        await self.runtime_registry.update_state(plugin_id, ExtensionLifecycleState.ENABLED)
        # Record the durable state only after the canonical registry accepts
        # activation. A failed state transition must preserve the marker.
        if marker.is_file():
            try:
                marker.unlink()
            except OSError:
                await self.runtime_registry.update_state(plugin_id, ExtensionLifecycleState.DISABLED)
                self._disabled.add(plugin_id)
                raise
        self._disabled.discard(plugin_id)
        return True

    async def disable(self, plugin_id: str) -> bool:
        async with self._state_lock:
            return await self._disable_unlocked(plugin_id)

    async def _disable_unlocked(self, plugin_id: str) -> bool:
        registration = self.runtime_registry.get(plugin_id)
        if registration is None:
            return False
        # A running handler cannot be shut down from under its execution.
        # Explicit disable remains a separate governed operation.
        if plugin_id in self._active.values():
            raise RuntimeError("Cannot disable a plugin with active executions")
        # Refuse to break any already-enabled dependent rather than silently
        # leaving it executable against a disabled transitive prerequisite.
        # The refusal happens before touching the durable disabled marker.
        if self._required_by_enabled_plugin(plugin_id):
            raise ValueError("Plugin is required by an enabled dependent")
        marker = self.extensions_root / plugin_id / ".karen-manual-disabled"
        if marker.is_symlink() or not marker.parent.is_dir() or marker.parent.is_symlink():
            raise ValueError("Unsafe plugin disabled-state path")
        # Persist explicit disable before transitioning runtime state.
        # If transition fails, retaining the marker is fail-closed.
        if not marker.exists():
            with marker.open("x", encoding="utf-8") as handle:
                handle.write("Plugin disabled explicitly; requires enable\n")
        self._disabled.add(plugin_id)
        await self.runtime_registry.update_state(plugin_id, ExtensionLifecycleState.DISABLED)
        # Disabling revokes execution and releases existing plugin resources;
        # enabling later must initialize a fresh instance.
        instance = self.loader.get_loaded_extensions().get(plugin_id)
        if instance is not None:
            await self._retire_loaded_plugin(plugin_id, instance)
        return True

    async def execute(
        self,
        request: ExtensionExecutionRequest,
    ) -> ExtensionExecutionResult:
        # Serialize the admission marker with refresh/disable, not the model
        # or plugin execution itself. Unrelated plugins may execute in parallel.
        async with self._state_lock:
            if request.context.request_id in self._active:
                raise RuntimeError("Plugin execution request ID already active")
            self._active[request.context.request_id] = request.plugin_id
            executor = self.executor
        try:
            return await executor.execute(request)
        finally:
            self._active.pop(request.context.request_id, None)

    def active_executions(self) -> Dict[str, str]:
        return dict(self._active)

    async def cleanup(self) -> None:
        async with self._state_lock:
            if self._active:
                raise RuntimeError("Cannot shut down plugins with active executions")
            failed = False
            for plugin_id, instance in self.loader.get_loaded_extensions().items():
                try:
                    await self._retire_loaded_plugin(plugin_id, instance)
                except Exception:
                    failed = True
                    logger.error(
                        "plugin.kernel.cleanup_incomplete",
                        extra={"plugin_id": plugin_id},
                    )
            self._initialized = False
            if failed:
                raise RuntimeError("Plugin cleanup incomplete")

    def registry_stats(self) -> Dict[str, Any]:
        records = self.list_records()
        by_status: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        for record in records:
            status = str(record.get("status", "unknown"))
            by_status[status] = by_status.get(status, 0) + 1
            manifest = record.get("manifest")
            category = str(getattr(manifest, "category", "general") or "general")
            by_category[category] = by_category.get(category, 0) + 1
        return {
            "total_plugins": len(records),
            "by_status": by_status,
            "by_category": by_category,
            "by_type": dict(by_category),
        }


__all__ = ["PluginKernel", "PluginCatalogRecord", "RuntimeExtensionManifest"]

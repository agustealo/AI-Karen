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
_CANONICAL_PLUGIN_ROOT = Path("src/ai_karen_engine/extensions/plugins")


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
        self._active: Dict[str, str] = {}
        self._initialized = False

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

    async def refresh(self) -> int:
        """Refresh catalog truth and atomically rebuild the execution projection."""
        self._disabled.update(
            registration.manifest.id
            for registration in self.runtime_registry.list_registered()
            if registration.state is ExtensionLifecycleState.DISABLED
        )
        await self.catalog_registry.refresh()

        runtime_registry = ExtensionRegistry()
        lifecycle = ExtensionLifecycleManager(runtime_registry)
        executor = ExtensionExecutionService(
            registry=runtime_registry,
            lifecycle=lifecycle,
            audit_sink=self._audit_sink,
        )
        catalog_manifests: Dict[str, CatalogExtensionManifest] = {}

        for plugin_id in self.catalog_registry.list_discovered():
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
            target = (
                ExtensionLifecycleState.DISABLED
                if plugin_id in self._disabled
                or not catalog_manifest.rbac.default_enabled
                else ExtensionLifecycleState.ENABLED
            )
            await runtime_registry.update_state(plugin_id, target)

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
        capability = ExtensionCapability(
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
        metadata = {
            "display_name": manifest.display_name,
            "author": manifest.author,
            "license": manifest.license,
            "category": manifest.category,
            "tags": list(manifest.tags),
            "catalog_api_version": manifest.api_version,
        }
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
            capabilities=[capability],
            required_permissions=required_permissions,
            required_roles=roles,
            tenant_scope=TenantScope.SINGLE,
            input_schema=schema,
            prompt_contract_id=manifest.prompt_files.contract_id,
            enabled_by_default=manifest.rbac.default_enabled,
            trusted_ui=False,
            trust_tier=trust_tier,
            metadata=metadata,
            risk_class=RiskClass.LOW,
            data_classification=DataClassification.PUBLIC,
        )

    def get_catalog_manifest(self, plugin_id: str) -> Optional[CatalogExtensionManifest]:
        return self._catalog_manifests.get(plugin_id)

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

    async def enable(self, plugin_id: str) -> bool:
        registration = self.runtime_registry.get(plugin_id)
        if registration is None:
            return False
        self._disabled.discard(plugin_id)
        await self.runtime_registry.update_state(plugin_id, ExtensionLifecycleState.ENABLED)
        return True

    async def disable(self, plugin_id: str) -> bool:
        registration = self.runtime_registry.get(plugin_id)
        if registration is None:
            return False
        self._disabled.add(plugin_id)
        await self.runtime_registry.update_state(plugin_id, ExtensionLifecycleState.DISABLED)
        return True

    async def execute(
        self,
        request: ExtensionExecutionRequest,
    ) -> ExtensionExecutionResult:
        self._active[request.context.request_id] = request.plugin_id
        try:
            return await self.executor.execute(request)
        finally:
            self._active.pop(request.context.request_id, None)

    def active_executions(self) -> Dict[str, str]:
        return dict(self._active)

    async def cleanup(self) -> None:
        for instance in self.loader.get_loaded_extensions().values():
            shutdown = getattr(instance, "_shutdown", None)
            is_shutdown = getattr(instance, "is_shutdown", None)
            already_shutdown = bool(is_shutdown()) if callable(is_shutdown) else False
            if callable(shutdown) and not already_shutdown:
                try:
                    await shutdown()
                except Exception:
                    logger.exception("Plugin shutdown failed")
        self._active.clear()
        self._initialized = False

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

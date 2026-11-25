"""Application facade for the canonical plugin kernel.

PluginService preserves the HTTP/application contract while delegating catalog
truth to the extension platform registry and execution to
ExtensionExecutionService through PluginKernel.  It is not an execution or
discovery authority.
"""

from __future__ import annotations

import asyncio
import logging
import math
import io
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
import uuid
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ai_karen_engine.core.runtime.contracts import (
    ActionExecutionGate,
    AuthorizedExecutionPlan,
)
from ai_karen_engine.core.runtime.policy import PolicyEvaluationRequest, RuntimePolicyEnforcer
from ai_karen_engine.extensions.contracts import (
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionExecutionResult,
)
from ai_karen_engine.extensions.content_intelligence_sources import MAX_CONTENT_SOURCE_REFERENCES
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.services.identity_vault.credential_vault_service import (
    get_credential_vault_service,
)
from ai_karen_engine.services.plugin_settings_repository import (
    PluginSettingsContract,
    PluginSettingsNotConfigured,
    PluginSettingsValidationError,
    PluginSettingsRepository,
)

if TYPE_CHECKING:
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
        PluginLifecycleApprovalScope,
    )

logger = logging.getLogger(__name__)
_ENABLED_STATES = {"registered", "enabled", "loaded", "active"}
_CANONICAL_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "extensions" / "plugins"


class ExecutionMode(str, Enum):
    """Compatibility hint retained at the application boundary.

    Isolation is governed by the runtime manifest and canonical executor; this
    value no longer selects a second execution engine.
    """

    DIRECT = "direct"
    THREAD = "thread"
    PROCESS = "process"
    SANDBOX = "sandbox"


class ExecutionStatus(str, Enum):
    """Stable application-facing execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class PluginExecutionResult:
    """HTTP/application view of a canonical ExtensionExecutionResult."""

    request_id: str
    plugin_name: str
    status: ExecutionStatus
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    plugin_id: str = ""
    plugin_version: str = ""
    user_id: str = ""
    tenant_id: str = ""
    session_id: str = ""
    conversation_id: str = ""
    correlation_id: str = ""
    policy_decision_id: str = ""
    requested_capabilities: List[str] = field(default_factory=list)
    granted_capabilities: List[str] = field(default_factory=list)
    error_code: Optional[str] = None


class PluginService:
    """Thin application facade over the canonical plugin kernel."""

    def __init__(
        self,
        marketplace_path: Optional[Path] = None,
        core_plugins_path: Optional[Path] = None,
    ) -> None:
        self.marketplace_path = marketplace_path
        self.core_plugins_path = core_plugins_path
        self.kernel: Optional[PluginKernel] = None
        self.initialized = False
        self._policy_enforcer = RuntimePolicyEnforcer()
        self._history: List[PluginExecutionResult] = []
        self._settings_repository = PluginSettingsRepository()

    def _resolve_root(self) -> Path:
        marketplace = Path(self.marketplace_path) if self.marketplace_path else None
        core = Path(self.core_plugins_path) if self.core_plugins_path else None
        if marketplace is not None and core is not None:
            if marketplace.resolve() != core.resolve():
                raise ValueError(
                    "PluginService requires one canonical plugin root; "
                    "marketplace_path and core_plugins_path must resolve to the same path"
                )
        return core or marketplace or _CANONICAL_PLUGIN_ROOT

    async def initialize(self, auto_discover: bool = True) -> None:
        if self.initialized and self.kernel is not None:
            return
        root = self._resolve_root()
        self.kernel = PluginKernel(root)
        await self.kernel.initialize(auto_discover=auto_discover)
        self.initialized = True

    async def _ensure_initialized(self) -> None:
        if not self.initialized or self.kernel is None:
            await self.initialize()

    def _get_kernel(self) -> PluginKernel:
        if self.kernel is None:
            raise RuntimeError("Plugin kernel is not initialized")
        return self.kernel

    async def _prepare_file_explorer(
        self, *, user_id: str, tenant_id: str, roles: List[str],
        permissions: List[str], request_id: str, correlation_id: str,
        mutation: Optional[str] = None, resource_scope: Optional[Dict[str, Any]] = None,
    ):
        """Shared fresh policy admission for the trusted Explorer host."""
        from ai_karen_engine.auth.rbac_middleware import (
            FILE_EXPLORER_MUTATION_PERMISSIONS, Permission,
        )

        required_permissions = [Permission.DATA_READ.value]
        if mutation is not None:
            entitlement = FILE_EXPLORER_MUTATION_PERMISSIONS.get(mutation)
            if entitlement is None:
                raise ValueError("file_explorer_operation_invalid")
            required_permissions.append(entitlement.value)
        capabilities = ["file-explorer", *required_permissions]
        if mutation:
            capabilities.append(mutation)
        from ai_karen_engine.database.factory import get_database_client
        from ai_karen_engine.extensions.owner_inventory import ArtifactSourceAdapter
        from ai_karen_engine.extensions.file_explorer_inventory import (
            FileExplorerInventoryHost,
        )
        from ai_karen_engine.services.database.repositories.repository_factory import (
            RepositoryFactory,
        )

        if (
            not user_id or not tenant_id
            or not set(required_permissions).issubset(permissions)
            or not request_id or not correlation_id
        ):
            raise PermissionError("file_explorer_read_permission_required")
        await self._ensure_initialized()
        kernel = self._get_kernel()
        record = kernel.get_record("file-explorer")
        if (
            record is None
            or record.get("status") != "enabled"
            or record.get("dependencies_resolved") is not True
        ):
            raise PermissionError("file_explorer_disabled")

        decision = await self._policy_enforcer.evaluate(
            PolicyEvaluationRequest(
                user_id=user_id,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                roles=list(roles),
                permissions=list(permissions),
                action="plugin_execution",
                plugin_id="file-explorer",
                requested_capabilities=capabilities,
                resource_scope=resource_scope or {},
            )
        )
        if not decision.allowed or decision.requires_human_gate:
            raise PermissionError("file_explorer_policy_denied")
        plan = decision.to_authorized_plan()
        if (
            "file-explorer" not in plan.allowed_plugins
            or "file-explorer" not in plan.allowed_capabilities
            or not set(capabilities).issubset(plan.allowed_capabilities)
            or plan.approval_requirements
            or (resource_scope is not None and plan.resource_scope != resource_scope)
            or not plan.matches_execution_scope(
                user_id=user_id,
                tenant_id=tenant_id,
                policy_decision_id=decision.decision_id,
            )
        ):
            raise PermissionError("file_explorer_policy_scope_denied")

        from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

        database = get_database_client()
        if database is None or not callable(getattr(database, "get_async_session", None)):
            raise RuntimeError("file_explorer_database_unavailable")
        repository = RepositoryFactory(
            session_factory=database.get_async_session,
            hierarchy_transaction=async_transaction_scope,
        ).create_artifact_store()

        # Shared metadata adapter; the File Explorer host still owns admission.
        source = ArtifactSourceAdapter(repository)
        context = ExtensionExecutionContext(
            request_id=request_id,
            correlation_id=correlation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            policy_decision_id=decision.decision_id,
            allowed_capabilities=list(plan.allowed_capabilities),
            resource_scope={},
            audit_context={
                "origin": "authenticated_file_explorer",
                "user_roles": list(roles),
                "permissions": list(permissions),
            },
        )
        return FileExplorerInventoryHost(kernel=kernel, source=source), context, plan

    async def get_file_explorer_capabilities(
        self, *, user_id: str, tenant_id: str, roles: List[str],
        permissions: List[str], request_id: str, correlation_id: str,
    ) -> Dict[str, Any]:
        """Report preflight eligibility, never a reusable authorization grant."""
        from ai_karen_engine.auth.rbac_middleware import FILE_EXPLORER_MUTATION_PERMISSIONS

        host, context, plan = await self._prepare_file_explorer(
            user_id=user_id, tenant_id=tenant_id, roles=roles,
            permissions=permissions, request_id=request_id, correlation_id=correlation_id,
        )
        browse = await host.probe_owner_capability(context=context, plan=plan)
        operations = {}
        for operation, permission in FILE_EXPLORER_MUTATION_PERMISSIONS.items():
            if permission.value not in permissions:
                operations[operation] = "denied"
            elif not browse:
                operations[operation] = "unavailable"
            else:
                try:
                    mutation_host, mutation_context, mutation_plan = await self._prepare_file_explorer(
                        user_id=user_id, tenant_id=tenant_id, roles=roles,
                        permissions=permissions, request_id=request_id,
                        correlation_id=correlation_id, mutation=operation,
                        resource_scope={"operation": operation, "availability_only": True},
                    )
                    admitted = await mutation_host.probe_owner_capability(
                        context=mutation_context, plan=mutation_plan, operation=operation,
                    )
                    operations[operation] = "available" if admitted else "unavailable"
                except PermissionError:
                    operations[operation] = "denied"
                except Exception:
                    logger.warning("file_explorer_capability_probe_failed", extra={
                        "request_id": request_id, "correlation_id": correlation_id,
                        "tenant_id": tenant_id, "user_id": user_id, "operation": operation,
                    })
                    operations[operation] = "unavailable"
        return {
            "browse": "available" if browse else "unavailable",
            "operations": operations,
            "semantics": "preflight_not_resource_authorization",
            "request_id": request_id, "correlation_id": correlation_id,
        }

    async def create_file_explorer_folder(
        self, *, user_id: str, tenant_id: str, roles: List[str],
        permissions: List[str], request_id: str, correlation_id: str,
        name: str, parent_folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Explicit user-initiated host mutation; plugin remains read-only."""
        host, context, plan = await self._prepare_file_explorer(
            user_id=user_id, tenant_id=tenant_id, roles=roles, permissions=permissions,
            request_id=request_id, correlation_id=correlation_id, mutation="file_explorer.folder.create",
            resource_scope={"operation": "file_explorer.folder.create",
                            "name": name, "parent_folder_id": parent_folder_id},
        )
        return await host.create_owner_folder(
            context=context, plan=plan, name=name, parent_folder_id=parent_folder_id,
        )

    async def rename_file_explorer_folder(
        self, *, user_id: str, tenant_id: str, roles: List[str],
        permissions: List[str], request_id: str, correlation_id: str,
        folder_id: str, name: str, expected_revision: int,
    ) -> Dict[str, Any]:
        host, context, plan = await self._prepare_file_explorer(
            user_id=user_id, tenant_id=tenant_id, roles=roles, permissions=permissions,
            request_id=request_id, correlation_id=correlation_id,
            mutation="file_explorer.folder.rename",
            resource_scope={"operation": "file_explorer.folder.rename",
                            "folder_id": folder_id, "name": name,
                            "expected_revision": expected_revision},
        )
        return await host.rename_owner_folder(
            context=context, plan=plan, folder_id=folder_id,
            name=name, expected_revision=expected_revision,
        )

    async def move_file_explorer_item(
        self, *, user_id: str, tenant_id: str, roles: List[str],
        permissions: List[str], request_id: str, correlation_id: str,
        kind: str, source_id: str, destination_id: Optional[str],
        expected_revision: int,
    ) -> Dict[str, Any]:
        if kind not in ("folder", "artifact"):
            raise ValueError("file_explorer_move_kind_invalid")
        operation = f"file_explorer.{kind}.move"
        host, context, plan = await self._prepare_file_explorer(
            user_id=user_id, tenant_id=tenant_id, roles=roles, permissions=permissions,
            request_id=request_id, correlation_id=correlation_id,
            mutation=operation,
            resource_scope={"operation": operation, "source_id": source_id,
                            "destination_id": destination_id,
                            "expected_revision": expected_revision},
        )
        return await host.move_owner_item(
            context=context, plan=plan, kind=kind, source_id=source_id,
            destination_id=destination_id, expected_revision=expected_revision,
        )

    async def delete_file_explorer_folder(
        self, *, user_id: str, tenant_id: str, roles: List[str],
        permissions: List[str], request_id: str, correlation_id: str,
        folder_id: str, expected_revision: int,
    ) -> Dict[str, Any]:
        host, context, plan = await self._prepare_file_explorer(
            user_id=user_id, tenant_id=tenant_id, roles=roles, permissions=permissions,
            request_id=request_id, correlation_id=correlation_id,
            mutation="file_explorer.folder.delete",
            resource_scope={"operation": "file_explorer.folder.delete",
                            "folder_id": folder_id, "expected_revision": expected_revision},
        )
        return await host.delete_empty_owner_folder(
            context=context, plan=plan, folder_id=folder_id,
            expected_revision=expected_revision,
        )

    async def list_file_explorer_owner_page(
        self,
        *,
        user_id: str,
        tenant_id: str,
        roles: List[str],
        permissions: List[str],
        request_id: str,
        correlation_id: str,
        limit: int = 100,
        cursor: Optional[str] = None,
        hierarchy: bool = False,
        parent_folder_id: Optional[str] = None,
        after_folder_id: Optional[str] = None,
        file_cursor: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Authorize a fresh read through RuntimePolicy and the canonical kernel.

        This is the only application entrypoint for the File Explorer owner
        inventory. Authentication/RBAC belongs to ingress; this boundary also
        rejects missing data-read entitlement rather than accepting a plugin
        identifier as a grant.
        """
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("file_explorer_page_limit_invalid")
        if cursor is not None and (
            not isinstance(cursor, str) or not 1 <= len(cursor) <= 768
        ):
            raise ValueError("file_explorer_cursor_invalid")

        host, context, plan = await self._prepare_file_explorer(
            user_id=user_id, tenant_id=tenant_id, roles=roles, permissions=permissions,
            request_id=request_id, correlation_id=correlation_id,
        )
        if hierarchy:
            return await host.list_owner_hierarchy(
                context=context, plan=plan, limit=limit,
                parent_folder_id=parent_folder_id, after_folder_id=after_folder_id,
                file_cursor=file_cursor,
                **({"search": search} if search is not None else {}),
            )
        return await host.list_owner_page(
            context=context,
            plan=plan,
            limit=limit,
            cursor=cursor,
            **({"search": search} if search is not None else {}),
        )

    async def _authorize_content_owner_access(
        self, *, user_id: str, tenant_id: str, roles: List[str],
        permissions: List[str], request_id: str, correlation_id: str,
    ):
        """Issue a fresh scoped policy plan for either metadata or text access."""
        if (
            not user_id or not tenant_id or not request_id or not correlation_id
            or "data:read" not in permissions
        ):
            raise PermissionError("content_source_read_permission_required")
        await self._ensure_initialized()
        kernel = self._get_kernel()
        record = kernel.get_record("content-intelligence")
        if (
            not isinstance(record, dict)
            or record.get("status") != "enabled"
            or record.get("dependencies_resolved") is not True
        ):
            raise PermissionError("content_source_plugin_disabled")
        decision = await self._policy_enforcer.evaluate(
            PolicyEvaluationRequest(
                user_id=user_id,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                roles=list(roles),
                permissions=list(permissions),
                action="plugin_execution",
                plugin_id="content-intelligence",
                requested_capabilities=["content-intelligence", "data:read"],
            )
        )
        if not decision.allowed:
            raise PermissionError("content_source_policy_denied")
        plan = decision.to_authorized_plan()
        if (
            "content-intelligence" not in plan.allowed_plugins
            or "content-intelligence" not in plan.allowed_capabilities
            or "data:read" not in plan.allowed_capabilities
            or not plan.matches_execution_scope(
                user_id=user_id,
                tenant_id=tenant_id,
                policy_decision_id=decision.decision_id,
            )
        ):
            raise PermissionError("content_source_policy_scope_denied")
        return kernel, decision, plan

    async def list_content_owner_page(
        self, *, user_id: str, tenant_id: str, roles: List[str],
        permissions: List[str], request_id: str, correlation_id: str,
        limit: int = 100, cursor: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read metadata independently of File Explorer lifecycle state."""
        from ai_karen_engine.database.factory import get_database_client
        from ai_karen_engine.extensions.content_intelligence_sources import ContentSourceHost
        from ai_karen_engine.extensions.owner_inventory import ArtifactSourceAdapter
        from ai_karen_engine.services.database.repositories.repository_factory import (
            RepositoryFactory,
        )

        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("content_inventory_limit_invalid")
        if cursor is not None and (
            not isinstance(cursor, str) or not 1 <= len(cursor) <= 768
        ):
            raise ValueError("content_inventory_cursor_invalid")
        kernel, decision, plan = await self._authorize_content_owner_access(
            user_id=user_id, tenant_id=tenant_id, roles=roles,
            permissions=permissions, request_id=request_id, correlation_id=correlation_id,
        )
        context = ExtensionExecutionContext(
            request_id=request_id, correlation_id=correlation_id,
            user_id=user_id, tenant_id=tenant_id,
            policy_decision_id=decision.decision_id,
            allowed_capabilities=list(plan.allowed_capabilities), resource_scope={},
            audit_context={"origin": "authenticated_content_owner_inventory",
                           "user_roles": list(roles), "permissions": list(permissions)},
        )
        await ContentSourceHost.admit_owner_access(kernel=kernel, context=context, plan=plan)
        database = get_database_client()
        if database is None or not callable(getattr(database, "get_async_session", None)):
            raise RuntimeError("content_inventory_database_unavailable")
        repository = RepositoryFactory(
            session_factory=database.get_async_session,
        ).create_artifact_store()
        page = await ArtifactSourceAdapter(repository).list_owner_sources_page(
            tenant_id=tenant_id, user_id=user_id, limit=limit, cursor=cursor,
            **({"search": search} if search is not None else {}),
        )
        logger.info("content_owner_inventory_page", extra={
            "request_id": request_id, "correlation_id": correlation_id,
            "user_id": user_id, "tenant_id": tenant_id,
            "item_count": len(page["items"]), "status": "success",
        })
        return {
            **page, "request_id": request_id, "correlation_id": correlation_id,
            "max_selection": MAX_CONTENT_SOURCE_REFERENCES,
        }

    async def analyze_content_owner_sources(
        self,
        *,
        user_id: str,
        tenant_id: str,
        roles: List[str],
        permissions: List[str],
        request_id: str,
        correlation_id: str,
        operation: str,
        references: List[Dict[str, str]],
        query: Optional[str] = None,
        left_id: Optional[str] = None,
        right_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply fresh RuntimePolicy before owner-source text and plugin execution."""
        from ai_karen_engine.database.factory import get_database_client
        from ai_karen_engine.integrations.supabase_client import get_supabase_platform
        from ai_karen_engine.extensions.content_intelligence_sources import (
            ContentSourceHost,
        )
        from ai_karen_engine.services.database.repositories.repository_factory import (
            RepositoryFactory,
        )

        if not isinstance(references, list) or not 1 <= len(references) <= MAX_CONTENT_SOURCE_REFERENCES:
            raise ValueError("content_source_reference_count_invalid")
        kernel, decision, plan = await self._authorize_content_owner_access(
            user_id=user_id, tenant_id=tenant_id, roles=roles,
            permissions=permissions, request_id=request_id, correlation_id=correlation_id,
        )
        database = get_database_client()
        if database is None or not callable(getattr(database, "get_async_session", None)):
            raise RuntimeError("content_source_database_unavailable")
        # Supply the canonical initialized Storage holder; the ArtifactStore
        # expects a platform with .storage.from_("artifacts"), not the raw
        # storage object. A missing capability must remain unavailable.
        platform = get_supabase_platform()
        if platform is None or getattr(platform, "storage", None) is None:
            raise RuntimeError("content_source_storage_unavailable")
        store = RepositoryFactory(
            session_factory=database.get_async_session,
            storage_client=platform,
        ).create_artifact_store()
        context = ExtensionExecutionContext(
            request_id=request_id,
            correlation_id=correlation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            policy_decision_id=decision.decision_id,
            allowed_capabilities=list(plan.allowed_capabilities),
            resource_scope={},
            audit_context={
                "origin": "authenticated_content_owner_sources",
                "user_roles": list(roles),
                "permissions": list(permissions),
            },
        )
        return await ContentSourceHost(
            store=store, kernel=kernel,
        ).execute_owner_text(
            context=context,
            plan=plan,
            operation=operation,
            references=references,
            query=query,
            left_id=left_id,
            right_id=right_id,
        )

    async def discover_plugins(
        self, force_refresh: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        await self._ensure_initialized()
        kernel = self._get_kernel()
        if force_refresh:
            await kernel.refresh()
        return {
            str(record["manifest"].name): record
            for record in kernel.list_records()
        }

    async def validate_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        record = self._get_kernel().get_record(plugin_name)
        return bool(record and not record.get("error_message"))

    async def register_plugin(self, plugin_name: str) -> bool:
        """Compatibility operation: valid discovered plugins are projected automatically."""
        await self._ensure_initialized()
        return self._get_kernel().runtime_registry.get(plugin_name) is not None

    async def validate_and_register_plugin(self, plugin_name: str) -> bool:
        return await self.validate_plugin(plugin_name) and await self.register_plugin(
            plugin_name
        )

    async def validate_and_register_all_discovered(self) -> Dict[str, bool]:
        await self._ensure_initialized()
        return {
            str(record["manifest"].name): not bool(record.get("error_message"))
            and self._get_kernel().runtime_registry.get(
                str(record["manifest"].name)
            )
            is not None
            for record in self._get_kernel().list_records()
        }

    async def uninstall_plugin_package(self, plugin_id: str) -> Dict[str, Any]:
        """Uninstall a canonical plugin package; never touch free_plugins storage."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", plugin_id):
            raise ValueError("Invalid plugin identifier")
        await self._ensure_initialized()
        root = self._resolve_root()
        target = root / plugin_id
        if root.is_symlink() or target.is_symlink():
            raise ValueError("Unsafe plugin installation path")
        if not target.is_dir():
            raise FileNotFoundError("Plugin is not installed")
        kernel = self._get_kernel()
        lock_path = root / (".plugin-install-" + plugin_id + ".lock")
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        quarantine = root.parent / ".karen-plugin-uninstall"
        moved = None
        try:
            if plugin_id in kernel._active.values():
                raise RuntimeError("Plugin has active executions")
            registration = kernel.runtime_registry.get(plugin_id)
            if registration is not None and registration.state.value != "disabled":
                raise RuntimeError("Disable the plugin before uninstalling it")
            if not target.is_dir() or target.is_symlink():
                raise FileNotFoundError("Plugin is not installed")
            quarantine.mkdir(mode=0o700, parents=True, exist_ok=True)
            if quarantine.is_symlink():
                raise ValueError("Unsafe uninstall quarantine")
            moved = quarantine / (plugin_id + "-" + uuid.uuid4().hex)
            os.rename(target, moved)
            try:
                await kernel.refresh()
                if kernel.get_record(plugin_id) is not None:
                    raise RuntimeError("Uninstalled plugin remains in registry")
            except Exception:
                os.rename(moved, target)
                await kernel.refresh()
                raise
            try:
                shutil.rmtree(moved)
            except OSError:
                logger.warning("Plugin package quarantined for cleanup: %s", plugin_id)
            return {"plugin_id": plugin_id, "uninstalled": True}
        finally:
            os.close(lock_fd)
            lock_path.unlink(missing_ok=True)

    async def install_uploaded_archive(self, plugin_id: str, archive: bytes) -> Dict[str, Any]:
        """Install a user-uploaded plugin package without enabling it.

        This service owns publication into the canonical kernel root; the API
        owns auth, bounded upload ingestion and audit.
        """
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", plugin_id):
            raise ValueError("Invalid plugin identifier")
        if len(archive) > 20 * 1024 * 1024:
            raise ValueError("Plugin archive exceeds 20 MiB")
        # Initialize discovery before publishing untrusted uploaded files.
        # First boot must never discover the uploaded package as default-enabled.
        await self._ensure_initialized()
        root = self._resolve_root()
        if root.is_symlink():
            raise ValueError("Unsafe plugin root")
        root.mkdir(parents=True, exist_ok=True)
        target = root / plugin_id
        if target.exists() or target.is_symlink():
            raise FileExistsError("Plugin already installed; overwrite refused")
        staged = Path(tempfile.mkdtemp(prefix=".plugin-upload-", dir=root))
        published = False
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as uploaded:
                entries = uploaded.infolist()
                if len(entries) > 500:
                    raise ValueError("Too many archive members")
                total_size = 0
                seen_paths: set[str] = set()
                for member in entries:
                    relative = Path(member.filename)
                    if (
                        not member.filename
                        or any(
                            part in {
                                PluginKernel.UPLOADED_ORIGIN_MARKER,
                                PluginKernel.MANUAL_ENABLED_MARKER,
                                ".karen-manual-disabled",
                            }
                            for part in relative.parts
                        )
                        or relative.is_absolute()
                        or ".." in relative.parts
                        or "\\" in member.filename
                        or member.filename.startswith("/")
                    ):
                        raise ValueError("Unsafe package member path")
                    # Reject duplicate paths and file/directory collisions before
                    # extraction, including normalized "." path components.
                    normalized = "/".join(part for part in relative.parts if part != ".")
                    if not normalized or normalized in seen_paths:
                        raise ValueError("Duplicate or invalid package member")
                    seen_paths.add(normalized)
                    mode = (member.external_attr >> 16) & 0xFFFF
                    if stat.S_ISLNK(mode):
                        raise ValueError("Package links are forbidden")
                    if mode and stat.S_IFMT(mode) not in (0, stat.S_IFDIR, stat.S_IFREG):
                        raise ValueError("Unsupported package member type")
                    total_size += member.file_size
                    if total_size > 80 * 1024 * 1024:
                        raise ValueError("Uncompressed package exceeds limit")
                    output = staged.joinpath(*relative.parts)
                    if member.is_dir():
                        output.mkdir(parents=True, exist_ok=True)
                    else:
                        output.parent.mkdir(parents=True, exist_ok=True)
                        with uploaded.open(member) as src, output.open("xb") as dst:
                            shutil.copyfileobj(src, dst)
            manifest_file = staged / "manifest.json"
            if not manifest_file.is_file() or manifest_file.is_symlink():
                raise ValueError("Plugin manifest.json missing at archive root")
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("Invalid plugin manifest")
            # Use the existing canonical manifest schema before publishing files.
            from ai_karen_engine.extensions.platform.core.manifest import (
                ExtensionManifest as CatalogExtensionManifest,
            )
            validated_manifest = CatalogExtensionManifest.from_dict(manifest)
            if not validated_manifest.name:
                raise ValueError("Plugin manifest missing name")
            declared_id = manifest.get("id") or manifest.get("name")
            if declared_id and declared_id != plugin_id:
                raise ValueError("Uploaded plugin manifest identity mismatch")
            if target.exists() or target.is_symlink():
                raise FileExistsError("Plugin installation conflict")
            # Durable opt-in activation gate: marker ships with the package and
            # survives process restarts. Only explicit enable may clear it.
            (staged / ".karen-manual-disabled").write_text(
                "Uploaded plugin remains disabled until isolated execution is available\n",
                encoding="utf-8",
            )
            # This survives explicit disable/enable transitions and catalog refresh.
            # The upload route cannot silently turn into a first-party code source.
            (staged / PluginKernel.UPLOADED_ORIGIN_MARKER).write_text(
                "origin=manual_upload;trust=untrusted\n", encoding="utf-8"
            )
            # Hold the exclusive lock through runtime validation and rollback.
            # Releasing it immediately after rename exposed a partial install.
            lock_path = root / (".plugin-install-" + plugin_id + ".lock")
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                if target.exists() or target.is_symlink():
                    raise FileExistsError("Plugin installation conflict")
                os.rename(staged, target)
                published = True
                try:
                    await self._get_kernel().refresh_with_new_plugin_disabled(plugin_id)
                    record = self._get_kernel().get_record(plugin_id)
                    if record is None or record.get("error_message"):
                        raise ValueError("Uploaded plugin did not pass runtime registry validation")
                except Exception:
                    # Restore the canonical registry after removing a rejected
                    # package so failed uploads cannot remain executable.
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
                    try:
                        await self._get_kernel().refresh()
                    except Exception:
                        logger.exception("Unable to reconcile plugin registry after rejected upload")
                    raise
                return {"plugin_id": plugin_id, "installed": True, "enabled": False}
            finally:
                os.close(lock_fd)
                lock_path.unlink(missing_ok=True)
        finally:
            if not published and staged.exists():
                shutil.rmtree(staged)

    @staticmethod
    def _settings_contract(record: Dict[str, Any]) -> PluginSettingsContract:
        manifest = record.get("manifest")
        if manifest is None or record.get("error_message") or record.get("is_valid") is False:
            raise PluginSettingsNotConfigured("Plugin has no valid settings manifest")
        if record.get("activation_blocked_reason"):
            raise PluginSettingsNotConfigured(
                "Quarantined plugin settings require a verified isolated runtime"
            )
        return PluginSettingsRepository.contract(manifest)

    @staticmethod
    def _settings_response(
        plugin_id: str, contract: PluginSettingsContract, persisted: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "plugin_id": plugin_id,
            "settings": contract.present(persisted["settings"]),
            "schema": [dict(field) for field in contract.fields],
            "revision": persisted["revision"],
            "stored": persisted["revision"] > 0,
        }

    async def read_plugin_settings(
        self, plugin_id: str, tenant_id: str
    ) -> Dict[str, Any]:
        record = await self.get_plugin_info(plugin_id)
        if record is None:
            raise LookupError("Plugin does not exist in the canonical catalog")
        contract = self._settings_contract(record)
        persisted = await self._settings_repository.get(tenant_id, plugin_id)
        return self._settings_response(plugin_id, contract, persisted)

    async def list_plugin_settings(
        self, tenant_id: str
    ) -> List[Dict[str, Any]]:
        records = await self.list_plugins()
        contracts: Dict[str, PluginSettingsContract] = {}
        for record in records:
            try:
                contract = self._settings_contract(record)
            except PluginSettingsNotConfigured:
                continue
            plugin_id = str(record["manifest"].name)
            contracts[plugin_id] = contract
        stored = await self._settings_repository.list_tenant(tenant_id)
        return [
            self._settings_response(
                plugin_id,
                contracts[plugin_id],
                stored.get(plugin_id, {"settings": {}, "revision": 0}),
            )
            for plugin_id in sorted(contracts)
        ]

    async def write_plugin_settings(
        self,
        *,
        plugin_id: str,
        tenant_id: str,
        actor_user_id: str,
        settings: Dict[str, Any],
        revision: int,
        request_id: str,
        correlation_id: str,
        reset: bool = False,
    ) -> Dict[str, Any]:
        record = await self.get_plugin_info(plugin_id)
        if record is None:
            raise LookupError("Plugin does not exist in the canonical catalog")
        contract = self._settings_contract(record)
        verified = contract.validate(
            {} if reset else settings, require_configured=not reset
        )
        new_revision = await self._settings_repository.write(
            tenant_id=tenant_id,
            plugin_id=plugin_id,
            actor_user_id=actor_user_id,
            operation="reset" if reset else "save",
            settings=verified,
            expected_revision=revision,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return {
            **self._settings_response(
                plugin_id, contract, {"settings": verified, "revision": new_revision}
            ),
            "success": True,
            "saved": not reset,
            "reset": reset,
        }

    @staticmethod
    def _plugin_credential_field_keys(
        record: Dict[str, Any],
    ) -> frozenset[str]:
        """Only canonical manifest-declared string secrets are manageable."""
        PluginService._settings_contract(record)
        manifest = record["manifest"]
        config = getattr(manifest, "config_schema", None)
        properties = getattr(config, "properties", None)
        if not isinstance(properties, dict):
            raise PluginSettingsNotConfigured("Plugin has no credential fields")
        allowed = frozenset(
            key for key, definition in properties.items()
            if isinstance(definition, dict)
            and definition.get("type") == "string"
            and PluginSettingsRepository._is_secret(key, definition)
        )
        if not allowed:
            raise PluginSettingsNotConfigured("Plugin has no credential fields")
        if any(len(key) > 50 for key in allowed):
            raise PluginSettingsNotConfigured("Plugin credential field name exceeds Vault limit")
        if len(allowed) > 64:
            raise PluginSettingsNotConfigured("Plugin credential field limit exceeded")
        return allowed

    async def _require_plugin_credential_field(
        self, plugin_id: str, field_key: str | None = None
    ) -> frozenset[str]:
        record = await self.get_plugin_info(plugin_id)
        if record is None:
            raise LookupError("Plugin does not exist in the canonical catalog")
        allowed = self._plugin_credential_field_keys(record)
        if field_key is not None and field_key not in allowed:
            # A URL cannot select an arbitrary existing vault secret type.
            raise PluginSettingsNotConfigured("Plugin credential field is not declared")
        return allowed

    async def read_plugin_credential_status(
        self, plugin_id: str, tenant_id: str
    ) -> Dict[str, Any]:
        allowed = await self._require_plugin_credential_field(plugin_id)
        fields = await get_credential_vault_service().list_plugin_credential_status(
            tenant_id=uuid.UUID(str(tenant_id)),
            plugin_id=plugin_id,
            field_keys=allowed,
        )
        return {"plugin_id": plugin_id, "fields": fields}

    async def write_plugin_credential(
        self,
        *,
        plugin_id: str,
        field_key: str,
        tenant_id: str,
        actor_user_id: str,
        secret_value: str,
        revision: int,
        correlation_id: str,
    ) -> Dict[str, Any]:
        await self._require_plugin_credential_field(plugin_id, field_key)
        receipt = await get_credential_vault_service().write_plugin_credential(
            tenant_id=uuid.UUID(str(tenant_id)),
            actor_user_id=actor_user_id,
            plugin_id=plugin_id,
            field_key=field_key,
            secret_value=secret_value,
            expected_revision=revision,
            correlation_id=correlation_id,
        )
        return {"plugin_id": plugin_id, "field_key": field_key, **receipt}

    async def revoke_plugin_credential(
        self,
        *,
        plugin_id: str,
        field_key: str,
        tenant_id: str,
        actor_user_id: str,
        revision: int,
        correlation_id: str,
    ) -> Dict[str, Any]:
        await self._require_plugin_credential_field(plugin_id, field_key)
        receipt = await get_credential_vault_service().revoke_plugin_credential(
            tenant_id=uuid.UUID(str(tenant_id)),
            actor_user_id=actor_user_id,
            plugin_id=plugin_id,
            field_key=field_key,
            expected_revision=revision,
            correlation_id=correlation_id,
        )
        return {"plugin_id": plugin_id, "field_key": field_key, **receipt}

    async def _execution_configuration_readiness(
        self, plugin_name: str, tenant_id: str
    ) -> Optional[str]:
        """Verify canonical installation and tenant configuration before execution.

        This single admission owner validates catalog provenance, persisted
        nonsecret settings and Vault credential *status*. It never reads or
        injects secret values into the plugin execution payload.
        """
        kernel = self._get_kernel()
        record = kernel.get_record(plugin_name)
        if record is None or record.get("error_message") or record.get("is_valid") is False:
            return "plugin_manifest_invalid"
        if record.get("activation_blocked_reason"):
            return "plugin_origin_untrusted"
        manifest = record.get("manifest")
        if manifest is None:
            return "plugin_manifest_invalid"
        schema = getattr(manifest, "config_schema", None)
        if schema is None:
            # Configuration-free, already-governed built-ins do not acquire a
            # dependency on tenant settings or Vault credential status.
            return None

        if (
            getattr(manifest, "name", None) != plugin_name
            or record.get("status") not in {"enabled", "active"}
            or record.get("dependencies_resolved") is not True
            or record.get("compatibility_checked") is not True
        ):
            return "plugin_installation_unverified"
        try:
            root = self._resolve_root()
            package = root / plugin_name
            source = Path(record["path"])
            if (
                root.is_symlink()
                or package.is_symlink()
                or source.is_symlink()
                or not package.is_dir()
                or source.resolve(strict=True) != package.resolve(strict=True)
                or package.resolve(strict=True).parent != root.resolve(strict=True)
                or kernel._is_uploaded_plugin(plugin_name)
            ):
                return "plugin_installation_unverified"
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return "plugin_installation_unverified"

        properties = getattr(schema, "properties", None)
        required_raw = getattr(schema, "required", ()) or ()
        if (
            not isinstance(properties, dict)
            or not isinstance(required_raw, (list, tuple))
            or any(not isinstance(key, str) for key in required_raw)
        ):
            return "plugin_configuration_invalid"
        required = set(required_raw)
        if (
            len(properties) > 64
            or not required.issubset(properties)
            or any(
                not isinstance(key, str) or not isinstance(definition, dict)
                for key, definition in properties.items()
            )
        ):
            return "plugin_configuration_invalid"
        if not properties:
            return None

        secret_fields = {
            key
            for key, definition in properties.items()
            if PluginSettingsRepository._is_secret(key, definition)
        }
        ordinary_fields = set(properties) - secret_fields
        required_nonsecret = required - secret_fields
        try:
            contract = self._settings_contract(record)
        except PluginSettingsNotConfigured:
            return "plugin_configuration_invalid"
        if not required_nonsecret.issubset(contract.rules):
            return "plugin_configuration_invalid"

        if ordinary_fields:
            try:
                persisted = await self._settings_repository.get(
                    tenant_id, plugin_name
                )
                revision = persisted.get("revision")
                if (
                    not isinstance(revision, int)
                    or isinstance(revision, bool)
                    or revision < 0
                ):
                    return "plugin_configuration_unavailable"
                if required_nonsecret and revision == 0:
                    return "plugin_configuration_missing"
                contract.validate(persisted["settings"], require_configured=True)
            except (PluginSettingsValidationError, TypeError, ValueError, KeyError):
                return "plugin_configuration_invalid"
            except Exception as exc:
                logger.warning(
                    "plugin.configuration_readiness_unavailable",
                    extra={
                        "plugin_id": plugin_name,
                        "error_type": type(exc).__name__,
                    },
                )
                return "plugin_configuration_unavailable"

        if secret_fields:
            try:
                states = await get_credential_vault_service().list_plugin_credential_status(
                    tenant_id=uuid.UUID(str(tenant_id)),
                    plugin_id=plugin_name,
                    field_keys=frozenset(secret_fields),
                )
                if not isinstance(states, dict):
                    return "plugin_credentials_unavailable"
                for field in secret_fields:
                    status = states.get(field)
                    if not isinstance(status, dict):
                        return "plugin_credentials_unavailable"
                    if field in required or status.get("status") != "missing":
                        revision = status.get("revision")
                        if (
                            status.get("status") != "active"
                            or not isinstance(revision, int)
                            or isinstance(revision, bool)
                            or revision < 1
                        ):
                            return "plugin_credentials_unavailable"
            except Exception as exc:
                logger.warning(
                    "plugin.credential_readiness_unavailable",
                    extra={
                        "plugin_id": plugin_name,
                        "error_type": type(exc).__name__,
                    },
                )
                return "plugin_credentials_unavailable"
        return None

    async def refresh_plugins(self) -> int:
        await self._ensure_initialized()
        return await self._get_kernel().refresh()

    @staticmethod
    def _type_matches(value: Any, expected: str) -> bool:
        mapping = {
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "array": lambda item: isinstance(item, list),
            "object": lambda item: isinstance(item, dict),
            "null": lambda item: item is None,
        }
        validator = mapping.get(str(expected).lower())
        if validator is None:
            raise ValueError(f"Unsupported schema type '{expected}'")
        return bool(validator(value))

    @classmethod
    def _validate_value(
        cls, value: Any, rules: Dict[str, Any], path: str
    ) -> None:
        expected = rules.get("type")
        if expected and not cls._type_matches(value, str(expected)):
            raise ValueError(f"Parameter '{path}' must be of type '{expected}'")
        allowed = rules.get("enum")
        if allowed is not None and value not in allowed:
            raise ValueError(f"Parameter '{path}' is not an allowed value")

        if isinstance(value, str):
            minimum = rules.get("minLength", rules.get("min_length"))
            maximum = rules.get("maxLength", rules.get("max_length"))
            if minimum is not None and len(value) < int(minimum):
                raise ValueError(f"Parameter '{path}' is too short")
            if maximum is not None and len(value) > int(maximum):
                raise ValueError(f"Parameter '{path}' is too long")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = rules.get("minimum", rules.get("min"))
            maximum = rules.get("maximum", rules.get("max"))
            if minimum is not None and value < minimum:
                raise ValueError(f"Parameter '{path}' is below minimum")
            if maximum is not None and value > maximum:
                raise ValueError(f"Parameter '{path}' exceeds maximum")

        if isinstance(value, list) and isinstance(rules.get("items"), dict):
            for index, item in enumerate(value):
                cls._validate_value(item, rules["items"], f"{path}[{index}]")

        if isinstance(value, dict) and isinstance(rules.get("properties"), dict):
            properties = rules["properties"]
            required = {str(item) for item in rules.get("required", []) or []}
            missing = sorted(required - set(value))
            if missing:
                raise ValueError(
                    f"Parameter '{path}' is missing required fields: {', '.join(missing)}"
                )
            additional = rules.get(
                "additionalProperties",
                rules.get("additional_properties", True),
            )
            unexpected = set(value) - set(properties)
            if unexpected and not bool(additional):
                raise ValueError(
                    f"Parameter '{path}' contains undeclared fields: "
                    + ", ".join(sorted(unexpected))
                )
            for key, nested in value.items():
                nested_rules = properties.get(key)
                if isinstance(nested_rules, dict):
                    cls._validate_value(nested, nested_rules, f"{path}.{key}")

    def _validate_parameter_contract(
        self, plugin_name: str, parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(parameters, dict):
            raise ValueError("Plugin parameters must be a JSON object")
        record = self._get_kernel().get_record(plugin_name)
        if record is None:
            raise LookupError(plugin_name)
        manifest = record.get("manifest")
        if manifest is None:
            raise ValueError("Plugin has no canonical invocation manifest")
        # The canonical kernel owns the projection. Persisted config fields
        # are not caller parameters and must not be used to validate actions.
        rules = PluginKernel.execution_input_schema(manifest)
        if not rules:
            return dict(parameters)
        self._validate_value(parameters, rules, "parameters")
        return dict(parameters)

    async def validate_plugin_parameters(
        self, plugin_name: str, parameters: Dict[str, Any]
    ) -> bool:
        await self._ensure_initialized()
        try:
            self._validate_parameter_contract(plugin_name, parameters)
        except (LookupError, TypeError, ValueError):
            return False
        return True

    @staticmethod
    def _failure(
        *,
        request_id: str,
        plugin_name: str,
        code: str,
        message: str,
        user_id: str,
        tenant_id: str,
        session_id: Optional[str],
        conversation_id: Optional[str],
        correlation_id: str,
        policy_decision_id: Optional[str],
        requested_capabilities: List[str],
    ) -> PluginExecutionResult:
        now = datetime.now(timezone.utc)
        return PluginExecutionResult(
            request_id=request_id,
            plugin_name=plugin_name,
            plugin_id=plugin_name,
            status=ExecutionStatus.FAILED,
            error=message,
            error_code=code,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=str(session_id or ""),
            conversation_id=str(conversation_id or ""),
            correlation_id=correlation_id,
            policy_decision_id=str(policy_decision_id or ""),
            requested_capabilities=list(requested_capabilities),
            completed_at=now,
        )

    @staticmethod
    def _adapt_result(
        result: ExtensionExecutionResult,
        *,
        plugin_name: str,
        user_id: str,
        tenant_id: str,
        session_id: Optional[str],
        conversation_id: Optional[str],
        requested_capabilities: List[str],
        granted_capabilities: List[str],
    ) -> PluginExecutionResult:
        status = (
            ExecutionStatus.COMPLETED
            if result.status == "success"
            else ExecutionStatus.FAILED
        )
        return PluginExecutionResult(
            request_id=result.request_id,
            plugin_name=plugin_name,
            plugin_id=result.plugin_id,
            plugin_version=result.plugin_version,
            status=status,
            result=result.payload,
            error=result.error_detail,
            error_code=result.error_code,
            execution_time=max(float(result.latency_ms), 0.0) / 1000.0,
            started_at=result.created_at,
            completed_at=datetime.now(timezone.utc),
            metadata={
                "execution_id": result.execution_id,
                "source": result.source.value,
                "trust_tier": result.trust_tier.value,
                "result_trust": result.result_trust.value,
                "data_classification": result.data_classification.value,
                "side_effects": list(result.side_effects),
            },
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=str(session_id or ""),
            conversation_id=str(conversation_id or ""),
            correlation_id=str(result.correlation_id or ""),
            policy_decision_id=str(result.policy_decision_id or ""),
            requested_capabilities=list(requested_capabilities),
            granted_capabilities=list(granted_capabilities),
        )

    def _record_result(self, result: PluginExecutionResult) -> PluginExecutionResult:
        """Retain bounded metadata, not private binary media, in execution history.

        The current authorized caller still receives the original complete
        result. History projections are separate objects so that observability
        cannot accidentally retain WAV/image buffers across chat sessions.
        """
        history_entry = result
        if isinstance(result.result, dict) and isinstance(result.result.get("audio_base64"), str):
            original = result.result
            history_entry = replace(
                result,
                result={
                    "engine": str(original.get("engine") or "")[:80],
                    "voice_id": str(original.get("voice_id") or "")[:96],
                    "content_type": str(original.get("content_type") or "")[:80],
                    "media_payload_redacted": True,
                },
                metadata={**result.metadata, "media_payload_redacted": True},
            )
        elif isinstance(result.result, (bytes, bytearray, memoryview)):
            history_entry = replace(
                result,
                result={"media_payload_redacted": True},
                metadata={**result.metadata, "media_payload_redacted": True},
            )
        self._history.append(history_entry)
        if len(self._history) > 1000:
            del self._history[:-1000]
        return result

    @staticmethod
    def _permission_granted(grants: List[str], required: str) -> bool:
        normalized = {str(value).strip() for value in grants if str(value).strip()}
        if "*" in normalized or required in normalized:
            return True
        if ":" in required and required.split(":", 1)[0] in normalized:
            return True
        return False

    async def execute_plugin(
        self,
        plugin_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        execution_mode: ExecutionMode = ExecutionMode.SANDBOX,
        timeout_seconds: int = 30,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        permissions: Optional[List[str]] = None,
        policy_decision_id: Optional[str] = None,
        authorized_plan: Optional[AuthorizedExecutionPlan] = None,
        allowed_capabilities: Optional[List[str]] = None,
        forbidden_capabilities: Optional[List[str]] = None,
        *,
        runtime_context: Any = None,
        execution_meter: Any = None,
    ) -> PluginExecutionResult:
        """Execute through RuntimePolicy and the one canonical extension executor."""
        del execution_mode  # Runtime isolation comes from the execution manifest.
        await self._ensure_initialized()
        request_id = str(uuid.uuid4())
        resolved_user = str(user_id or "").strip()
        resolved_tenant = str(tenant_id or "").strip()
        resolved_correlation = str(correlation_id or "").strip() or request_id
        requested_caps = list(allowed_capabilities or [])

        def failure(code: str, message: str) -> PluginExecutionResult:
            return self._record_result(
                self._failure(
                    request_id=request_id,
                    plugin_name=plugin_name,
                    code=code,
                    message=message,
                    user_id=resolved_user,
                    tenant_id=resolved_tenant,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    correlation_id=resolved_correlation,
                    policy_decision_id=policy_decision_id,
                    requested_capabilities=requested_caps,
                )
            )

        if not resolved_user or not resolved_tenant:
            return failure(
                "identity_scope_missing",
                "Plugin execution requires authenticated user and tenant scope",
            )

        try:
            validated_parameters = self._validate_parameter_contract(
                plugin_name, parameters or {}
            )
        except LookupError:
            return failure("plugin_not_found", "Plugin not found")
        except (TypeError, ValueError):
            return failure(
                "invalid_parameters",
                "Plugin parameters do not satisfy the manifest contract",
            )

        required_permissions = self._get_kernel().get_required_permissions(plugin_name)
        principal_permissions = list(permissions or [])
        missing_principal_permissions = [
            permission
            for permission in required_permissions
            if not self._permission_granted(principal_permissions, permission)
        ]
        if missing_principal_permissions:
            return failure(
                "permission_denied",
                "Plugin execution requires permissions: "
                + ", ".join(missing_principal_permissions),
            )
        for permission in required_permissions:
            if permission not in requested_caps:
                requested_caps.append(permission)

        if authorized_plan is not None and not isinstance(
            authorized_plan, AuthorizedExecutionPlan
        ):
            return failure(
                "authorized_plan_invalid",
                "Plugin execution requires a typed AuthorizedExecutionPlan",
            )

        if (runtime_context is not None or execution_meter is not None) and authorized_plan is None:
            return failure("extension_runtime_authority_invalid", "Original runtime plan required")

        if authorized_plan is None:
            if policy_decision_id:
                return failure(
                    "authorized_plan_required",
                    "A policy_decision_id alone cannot authorize plugin execution",
                )
            decision = await self._policy_enforcer.evaluate(
                PolicyEvaluationRequest(
                    user_id=resolved_user,
                    tenant_id=resolved_tenant,
                    session_id=session_id,
                    correlation_id=resolved_correlation,
                    roles=list(roles or []),
                    permissions=principal_permissions,
                    action="plugin_execution",
                    plugin_id=plugin_name,
                    requested_capabilities=requested_caps,
                    forbidden_capabilities=list(forbidden_capabilities or []),
                )
            )
            if not decision.allowed:
                policy_decision_id = decision.decision_id
                return failure(
                    "policy_denied", "Plugin execution denied by RuntimePolicy"
                )
            authorized_plan = decision.to_authorized_plan()
        elif policy_decision_id and policy_decision_id != authorized_plan.policy_decision_id:
            return failure(
                "policy_decision_mismatch",
                "policy_decision_id does not match AuthorizedExecutionPlan",
            )

        policy_decision_id = authorized_plan.policy_decision_id
        if not authorized_plan.matches_execution_scope(
            user_id=resolved_user,
            tenant_id=resolved_tenant,
            session_id=session_id,
            policy_decision_id=policy_decision_id,
        ):
            return failure(
                "authorized_scope_mismatch",
                "AuthorizedExecutionPlan does not match execution identity scope",
            )
        if plugin_name not in authorized_plan.allowed_plugins:
            return failure(
                "plugin_not_authorized",
                "Plugin is not present in AuthorizedExecutionPlan.allowed_plugins",
            )
        missing_plan_permissions = [
            permission
            for permission in required_permissions
            if not self._permission_granted(
                list(authorized_plan.allowed_capabilities), permission
            )
        ]
        if missing_plan_permissions:
            return failure(
                "permission_plan_mismatch",
                "AuthorizedExecutionPlan does not grant plugin permissions: "
                + ", ".join(missing_plan_permissions),
            )
        if not await ActionExecutionGate.authorize(authorized_plan, plugin_name):
            return failure(
                "action_gate_denied",
                "Plugin execution denied by ActionExecutionGate",
            )

        readiness = await self._execution_configuration_readiness(
            plugin_name, resolved_tenant
        )
        if readiness is not None:
            return failure(
                readiness,
                "Plugin tenant configuration is not ready for execution",
            )

        context = ExtensionExecutionContext(
            request_id=request_id,
            correlation_id=resolved_correlation,
            user_id=resolved_user,
            tenant_id=resolved_tenant,
            session_id=session_id,
            conversation_id=conversation_id,
            policy_decision_id=policy_decision_id,
            allowed_capabilities=list(authorized_plan.allowed_capabilities),
            resource_scope=dict(authorized_plan.resource_scope),
            audit_context={
                "user_roles": list(roles or []),
                "permissions": principal_permissions,
            },
        )
        if runtime_context is not None or execution_meter is not None:
            if plugin_name != "intelligent-search":
                return failure("extension_runtime_authority_invalid", "Runtime search authority is restricted to Intelligent Search")
            try:
                context.bind_runtime_authority(runtime_context, authorized_plan, execution_meter, plugin_name)
            except PermissionError:
                return failure("extension_runtime_authority_invalid", "Original runtime authority does not match plugin execution")

        canonical_request = ExtensionExecutionRequest(
            plugin_id=plugin_name,
            capability=PluginKernel.EXECUTE_CAPABILITY,
            payload=validated_parameters,
            context=context,
            authorized_plan=authorized_plan,
            timeout_override_ms=max(int(timeout_seconds), 1) * 1000,
        )
        try:
            canonical_result = await self._get_kernel().execute(canonical_request)
        except Exception as exc:
            logger.exception("Canonical plugin execution failed for %s", plugin_name)
            return failure("plugin_execution_error", str(exc))

        return self._record_result(
            self._adapt_result(
                canonical_result,
                plugin_name=plugin_name,
                user_id=resolved_user,
                tenant_id=resolved_tenant,
                session_id=session_id,
                conversation_id=conversation_id,
                requested_capabilities=requested_caps,
                granted_capabilities=list(authorized_plan.allowed_capabilities),
            )
        )

    async def cancel_execution(self, request_id: str) -> bool:
        """Cancellation is unsupported until the canonical executor exposes handles."""
        del request_id
        await self._ensure_initialized()
        return False

    def get_plugin(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        if not self.initialized or self.kernel is None:
            return None
        return self.kernel.get_record(plugin_name)

    async def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        await self._ensure_initialized()
        return self.get_plugin(plugin_name)

    async def list_plugins(
        self,
        category: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[Dict[str, Any]]:
        await self._ensure_initialized()
        plugins = self._get_kernel().list_records()
        if category:
            plugins = [
                plugin
                for plugin in plugins
                if str(getattr(plugin.get("manifest"), "category", "")) == category
            ]
        if enabled_only:
            plugins = [
                plugin
                for plugin in plugins
                if str(plugin.get("status")) in _ENABLED_STATES
            ]
        return list(plugins)



    async def preview_conversational_management(
        self, *, plugin_id: str, action: str, principal: Any,
    ) -> Dict[str, Any]:
        """Read the canonical global lifecycle state without changing it.

        Installation-state mutations are application-global and protected by
        ADMIN_PLUGINS_MANAGE at the existing plugin management API. Conversational
        inspection must not turn an authenticated ordinary user into an admin,
        or turn approval prose into an executable lifecycle grant.
        """
        from ai_karen_engine.auth.models import UserData
        from ai_karen_engine.auth.rbac_middleware import (
            Permission, get_rbac_manager,
        )

        if (
            not isinstance(principal, UserData)
            or not principal.user_id or not principal.tenant_id
            or principal.is_active is not True
            or principal.is_verified is not True
        ):
            raise PermissionError("Verified plugin management principal required")
        if (
            not isinstance(plugin_id, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,49}", plugin_id)
            or not isinstance(action, str)
            or not re.fullmatch(r"[a-z]{3,15}", action)
        ):
            raise ValueError("Invalid plugin management request")

        request = {
            "installation_id": plugin_id,
            "requested_action": action,
            "operation_scope": "application_global",
            "required_permission": Permission.ADMIN_PLUGINS_MANAGE.value,
            "permission_verified": False,
            "approval_granted": False,
            "mutation_performed": False,
            "action_receipt": None,
            "next_action": None,
        }
        if action not in {"enable", "disable"}:
            return {**request, "status": "unsupported_action"}

        record = self._get_kernel().get_record(plugin_id)
        manifest = record.get("manifest") if isinstance(record, dict) else None
        if (
            manifest is None
            or getattr(manifest, "name", None) != plugin_id
            or record.get("is_valid") is not True
            or record.get("activation_blocked_reason")
        ):
            return {**request, "status": "unavailable_installation"}
        capabilities = getattr(manifest, "capabilities", None)
        channel = getattr(capabilities, "communication_channel", None)
        voice = getattr(capabilities, "voice_modality", None)
        if channel is not None:
            return {
                **request, "status": "delegated_to_channel_host",
                "next_action": "channel.inspect_and_request_operator_authorization",
            }
        if voice is not None:
            return {
                **request, "status": "delegated_to_voice_runtime",
                "next_action": "voice.inspect_and_request_operator_authorization",
            }

        # This is a fresh, read-only eligibility check. The actual mutation
        # must still run through the existing authenticated and audited admin
        # management endpoint with its own authorization and confirmation.
        authorized = get_rbac_manager().has_permission(
            principal, Permission.ADMIN_PLUGINS_MANAGE,
        )
        state = str(getattr(record.get("status"), "value", record.get("status") or "unknown"))
        if not authorized:
            return {
                **request, "status": "permission_denied",
                "current_state": state,
            }
        if state not in {"enabled", "disabled", "active", "loaded", "registered"}:
            return {
                **request, "status": "unsupported_state",
                "permission_verified": True, "current_state": state,
            }
        enabled = state in {"enabled", "active", "loaded", "registered"}
        requested_enabled = action == "enable"
        if enabled == requested_enabled:
            return {
                **request, "status": "already_satisfied",
                "permission_verified": True, "current_state": state,
                "next_action": "plugin.verify_runtime_state",
            }
        return {
            **request, "status": "needs_explicit_confirmation",
            "permission_verified": True, "current_state": state,
            "next_action": "plugin.open_admin_management",
            "confirmation_channel": "authenticated_plugin_management_ui",
        }

    @staticmethod
    def _inspection_key(value: object) -> str:
        """Canonical comparison of catalog names; no fuzzy execution aliases."""
        return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))

    async def inspect_for_conversation(
        self, *, tenant_id: str, target: Optional[str] = None, limit: int = 25,
        caller_roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Read-only, redacted plugin catalog for authenticated ChatRuntime.

        Runtime checks the authenticated user and plugin.inspect authorization
        before invoking this facade. A channel extension remains disabled for
        generic invocation even when the host may separately activate a tenant
        connection. Neither credential readiness nor live delivery may be
        deduced from a manifest or this catalog projection.
        """
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise PermissionError("Authenticated tenant scope required")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid plugin inspection result bound")
        if target is not None and (
            not isinstance(target, str)
            or not 1 <= len(target) <= 80
            or self._inspection_key(target) == ""
        ):
            raise ValueError("Invalid plugin inspection target")

        # Caller roles come solely from ChatExecutionContext's verified
        # principal, never from user prose, tool output or plugin metadata.
        role_set = {
            str(role).casefold().strip()
            for role in (caller_roles or [])
            if isinstance(role, str) and role.strip()
        }
        records = await self.list_plugins()
        kernel = self._get_kernel()
        requested_key = self._inspection_key(target) if target is not None else None
        candidates: list[tuple[int, Dict[str, Any]]] = []
        for record in records:
            manifest = record.get("manifest")
            if manifest is None:
                continue
            plugin_id = str(getattr(manifest, "name", "") or "")
            if not plugin_id:
                continue
            display_name = str(
                getattr(manifest, "display_name", "") or plugin_id
            )
            tags = [
                str(tag) for tag in (getattr(manifest, "tags", None) or ())
                if isinstance(tag, str) and 0 < len(tag) <= 48
            ]
            aliases = (
                {self._inspection_key(plugin_id): 3,
                 self._inspection_key(display_name): 2}
            )
            for tag in tags:
                aliases.setdefault(self._inspection_key(tag), 1)
            score = aliases.get(requested_key, 0) if requested_key is not None else 1
            if not score:
                continue
            candidate = {
                "record": record, "manifest": manifest,
                "plugin_id": plugin_id, "display_name": display_name,
            }
            candidates.append((score, candidate))

        if requested_key is not None and candidates:
            best_score = max(item[0] for item in candidates)
            candidates = [item for item in candidates if item[0] == best_score]

        # Never silently pick the first plugin for an ambiguous capability
        # name, and never load or execute a plugin handler during inspection.
        candidates.sort(key=lambda item: item[1]["plugin_id"])
        selected = candidates[:limit]
        projections: list[Dict[str, Any]] = []
        for _, item in selected:
            record = item["record"]
            manifest = item["manifest"]
            plugin_id = item["plugin_id"]
            display_name = item["display_name"]
            channel = getattr(
                getattr(manifest, "capabilities", None),
                "communication_channel", None,
            )
            validated = record.get("is_valid") is True
            registration_state = str(record.get("status") or "unknown")
            blocked = bool(record.get("activation_blocked_reason"))
            manifest_roles = {
                str(getattr(role, "value", role)).casefold().strip()
                for role in (
                    getattr(getattr(manifest, "rbac", None), "allowed_roles", ())
                    or ()
                )
            }
            role_eligible = bool(manifest_roles.intersection(role_set))
            capabilities = getattr(manifest, "capabilities", None)
            declared_generic_features = [
                label
                for flag, label in (
                    ("provides_api", "plugin.api"),
                    ("provides_ui", "plugin.ui"),
                    ("provides_background_tasks", "plugin.background_tasks"),
                    ("provides_webhooks", "plugin.webhooks"),
                )
                if bool(getattr(capabilities, flag, False))
            ]
            voice = getattr(capabilities, "voice_modality", None)
            if voice is not None:
                declared_generic_features.extend(
                    f"voice.{modality}"
                    for modality in list(getattr(voice, "modalities", ()) or ())[:10]
                    if isinstance(modality, str)
                )
            if channel is not None:
                host_eligible = bool(
                    validated and not blocked
                    and kernel.get_channel_activation_manifest(plugin_id) is not None
                )
                next_action = (
                    "channel.inspect_owned_connections"
                    if host_eligible else "channel.installation_review"
                )
                readiness = "requires_authorized_channel_inspection"
                execution_route = "channel_host"
                features = [
                    *(
                        f"channel.inbound.{kind}"
                        for kind in sorted(getattr(channel, "inbound", ()) or ())
                    ),
                    *(
                        f"channel.outbound.{kind}"
                        for kind in sorted(getattr(channel, "outbound", ()) or ())
                    ),
                ][:20]
            elif voice is not None:
                # Voice plugins execute through the existing governed
                # VoiceRuntime engine catalog, not a second chat voice runner.
                # A manifest declaration alone is not a ready local engine.
                host_eligible = False
                execution_route = "voice_runtime"
                features = declared_generic_features[:20]
                if not validated or blocked:
                    readiness = "invalid_or_blocked"
                    next_action = "plugin.installation_review"
                elif registration_state not in {"enabled", "active"}:
                    readiness = "disabled"
                    next_action = "plugin.enable_with_approval"
                else:
                    readiness = "requires_authorized_voice_catalog"
                    next_action = "voice.inspect_engine_catalog"
            else:
                host_eligible = False
                execution_route = "plugin_executor"
                features = declared_generic_features[:20]
                if not validated or blocked:
                    readiness = "invalid_or_blocked"
                    next_action = "plugin.installation_review"
                elif registration_state not in {"enabled", "active"}:
                    readiness = "disabled"
                    next_action = "plugin.enable_with_approval"
                else:
                    reason = await self._execution_configuration_readiness(
                        plugin_id, tenant_id
                    )
                    readiness = "ready" if reason is None else reason
                    next_action = (
                        "plugin.use_authorized_capability"
                        if reason is None else "plugin.configure_securely"
                    )
            projections.append({
                "installation_id": plugin_id,
                "display_name": (
                    display_name if len(display_name) <= 80
                    and all(char.isprintable() for char in display_name)
                    else plugin_id
                ),
                "category": str(getattr(manifest, "category", "") or "")[:40],
                "registered": validated,
                "role_eligible": role_eligible,
                "role_check_source": "manifest_rbac",
                "generic_execution_enabled": (
                    channel is None and registration_state in {"enabled", "active"}
                    and validated and not blocked
                ),
                # Installation status and manifest role eligibility are
                # independent from a fresh action-specific RuntimePolicy grant.
                "authorized_to_execute": False,
                "execution_route": execution_route,
                "channel_host_eligible": host_eligible,
                "connection_status": (
                    "not_inspected" if channel is not None else "not_applicable"
                ),
                "credential_status": "not_inspected",
                "webhook_verified": False,
                "runtime_execution_verified": False,
                "provider_send_verified": False,
                "provider_delivery_verified": False,
                "readiness": readiness,
                "next_action": next_action,
                "declared_features": features,
            })

        status = (
            "not_found" if requested_key is not None and not candidates
            else "ambiguous" if requested_key is not None and len(candidates) > 1
            else "found"
        )
        return {
            "status": status,
            "target": target,
            "catalog_source": "plugin_kernel",
            "matches": projections,
            "truncated": len(candidates) > limit,
            "mutation_performed": False,
        }


    @staticmethod
    def _chat_action_phrase(value: str) -> str:
        """Normalize exact manifest-declared utterances, never build regexes."""
        return " ".join(value.casefold().strip().rstrip(" ?!.").split())

    def resolve_conversational_read_action(
        self, *, plugin_id: str, goal: str, caller_roles: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Resolve one read-only, fixed-input action from a verified manifest.

        Only canonical installed plugins may opt in through the strict
        manifest-owned conversational_actions contract. Nothing in this method
        invokes plugin code or grants a permission. The regular execute_plugin
        method remains the sole application execution owner, including the
        fresh RuntimePolicy decision, action gate, schema and tenant readiness.
        """
        if (
            not isinstance(plugin_id, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,49}", plugin_id)
            or not isinstance(goal, str)
            or not 1 <= len(goal.strip()) <= 240
            or not isinstance(caller_roles, list)
        ):
            return None
        kernel = self._get_kernel()
        record = kernel.get_record(plugin_id)
        if (
            record is None
            or record.get("is_valid") is not True
            or record.get("status") not in {"enabled", "active"}
            or record.get("activation_blocked_reason")
        ):
            return None
        manifest = record.get("manifest")
        if (
            manifest is None
            or getattr(manifest, "name", None) != plugin_id
            or getattr(getattr(manifest, "capabilities", None), "communication_channel", None)
            is not None
            or getattr(getattr(manifest, "capabilities", None), "voice_modality", None)
            is not None
        ):
            return None
        roles = {
            str(role).casefold().strip()
            for role in caller_roles
            if isinstance(role, str) and role.strip()
        }
        manifest_roles = {
            str(getattr(role, "value", role)).casefold().strip()
            for role in (
                getattr(getattr(manifest, "rbac", None), "allowed_roles", ())
                or ()
            )
        }
        if not roles.intersection(manifest_roles):
            return None
        governance = getattr(manifest, "governance", None)
        if not isinstance(governance, dict):
            return None
        contract = governance.get("conversational_actions")
        if (
            not isinstance(contract, dict)
            or set(contract) != {"version", "actions"}
            or type(contract["version"]) is not int
            or contract["version"] != 1
            or not isinstance(contract["actions"], list)
            or not 1 <= len(contract["actions"]) <= 16
        ):
            return None

        # A malformed or ambiguous manifest action registry denies the whole
        # selection. Arbitrary strings from a model or client never become
        # plugin parameters, and secrets cannot enter fixed action inputs.
        actions: list[Dict[str, Any]] = []
        seen_action_ids: set[str] = set()
        seen_utterances: set[str] = set()
        for item in contract["actions"]:
            if (
                not isinstance(item, dict)
                or set(item) != {
                    "id", "utterances", "parameters",
                    "side_effect_level", "requires_confirmation",
                }
                or not isinstance(item["id"], str)
                or not re.fullmatch(r"[a-z][a-z0-9_.-]{1,63}", item["id"])
                or item["side_effect_level"] != "none"
                or item["requires_confirmation"] is not False
                or not isinstance(item["utterances"], list)
                or not 1 <= len(item["utterances"]) <= 16
                or not isinstance(item["parameters"], dict)
                or len(item["parameters"]) > 12
            ):
                return None
            if any(
                not isinstance(phrase, str)
                or not 3 <= len(phrase.strip()) <= 160
                for phrase in item["utterances"]
            ):
                return None
            if any(
                not isinstance(key, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
                or re.search(r"(?:token|password|secret|credential|api_key)", key)
                or type(value) not in {str, int, float, bool}
                or (isinstance(value, str) and len(value) > 160)
                or (isinstance(value, float) and not math.isfinite(value))
                for key, value in item["parameters"].items()
            ):
                return None
            if item["id"] in seen_action_ids:
                return None
            seen_action_ids.add(item["id"])
            for phrase in item["utterances"]:
                normalized = self._chat_action_phrase(phrase)
                if not normalized or normalized in seen_utterances:
                    return None
                seen_utterances.add(normalized)
            actions.append(item)
        normalized_goal = self._chat_action_phrase(goal)
        matches = [
            item for item in actions
            if normalized_goal in {
                self._chat_action_phrase(phrase)
                for phrase in item["utterances"]
            }
        ]
        if len(matches) != 1:
            return None
        selected = matches[0]
        # Return a copy only of fixed, inspected manifest input. The requested
        # utterance itself is not sent to the plugin unless a future reviewed
        # prompt contract explicitly declares a safe parameter mapping.
        return {
            "action_id": selected["id"],
            "parameters": dict(selected["parameters"]),
            "authorization_required": "fresh_plugin_execution_policy",
            "manifest_source": "plugin_kernel",
        }

    def get_plugins_by_category(self, category: str) -> List[Dict[str, Any]]:
        if not self.initialized or self.kernel is None:
            return []
        return [
            record
            for record in self.kernel.list_records()
            if str(getattr(record.get("manifest"), "category", "")) == category
        ]

    def get_plugins_by_type(self, plugin_type: str) -> List[Dict[str, Any]]:
        return self.get_plugins_by_category(plugin_type)

    def get_plugins_by_status(self, status: str) -> List[Dict[str, Any]]:
        if not self.initialized or self.kernel is None:
            return []
        return [
            record
            for record in self.kernel.list_records()
            if str(record.get("status")) == status
        ]

    def get_available_plugins(self) -> List[Dict[str, Any]]:
        if not self.initialized or self.kernel is None:
            return []
        return [
            record
            for record in self.kernel.list_records()
            if str(record.get("status")) in _ENABLED_STATES
        ]

    def get_active_executions(self) -> List[PluginExecutionResult]:
        if not self.initialized or self.kernel is None:
            return []
        active_ids = set(self.kernel.active_executions())
        return [item for item in self._history if item.request_id in active_ids]

    def get_execution_history(self, limit: int = 100) -> List[PluginExecutionResult]:
        if limit <= 0:
            return []
        return list(self._history[-limit:])

    def get_plugin_runtime_stats(self, plugin_name: str) -> Dict[str, Any]:
        history = [
            item
            for item in self.get_execution_history(1000)
            if item.plugin_name == plugin_name
        ]
        successful = sum(
            item.status is ExecutionStatus.COMPLETED for item in history
        )
        last = next(
            (item.completed_at for item in reversed(history) if item.completed_at),
            None,
        )
        return {
            "execution_count": len(history),
            "success_rate": successful / len(history) if history else 0.0,
            "last_executed": last.isoformat() if last else None,
        }

    def _execution_metrics(self) -> Dict[str, Any]:
        completed = sum(
            item.status is ExecutionStatus.COMPLETED for item in self._history
        )
        failed = len(self._history) - completed
        total_time = sum(item.execution_time for item in self._history)
        return {
            "executions_total": len(self._history),
            "executions_successful": completed,
            "executions_failed": failed,
            "average_execution_time": (
                total_time / len(self._history) if self._history else 0.0
            ),
        }

    def get_service_stats(self) -> Dict[str, Any]:
        if not self.initialized or self.kernel is None:
            return {"initialized": False}
        return {
            "initialized": True,
            "registry_stats": self.kernel.registry_stats(),
            "execution_metrics": self._execution_metrics(),
            "active_executions": len(self.kernel.active_executions()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def get_metrics(self) -> Dict[str, Any]:
        await self._ensure_initialized()
        stats = self.get_service_stats()
        registry = stats["registry_stats"]
        execution = stats["execution_metrics"]
        status_counts = registry.get("by_status", {})
        history = self.get_execution_history(100)
        usage = Counter(item.plugin_name for item in history)
        return {
            "total_plugins": int(registry.get("total_plugins", 0) or 0),
            "enabled_plugins": sum(
                int(status_counts.get(state, 0) or 0)
                for state in _ENABLED_STATES
            ),
            "total_executions": int(execution.get("executions_total", 0) or 0),
            "successful_executions": int(
                execution.get("executions_successful", 0) or 0
            ),
            "failed_executions": int(
                execution.get("executions_failed", 0) or 0
            ),
            "average_execution_time": float(
                execution.get("average_execution_time", 0.0) or 0.0
            ),
            "plugins_by_category": dict(registry.get("by_category", {})),
            "most_used_plugins": [
                {"plugin_name": name, "execution_count": count}
                for name, count in usage.most_common(10)
            ],
            "recent_executions": [
                {
                    "request_id": item.request_id,
                    "plugin_name": item.plugin_name,
                    "status": item.status.value,
                    "execution_time": item.execution_time,
                    "completed_at": (
                        item.completed_at.isoformat() if item.completed_at else None
                    ),
                    "tenant_id": item.tenant_id or None,
                    "correlation_id": item.correlation_id or None,
                }
                for item in reversed(history[-10:])
            ],
        }

    async def health_check(self) -> Dict[str, Any]:
        await self._ensure_initialized()
        health: Dict[str, Any] = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {},
        }
        try:
            stats = self._get_kernel().registry_stats()
            health["components"]["registry"] = {
                "status": "healthy",
                "total_plugins": stats["total_plugins"],
                "enabled_plugins": sum(
                    int(stats["by_status"].get(state, 0) or 0)
                    for state in _ENABLED_STATES
                ),
            }
            health["components"]["execution_engine"] = {
                "status": "healthy",
                "authority": "ExtensionExecutionService",
                "active_executions": len(self._get_kernel().active_executions()),
                "total_executions": len(self._history),
            }
        except Exception:
            logger.exception("Plugin health check failed")
            health["status"] = "unhealthy"
            health["error_code"] = "plugin_health_check_failed"
        return health

    async def cleanup(self) -> None:
        if self.kernel is not None:
            await self.kernel.cleanup()
        self.initialized = False

    async def prepare_lifecycle_approval(
        self,
        *,
        context: "ChatExecutionContext",
        plugin_id: str,
        action: str,
    ) -> Dict[str, Any]:
        """Persist exact, revocable human consent request for one plugin.

        This is a host-only preparation step, not an execution grant. The
        installer, manifest SHA-256, terminal state and global revision come
        exclusively from the canonical kernel and PostgreSQL ledger. No
        request payload or chat turn can supply those facts.
        """
        from ai_karen_engine.auth.rbac_middleware import (
            Permission, get_rbac_manager,
        )
        from ai_karen_engine.core.runtime.chat_runtime_contract import (
            ChatExecutionContext, ChatExecutionRequest,
        )
        from ai_karen_engine.core.runtime.execution_decision import (
            ExecutionDecision, RiskLevel,
        )
        from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
            PluginLifecycleApprovalScope,
        )
        from ai_karen_engine.persistence.repositories.plugin_lifecycle_repository import (
            PluginLifecycleLedger, PluginLifecycleRevisionConflict,
        )
        from ai_karen_engine.services.approvals import get_approval_service

        if not isinstance(context, ChatExecutionContext):
            raise TypeError("Authenticated plugin lifecycle context required")
        principal = context.require_authenticated_user()
        if not get_rbac_manager().has_permission(
            principal, Permission.ADMIN_PLUGINS_MANAGE,
        ):
            raise PermissionError("Plugin lifecycle management permission required")
        if (
            not isinstance(plugin_id, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,49}", plugin_id)
            or not isinstance(action, str)
            or action not in {"enable", "disable"}
        ):
            raise ValueError("Unsupported plugin lifecycle approval request")
        if (
            not context.request_id
            or not context.correlation_id
            or not context.session_id
        ):
            raise ValueError("Lifecycle approval requires authenticated session and trace")
        # A canonical UUID conversation is required; the runtime context may
        # derive one from the trusted session when ingress has not assigned it.
        conversation = context.require_conversation_id()
        await self._ensure_initialized()
        observation = await self._get_kernel().observe_lifecycle_for_finalization(
            plugin_id, operation_id=str(uuid.uuid4()),
        )
        if observation.observed_state != (
            "disabled" if action == "enable" else "enabled"
        ):
            raise ValueError("Plugin lifecycle action is already satisfied")
        ledger = PluginLifecycleLedger()
        revision = await ledger.initialize_observation(
            installation_id=observation.installation_id,
            manifest_checksum=observation.manifest_checksum,
            observed_state=observation.observed_state,
        )
        if revision["disposition"] != "ready":
            raise PluginLifecycleRevisionConflict(
                "Plugin lifecycle remains unresolved from an earlier operation"
            )
        scope = PluginLifecycleApprovalScope(
            installation_id=observation.installation_id,
            action=action,
            manifest_checksum=observation.manifest_checksum,
            expected_state=observation.observed_state,
            expected_revision=revision["revision"],
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            session_id=context.session_id,
            conversation_id=conversation,
        )
        decision = await self._policy_enforcer.authorize_plugin_lifecycle_preflight(
            context=context,
            scope=scope,
            observed_state=observation.observed_state,
            manifest_checksum=observation.manifest_checksum,
            revision=revision["revision"],
            disposition=revision["disposition"],
        )
        if (
            not decision.allowed
            or not decision.requires_human_gate
            or decision.allowed_capabilities
            or decision.risk_level != "high"
        ):
            raise PermissionError("Plugin lifecycle consent preflight denied")
        # Reuse ApprovalService's canonical scope fingerprint, PostgreSQL
        # repository and audit. Empty chat messages are deliberate: this is
        # an authenticated admin action, not an invented user chat turn.
        approval = await get_approval_service().create_for_request(
            ChatExecutionRequest(messages=[], context=context),
            ExecutionDecision(
                intent="plugin.lifecycle." + action,
                risk_level=RiskLevel.HIGH,
                requires_human_gate=True,
                policy_decision_id=decision.decision_id,
                policy_version=decision.policy_version,
                policy_reason_codes=[reason.value for reason in decision.reason_codes],
                policy_constraints={"authorization_status": "allowed"},
            ),
            lifecycle_scope=scope,
        )
        if approval.get("status") != "pending":
            raise RuntimeError("Lifecycle approval was not durably recorded as pending")
        return {
            "status": "pending",
            "approval_id": approval["approval_id"],
            "plugin_id": scope.installation_id,
            "action": scope.action,
            "expected_state": scope.expected_state,
            "target_state": "enabled" if action == "enable" else "disabled",
            "expected_revision": scope.expected_revision,
            "manifest_checksum": scope.manifest_checksum,
            "expires_at": approval["expires_at"],
            "policy_decision_id": decision.decision_id,
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "execution_performed": False,
        }

    async def resume_lifecycle_approval(
        self,
        *,
        context: "ChatExecutionContext",
        plugin_id: str,
        action: str,
        approval_id: str,
    ) -> Dict[str, Any]:
        """Rebuild exact approved scope from tenant-scoped SQL, never HTTP.

        The authenticated admin ingress supplies only an approval UUID and
        action path. ApprovalService owns the durable consent. The existing
        execute_approved_lifecycle performs all fresh policy/RBAC checks,
        global revision CAS, physical fencing and verified terminalization.
        """
        from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
        from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
            PluginLifecycleApprovalScope,
        )
        from ai_karen_engine.services.approvals import (
            ApprovalScopeError, ApprovalStateError, get_approval_service,
        )

        if not isinstance(context, ChatExecutionContext):
            raise TypeError("Verified plugin lifecycle identity required")
        principal = context.require_authenticated_user()
        if (
            not isinstance(plugin_id, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,49}", plugin_id)
            or action not in {"enable", "disable"}
        ):
            raise ValueError("Invalid plugin lifecycle target")
        try:
            canonical_id = str(uuid.UUID(approval_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Invalid lifecycle approval identifier") from exc
        if canonical_id != approval_id:
            raise ValueError("Noncanonical lifecycle approval identifier")

        # Authenticated actor/tenant SQL read. A client cannot provide the
        # trusted immutable action/revision/manifest identity as a shortcut.
        approval = await get_approval_service().get(canonical_id, user=principal)
        if approval.get("status") != "approved":
            raise ApprovalStateError("Human lifecycle approval is not executable")
        saved = approval.get("request_payload")
        bound = saved.get("plugin_lifecycle_scope") if isinstance(saved, dict) else None
        if not isinstance(bound, dict):
            raise ApprovalScopeError("Lifecycle approval scope is unavailable")
        try:
            scope = PluginLifecycleApprovalScope(**bound)
        except (TypeError, ValueError) as exc:
            raise ApprovalScopeError("Persisted lifecycle approval scope is invalid") from exc
        if (
            scope.installation_id != plugin_id
            or scope.action != action
            or approval.get("intent") != "plugin.lifecycle." + action
        ):
            raise ApprovalScopeError("Lifecycle approval does not match the requested action")
        try:
            scope.require_matching_context(context)
        except PermissionError as exc:
            raise ApprovalScopeError("Lifecycle approval does not belong to this session") from exc
        return await self.execute_approved_lifecycle(
            context=context,
            scope=scope,
            approval_id=canonical_id,
        )

    async def execute_approved_lifecycle(
        self,
        *,
        context: "ChatExecutionContext",
        scope: "PluginLifecycleApprovalScope",
        approval_id: str,
    ) -> Dict[str, Any]:
        """Execute one approved general-plugin lifecycle action, host-only.

        This method is never exposed to generic chat or unapproved HTTP
        actions. The trusted bearer-session admin route reaches it only
        through resume_lifecycle_approval and its actor-scoped SQL receipt.
        RuntimePolicy authorizes the exact approved action, ActionExecutionGate admits it,
        and the existing ledger keeps the global physical fence until the
        kernel observation and terminal CAS are both committed.
        """
        from ai_karen_engine.audit_logging import (
            AuditEventType, AuditSeverity, get_audit_logger,
        )
        from ai_karen_engine.auth.rbac_middleware import (
            Permission, get_rbac_manager,
        )
        from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
        from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
            PluginLifecycleApprovalScope,
        )
        from ai_karen_engine.persistence.repositories.plugin_lifecycle_repository import (
            PluginLifecycleLedger,
        )
        from ai_karen_engine.services.approvals import get_approval_service

        if not isinstance(context, ChatExecutionContext):
            raise TypeError("Authenticated plugin lifecycle context required")
        if not isinstance(scope, PluginLifecycleApprovalScope):
            raise TypeError("Validated plugin lifecycle scope required")

        principal = context.require_authenticated_user()
        scope.require_matching_context(context)
        if not get_rbac_manager().has_permission(
            principal, Permission.ADMIN_PLUGINS_MANAGE
        ):
            raise PermissionError("Plugin lifecycle management permission required")
        if not context.request_id or not context.correlation_id:
            raise ValueError("Plugin lifecycle request and correlation IDs are required")

        # ApprovalService is the sole actor-scoped approval read authority.
        # The ledger independently proves its DB freshness and single use at
        # reservation; a UI-supplied approval object is not accepted here.
        approval = await get_approval_service().get(approval_id, user=principal)
        await self._ensure_initialized()
        kernel = self._get_kernel()
        initial = await kernel.observe_lifecycle_for_finalization(
            scope.installation_id, operation_id=str(uuid.uuid4()),
        )
        ledger = PluginLifecycleLedger()
        durable = await ledger.initialize_observation(
            installation_id=scope.installation_id,
            manifest_checksum=initial.manifest_checksum,
            observed_state=initial.observed_state,
        )
        decision = await self._policy_enforcer.authorize_approved_plugin_lifecycle(
            context=context,
            scope=scope,
            approval=approval,
            observed_state=initial.observed_state,
            manifest_checksum=initial.manifest_checksum,
            revision=durable["revision"],
            disposition=durable["disposition"],
        )
        action = "plugin.lifecycle." + scope.action
        plan = decision.to_authorized_plan()
        if (
            not decision.allowed
            or not decision.requires_human_gate
            or not plan.matches_execution_scope(
                user_id=scope.user_id,
                tenant_id=scope.tenant_id,
                session_id=scope.session_id,
                policy_decision_id=decision.decision_id,
            )
            or not await ActionExecutionGate.authorize(plan, action)
        ):
            raise PermissionError("Current lifecycle policy denied execution")

        operation_id: Optional[str] = None
        stage = "approved"
        metadata: Dict[str, Any] = {
            "plugin_id": scope.installation_id,
            "action": scope.action,
            "tenant_id": scope.tenant_id,
            "user_id": scope.user_id,
            "session_id": scope.session_id,
            "conversation_id": scope.conversation_id,
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "policy_decision_id": decision.decision_id,
            "approval_id": approval_id,
            "manifest_checksum": scope.manifest_checksum,
            "expected_revision": scope.expected_revision,
        }

        def audit(outcome: str, error_type: Optional[str] = None) -> None:
            try:
                get_audit_logger().log_audit_event(
                    {
                        "event_type": AuditEventType.SECURITY_EVENT,
                        "severity": (
                            AuditSeverity.INFO if outcome == "verified_committed"
                            else AuditSeverity.WARNING
                        ),
                        "message": "plugin_lifecycle_" + outcome,
                        "user_id": scope.user_id,
                        "tenant_id": scope.tenant_id,
                        "session_id": scope.session_id,
                        "correlation_id": context.correlation_id,
                        "metadata": {
                            **metadata,
                            "operation_id": operation_id,
                            "stage": stage,
                            "error_type": error_type,
                        },
                    }
                )
            except Exception:
                logger.exception(
                    "plugin.lifecycle.audit_unavailable",
                    extra={"operation_id": operation_id, "correlation_id": context.correlation_id},
                )

        try:
            claim = await ledger.reserve_approved(
                approval_id=approval_id,
                scope=scope,
                request_id=context.request_id,
                correlation_id=context.correlation_id,
            )
            operation_id = claim["operation_id"]
            stage = "reserved"
            async with ledger.hold_prepared_execution(
                scope=scope, operation_id=operation_id,
            ):
                stage = "in_flight"
                # Recheck the verified principal and canonical permission at
                # physical admission. The prepared DB approval is single use.
                if (
                    context.require_authenticated_user() is not principal
                    or not get_rbac_manager().has_permission(
                        principal, Permission.ADMIN_PLUGINS_MANAGE
                    )
                ):
                    raise PermissionError("Lifecycle permission revoked before mutation")
                observation = await kernel.transition_prepared_lifecycle(
                    scope, operation_id=operation_id,
                )
                stage = "observed"
                receipt = await ledger.complete_verified(
                    operation_id=operation_id,
                    tenant_id=scope.tenant_id,
                    actor_user_id=scope.user_id,
                    observation=observation,
                )
                stage = "verified_committed"
            audit("verified_committed")
            return {
                **receipt,
                "policy_decision_id": decision.decision_id,
                "original_policy_decision_id": approval["policy_decision_id"],
                "correlation_id": context.correlation_id,
                "request_id": context.request_id,
                "execution_authority": "plugin_service",
            }
        except BaseException as exc:
            if operation_id is not None:
                # Unknown is permanent and unretryable. Best-effort freeze is
                # shielded from repeated coroutine cancellation; the durable
                # in_flight or prepared row already keeps the global revision
                # unresolved if PostgreSQL itself becomes unavailable.
                freeze = asyncio.create_task(
                    ledger.mark_unknown(
                        operation_id=operation_id,
                        tenant_id=scope.tenant_id,
                        actor_user_id=scope.user_id,
                    )
                )
                while not freeze.done():
                    try:
                        await asyncio.shield(freeze)
                    except asyncio.CancelledError:
                        if freeze.done():
                            break
                    except Exception:
                        # The attempted freeze can fail when PostgreSQL is
                        # unavailable. Preserve the original execution error.
                        break
                try:
                    await freeze
                except Exception:
                    logger.exception(
                        "plugin.lifecycle.unknown_persistence_unavailable",
                        extra={**metadata, "operation_id": operation_id},
                    )
            audit("unresolved", type(exc).__name__)
            raise

    async def disable_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        return await self._get_kernel().disable(plugin_name)

    async def enable_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        return await self._get_kernel().enable(plugin_name)


_plugin_service: Optional[PluginService] = None


def get_plugin_service() -> PluginService:
    global _plugin_service
    if _plugin_service is None:
        _plugin_service = PluginService(_CANONICAL_PLUGIN_ROOT, _CANONICAL_PLUGIN_ROOT)
    return _plugin_service


async def initialize_plugin_service(
    marketplace_path: Optional[Path] = None,
    core_plugins_path: Optional[Path] = None,
    auto_discover: bool = True,
) -> PluginService:
    global _plugin_service
    root = core_plugins_path or marketplace_path or _CANONICAL_PLUGIN_ROOT
    _plugin_service = PluginService(root, root)
    await _plugin_service.initialize(auto_discover)
    return _plugin_service


async def discover_and_register_all_plugins() -> Dict[str, bool]:
    service = get_plugin_service()
    await service.discover_plugins(force_refresh=True)
    return await service.validate_and_register_all_discovered()


async def execute_plugin_simple(
    plugin_name: str,
    parameters: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 30,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> PluginExecutionResult:
    return await get_plugin_service().execute_plugin(
        plugin_name,
        parameters=parameters or {},
        timeout_seconds=timeout_seconds,
        user_id=user_id,
        tenant_id=tenant_id,
    )


async def get_plugin_marketplace_info() -> Dict[str, Any]:
    """Compatibility name returning local catalog truth, never remote-market data."""
    service = get_plugin_service()
    await service._ensure_initialized()
    stats = service.get_service_stats()["registry_stats"]
    catalog = []
    for plugin in service.get_available_plugins():
        manifest = plugin.get("manifest")
        if manifest is None:
            continue
        catalog.append(
            {
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "category": manifest.category,
                "type": manifest.category,
                "author": manifest.author,
            }
        )
    return {
        "total_plugins": stats.get("total_plugins", 0),
        "by_category": stats.get("by_category", {}),
        "by_type": stats.get("by_type", {}),
        "by_status": stats.get("by_status", {}),
        "available_plugins": catalog,
    }


__all__ = [
    "ExecutionMode",
    "ExecutionStatus",
    "PluginExecutionResult",
    "PluginService",
    "get_plugin_service",
    "initialize_plugin_service",
    "discover_and_register_all_plugins",
    "execute_plugin_simple",
    "get_plugin_marketplace_info",
]
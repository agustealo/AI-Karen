"""Authenticated runtime bridge for the canonical File Explorer inventory.

This is host orchestration, not a new file store or plugin execution path.
Only the trusted runtime can construct it with a repository adapter and kernel.
No HTTP route or client-side caller is registered by this module.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from typing import Any, Protocol

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.contracts import (
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
)

logger = logging.getLogger(__name__)
PLUGIN_ID = "file-explorer"
MAX_PAGE_SIZE = 200
MAX_CURSOR_LENGTH = 768
_RESERVED_SCOPE = frozenset({"file_explorer_grant", "file_explorer_entries"})


class OwnerInventorySource(Protocol):
    async def list_owner_sources_page(
        self, *, tenant_id: str, user_id: str, limit: int, cursor: str | None
    ) -> dict[str, Any]: ...

    async def list_owner_hierarchy(
        self, *, tenant_id: str, user_id: str, limit: int,
        parent_folder_id: str | None, after_folder_id: str | None,
        file_cursor: str | None = None,
    ) -> dict[str, Any]: ...

    async def create_owner_folder(
        self, *, tenant_id: str, user_id: str, name: str,
        parent_folder_id: str | None,
    ) -> dict[str, Any]: ...

    async def rename_owner_folder(
        self, *, tenant_id: str, user_id: str, folder_id: str,
        name: str, expected_revision: int,
    ) -> dict[str, Any]: ...

    async def move_owner_item(
        self, *, tenant_id: str, user_id: str, kind: str, source_id: str,
        destination_id: str | None, expected_revision: int,
    ) -> str: ...

    async def delete_empty_owner_folder(
        self, *, tenant_id: str, user_id: str, folder_id: str,
        expected_revision: int,
    ) -> bool: ...

    async def revalidate_owner_reference(
        self, *, tenant_id: str, user_id: str, source_id: str,
        expected_revision: str,
    ) -> dict[str, Any]: ...


class GovernedPluginKernel(Protocol):
    def get_record(self, plugin_id: str) -> dict[str, Any] | None: ...
    async def execute(self, request: ExtensionExecutionRequest) -> Any: ...


def _canonical_uuid(value: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
        return parsed.version is not None and str(parsed) == value
    except (ValueError, TypeError, AttributeError):
        return False


class FileExplorerInventoryHost:
    """Build one source page only after canonical authorization and kernel gating.

    The service receives its dependencies from trusted runtime composition.
    Callers must not construct the context or plan from request JSON.
    """

    def __init__(
        self, *, kernel: GovernedPluginKernel, source: OwnerInventorySource
    ) -> None:
        self._kernel = kernel
        self._source = source

    def _authorize_owner(
        self, *, context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
    ) -> None:
        if not isinstance(context, ExtensionExecutionContext):
            raise PermissionError("file_explorer_context_required")
        if (
            not _canonical_uuid(context.tenant_id)
            or not _canonical_uuid(context.user_id)
            or not isinstance(plan, AuthorizedExecutionPlan)
            or not context.policy_decision_id
            or not plan.matches_execution_scope(
                user_id=context.user_id,
                tenant_id=context.tenant_id,
                session_id=context.session_id,
                policy_decision_id=context.policy_decision_id,
            )
            or PLUGIN_ID not in plan.allowed_plugins
            or PLUGIN_ID not in context.allowed_capabilities
        ):
            raise PermissionError("file_explorer_authorization_required")
        if not isinstance(context.resource_scope, dict) or any(
            key in context.resource_scope for key in _RESERVED_SCOPE
        ):
            raise PermissionError("file_explorer_untrusted_inventory")
        # Deny before any repository access when extension is inactive.
        record = self._kernel.get_record(PLUGIN_ID)
        if (
            not isinstance(record, dict)
            or record.get("status") != "enabled"
            or record.get("dependencies_resolved") is not True
        ):
            raise PermissionError("file_explorer_disabled")


    async def _admit_kernel_before_read(
        self, *, context: ExtensionExecutionContext,
        plan: AuthorizedExecutionPlan,
    ) -> None:
        # Kernel admission must precede every owner metadata read.
        # An empty host-issued list has no source contents but triggers the same
        # lifecycle, role, action and permission checks as inventory listing.
        admission_context = replace(
            context,
            resource_scope={
                **context.resource_scope,
                "file_explorer_grant": "host_verified",
                "file_explorer_entries": [],
            },
        )
        admission = await self._kernel.execute(ExtensionExecutionRequest(
            plugin_id=PLUGIN_ID,
            capability="execute",
            payload={"operation": "list"},
            context=admission_context,
            authorized_plan=plan,
        ))
        if (
            getattr(admission, "status", None) != "success"
            or not isinstance(getattr(admission, "payload", None), dict)
            or admission.payload.get("operation") != "list"
            or admission.payload.get("items") != []
        ):
            raise PermissionError("file_explorer_kernel_denied")

    async def list_owner_hierarchy(
        self, *, context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
        limit: int, parent_folder_id: str | None, after_folder_id: str | None,
        file_cursor: str | None = None,
    ) -> dict[str, Any]:
        self._authorize_owner(context=context, plan=plan)
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError("file_explorer_page_limit_invalid")
        if any(value is not None and not _canonical_uuid(value)
               for value in (parent_folder_id, after_folder_id)):
            raise ValueError("file_explorer_folder_id_invalid")
        if file_cursor is not None and (
            not isinstance(file_cursor, str) or not 1 <= len(file_cursor) <= MAX_CURSOR_LENGTH
        ):
            raise ValueError("file_explorer_cursor_invalid")
        await self._admit_kernel_before_read(context=context, plan=plan)
        page = await self._source.list_owner_hierarchy(
            tenant_id=context.tenant_id, user_id=context.user_id, limit=limit,
            parent_folder_id=parent_folder_id, after_folder_id=after_folder_id,
            file_cursor=file_cursor,
        )
        logger.info("file_explorer_hierarchy_page", extra={
            "request_id": context.request_id, "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id, "user_id": context.user_id,
            "available": page["available"], "folder_count": len(page["folders"]),
        })
        return {**page, "request_id": context.request_id,
                "correlation_id": context.correlation_id}

    def _authorize_mutation(
        self, *, context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
        scope: dict[str, Any],
    ) -> None:
        self._authorize_owner(context=context, plan=plan)
        from ai_karen_engine.auth.rbac_middleware import (
            FILE_EXPLORER_MUTATION_PERMISSIONS, Permission,
        )

        entitlement = FILE_EXPLORER_MUTATION_PERMISSIONS.get(scope["operation"])
        if entitlement is None:
            raise PermissionError("file_explorer_operation_denied")
        permissions = {Permission.DATA_READ.value, entitlement.value}
        required = permissions | {scope["operation"]}
        if (not required.issubset(plan.allowed_capabilities)
            or not required.issubset(context.allowed_capabilities)
            or plan.approval_requirements
            or plan.resource_scope != scope
            or not permissions.issubset(context.audit_context.get("permissions", []))):
            raise PermissionError("file_explorer_write_permission_required")

    @staticmethod
    def _validate_folder_name(name: str) -> None:
        if (not isinstance(name, str) or not 1 <= len(name) <= 256
            or name != name.strip()
            or any(ord(ch) < 32 or 127 <= ord(ch) <= 159
                   or 0xD800 <= ord(ch) <= 0xDFFF for ch in name)):
            raise ValueError("file_explorer_folder_invalid")

    async def create_owner_folder(
        self, *, context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
        name: str, parent_folder_id: str | None,
    ) -> dict[str, Any]:
        self._authorize_mutation(context=context, plan=plan, scope={
            "operation": "file_explorer.folder.create",
            "name": name, "parent_folder_id": parent_folder_id,
        })
        self._validate_folder_name(name)
        if parent_folder_id is not None and not _canonical_uuid(parent_folder_id):
            raise ValueError("file_explorer_folder_invalid")
        # Kernel admission verifies lifecycle and role; the host, not the
        # read-only extension, performs the narrowly policy-bound mutation.
        await self._admit_kernel_before_read(context=context, plan=plan)
        try:
            folder = await self._source.create_owner_folder(
                tenant_id=context.tenant_id, user_id=context.user_id,
                name=name, parent_folder_id=parent_folder_id,
            )
        except Exception:
            logger.warning("file_explorer_folder_create_failed", extra={
                "request_id": context.request_id, "correlation_id": context.correlation_id,
                "tenant_id": context.tenant_id, "user_id": context.user_id,
            })
            raise
        logger.info("file_explorer_folder_created", extra={
            "request_id": context.request_id, "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id, "user_id": context.user_id,
            "policy_decision_id": context.policy_decision_id,
            "folder_id": folder["folder_id"], "status": "success",
        })
        return {"folder": folder, "request_id": context.request_id,
                "correlation_id": context.correlation_id}

    async def rename_owner_folder(
        self, *, context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
        folder_id: str, name: str, expected_revision: int,
    ) -> dict[str, Any]:
        self._authorize_mutation(context=context, plan=plan, scope={
            "operation": "file_explorer.folder.rename", "folder_id": folder_id,
            "name": name, "expected_revision": expected_revision,
        })
        self._validate_folder_name(name)
        if (not _canonical_uuid(folder_id) or type(expected_revision) is not int
            or not 1 <= expected_revision <= 9223372036854775806):
            raise ValueError("file_explorer_folder_invalid")
        await self._admit_kernel_before_read(context=context, plan=plan)
        try:
            folder = await self._source.rename_owner_folder(
                tenant_id=context.tenant_id, user_id=context.user_id,
                folder_id=folder_id, name=name, expected_revision=expected_revision,
            )
        except Exception:
            logger.warning("file_explorer_folder_rename_failed", extra={
                "request_id": context.request_id, "correlation_id": context.correlation_id,
                "tenant_id": context.tenant_id, "user_id": context.user_id,
            })
            raise
        logger.info("file_explorer_folder_renamed", extra={
            "request_id": context.request_id, "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id, "user_id": context.user_id,
            "policy_decision_id": context.policy_decision_id,
            "folder_id": folder_id, "status": "success",
        })
        return {"folder": folder, "request_id": context.request_id,
                "correlation_id": context.correlation_id}

    async def move_owner_item(
        self, *, context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
        kind: str, source_id: str, destination_id: str | None,
        expected_revision: int,
    ) -> dict[str, Any]:
        if kind not in ("folder", "artifact"):
            raise ValueError("file_explorer_move_kind_invalid")
        operation = f"file_explorer.{kind}.move"
        self._authorize_mutation(context=context, plan=plan, scope={
            "operation": operation, "source_id": source_id,
            "destination_id": destination_id, "expected_revision": expected_revision,
        })
        if (not _canonical_uuid(source_id)
            or (destination_id is not None and not _canonical_uuid(destination_id))
            or (kind == "folder" and destination_id == source_id)
            or type(expected_revision) is not int
            or not 1 <= expected_revision <= 9223372036854775806):
            raise ValueError("file_explorer_move_invalid")
        await self._admit_kernel_before_read(context=context, plan=plan)
        evidence = {
            "request_id": context.request_id, "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id, "user_id": context.user_id,
            "policy_decision_id": context.policy_decision_id,
            "operation": operation, "source_id": source_id,
            "destination_id": destination_id,
        }
        try:
            revision = await self._source.move_owner_item(
                tenant_id=context.tenant_id, user_id=context.user_id,
                kind=kind, source_id=source_id, destination_id=destination_id,
                expected_revision=expected_revision,
            )
        except Exception:
            logger.warning("file_explorer_move_failed", extra=evidence)
            raise
        logger.info("file_explorer_move_committed", extra={
            **evidence, "organization_revision": revision, "status": "success",
        })
        return {"kind": kind, "source_id": source_id, "parent_folder_id": destination_id,
                "organization_revision": revision, "request_id": context.request_id,
                "correlation_id": context.correlation_id}

    async def delete_empty_owner_folder(
        self, *, context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
        folder_id: str, expected_revision: int,
    ) -> dict[str, Any]:
        self._authorize_mutation(context=context, plan=plan, scope={
            "operation": "file_explorer.folder.delete", "folder_id": folder_id,
            "expected_revision": expected_revision,
        })
        if (not _canonical_uuid(folder_id) or type(expected_revision) is not int
            or not 1 <= expected_revision <= 9223372036854775806):
            raise ValueError("file_explorer_folder_delete_invalid")
        await self._admit_kernel_before_read(context=context, plan=plan)
        evidence = {
            "request_id": context.request_id, "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id, "user_id": context.user_id,
            "policy_decision_id": context.policy_decision_id, "folder_id": folder_id,
            "expected_revision": expected_revision,
        }
        try:
            deleted = await self._source.delete_empty_owner_folder(
                tenant_id=context.tenant_id, user_id=context.user_id,
                folder_id=folder_id, expected_revision=expected_revision,
            )
            if deleted is not True:
                raise RuntimeError("file_explorer_folder_delete_unconfirmed")
        except Exception:
            logger.warning("file_explorer_folder_delete_failed", extra=evidence)
            raise
        logger.info("file_explorer_folder_deleted", extra={**evidence, "status": "success"})
        return {"folder_id": folder_id, "deleted": True,
                "request_id": context.request_id, "correlation_id": context.correlation_id}

    async def revalidate_owner_selection(
        self, *, context: ExtensionExecutionContext,
        plan: AuthorizedExecutionPlan, source_id: str, expected_revision: str,
    ) -> dict[str, Any]:
        """Recheck selected metadata without granting access to source bytes."""
        self._authorize_owner(context=context, plan=plan)
        if not _canonical_uuid(source_id):
            raise PermissionError("file_explorer_source_id_invalid")
        if (
            not isinstance(expected_revision, str)
            or len(expected_revision) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in expected_revision)
        ):
            raise PermissionError("file_explorer_revision_invalid")
        await self._admit_kernel_before_read(context=context, plan=plan)
        evidence = await self._source.revalidate_owner_reference(
            tenant_id=context.tenant_id, user_id=context.user_id,
            source_id=source_id, expected_revision=expected_revision,
        )
        if (
            not isinstance(evidence, dict)
            or evidence.get("source_id") != source_id
            or evidence.get("revision") != expected_revision.lower()
            or evidence.get("owner_scope_verified") is not True
            or evidence.get("access_semantics")
            != "owner_only_at_lookup_time_not_transferable_grant"
        ):
            raise PermissionError("file_explorer_revalidation_invalid")
        logger.info("file_explorer_reference_revalidated", extra={
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "source_id": source_id,
            "status": "success",
        })
        return {
            "source_id": source_id,
            "revision": expected_revision.lower(),
            "owner_scope_verified": True,
            "access_semantics": "owner_only_at_lookup_time_not_transferable_grant",
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
        }

    async def list_owner_page(
        self,
        *,
        context: ExtensionExecutionContext,
        plan: AuthorizedExecutionPlan,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._authorize_owner(context=context, plan=plan)
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError("file_explorer_page_limit_invalid")
        if cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= MAX_CURSOR_LENGTH):
            raise ValueError("file_explorer_cursor_invalid")

        await self._admit_kernel_before_read(context=context, plan=plan)

        page = await self._source.list_owner_sources_page(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            limit=limit,
            cursor=cursor,
        )
        if not isinstance(page, dict):
            raise RuntimeError("file_explorer_source_page_invalid")
        items = page.get("items")
        has_more = page.get("has_more")
        next_cursor = page.get("next_cursor")
        if (
            not isinstance(items, list)
            or len(items) > limit
            or type(has_more) is not bool
            or (
                has_more
                and (
                    not items
                    or not isinstance(next_cursor, str)
                    or not 1 <= len(next_cursor) <= MAX_CURSOR_LENGTH
                )
            )
            or (not has_more and next_cursor is not None)
        ):
            raise RuntimeError("file_explorer_source_page_invalid")

        # The kernel rechecks the plan, RBAC, lifecycle and execution policy.
        # This scope is created inside the trusted host, never by an API input.
        host_context = replace(
            context,
            resource_scope={
                **context.resource_scope,
                "file_explorer_grant": "host_verified",
                "file_explorer_entries": items,
            },
        )
        outcome = await self._kernel.execute(
            ExtensionExecutionRequest(
                plugin_id=PLUGIN_ID,
                capability="execute",
                payload={"operation": "list"},
                context=host_context,
                authorized_plan=plan,
            )
        )
        if getattr(outcome, "status", None) != "success":
            raise PermissionError("file_explorer_kernel_denied")
        projected = getattr(outcome, "payload", None)
        if (
            not isinstance(projected, dict)
            or projected.get("operation") != "list"
            or not isinstance(projected.get("items"), list)
            or len(projected["items"]) != len(items)
            or any(not isinstance(item, dict) for item in projected["items"])
            or sorted(projected["items"], key=lambda item: item["source_id"])
            != sorted(items, key=lambda item: item["source_id"])
        ):
            raise RuntimeError("file_explorer_kernel_projection_invalid")
        logger.info(
            "file_explorer_inventory_page",
            extra={
                "request_id": context.request_id,
                "correlation_id": context.correlation_id,
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "policy_decision_id": context.policy_decision_id,
                "item_count": len(items),
                "has_more": has_more,
                "status": "success",
            },
        )
        return {
            "items": projected["items"],
            "has_more": has_more,
            "next_cursor": next_cursor,
            "inventory_semantics": "owner_metadata_page_not_live_acl",
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
        }

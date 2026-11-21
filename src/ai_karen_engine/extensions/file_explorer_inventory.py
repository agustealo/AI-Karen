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
_RESERVED_SCOPE = frozenset({"file_explorer_grant", "file_explorer_entries"})


class OwnerInventorySource(Protocol):
    async def list_owner_sources_page(
        self, *, tenant_id: str, user_id: str, limit: int, cursor: str | None
    ) -> dict[str, Any]: ...

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
        # Run the full canonical execution gate before touching source metadata.
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
            or getattr(admission, "payload", None) is None
            or admission.payload.get("operation") != "list"
            or admission.payload.get("items") != []
        ):
            raise PermissionError("file_explorer_kernel_denied")
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
        if cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 768):
            raise ValueError("file_explorer_cursor_invalid")

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
            or (has_more and (not items or not isinstance(next_cursor, str) or not next_cursor))
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

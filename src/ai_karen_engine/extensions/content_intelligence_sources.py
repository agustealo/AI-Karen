"""Admit canonical owner-active inert text to Content Intelligence.

Host-only composition. RuntimePolicy and the extension kernel remain authoritative.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, Protocol

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.contracts import (
    ExtensionExecutionContext, ExtensionExecutionRequest,
)

logger = logging.getLogger(__name__)
PLUGIN = "content-intelligence"


class TextStore(Protocol):
    async def read_owner_active_code(
        self, artifact_id: str, tenant_id: str, user_id: str,
    ) -> Any: ...


class Kernel(Protocol):
    def get_record(self, plugin_id: str) -> dict[str, Any] | None: ...
    async def execute(self, request: ExtensionExecutionRequest) -> Any: ...


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (TypeError, ValueError, AttributeError):
        return False


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


class ContentSourceHost:
    """Bridge a trusted authorized plan to the existing owner-text repository."""

    def __init__(self, *, store: TextStore, kernel: Kernel) -> None:
        self._store = store
        self._kernel = kernel

    async def execute_owner_text(
        self, *, context: ExtensionExecutionContext,
        plan: AuthorizedExecutionPlan, operation: str,
        references: list[dict[str, str]], query: str | None = None,
        left_id: str | None = None, right_id: str | None = None,
    ) -> dict[str, Any]:
        if (
            not isinstance(context, ExtensionExecutionContext)
            or not isinstance(plan, AuthorizedExecutionPlan)
            or not _uuid(context.tenant_id) or not _uuid(context.user_id)
            or not context.policy_decision_id
            or not plan.matches_execution_scope(
                user_id=context.user_id, tenant_id=context.tenant_id,
                session_id=context.session_id,
                policy_decision_id=context.policy_decision_id,
            )
            or PLUGIN not in plan.allowed_plugins
            or PLUGIN not in plan.allowed_capabilities
            or "data:read" not in plan.allowed_capabilities
            or PLUGIN not in context.allowed_capabilities
            or "data:read" not in context.allowed_capabilities
            or context.resource_scope != {}
        ):
            raise PermissionError("content_source_authorization_required")
        if operation not in {"analyze", "search", "compare"}:
            raise ValueError("content_source_operation_invalid")
        if not isinstance(references, list) or not 1 <= len(references) <= 12:
            raise ValueError("content_source_count_invalid")
        ids: set[str] = set()
        for ref in references:
            if (
                not isinstance(ref, dict)
                or set(ref) != {"source_id", "revision"}
                or not _uuid(ref["source_id"])
                or not _sha(ref["revision"])
                or ref["source_id"] in ids
            ):
                raise PermissionError("content_source_reference_invalid")
            ids.add(ref["source_id"])
        if operation == "search":
            if not isinstance(query, str) or not 1 <= len(query.strip()) <= 512:
                raise ValueError("content_source_query_invalid")
        elif query is not None:
            raise ValueError("content_source_unused_query")
        if operation == "compare":
            if left_id not in ids or right_id not in ids or left_id == right_id:
                raise ValueError("content_source_comparison_invalid")
        elif left_id is not None or right_id is not None:
            raise ValueError("content_source_unused_selection")

        record = self._kernel.get_record(PLUGIN)
        if (
            not isinstance(record, dict)
            or record.get("status") != "enabled"
            or record.get("dependencies_resolved") is not True
        ):
            raise PermissionError("content_source_plugin_disabled")
        # The kernel owns RBAC, lifecycle, permission and action admission.
        # Probe with the already-validated, non-content source identifier.
        # Its result is discarded and never presented as document analysis.
        admission = await self._kernel.execute(ExtensionExecutionRequest(
            plugin_id=PLUGIN,
            capability="execute",
            payload={
                "operation": "analyze",
                "documents": [{
                    "id": references[0]["source_id"],
                    "name": "source-reference",
                    "text": references[0]["source_id"],
                }],
            },
            context=context,
            authorized_plan=plan,
        ))
        admission_payload = getattr(admission, "payload", None)
        if (
            getattr(admission, "status", None) != "success"
            or not isinstance(admission_payload, dict)
            or admission_payload.get("operation") != "analyze"
        ):
            raise PermissionError("content_source_kernel_admission_denied")
        documents: list[dict[str, str]] = []
        total_chars = 0
        for ref in references:
            response = await self._store.read_owner_active_code(
                ref["source_id"], context.tenant_id, context.user_id,
            )
            if not getattr(response, "success", False):
                raise PermissionError("content_source_unavailable")
            artifact = getattr(response, "data", None)
            if (
                artifact is None
                or getattr(artifact, "artifact_id", None) != ref["source_id"]
                or getattr(artifact, "tenant_id", None) != context.tenant_id
                or getattr(artifact, "user_id", None) != context.user_id
                or getattr(artifact, "sha256", None) != ref["revision"]
                or not isinstance(getattr(artifact, "filename", None), str)
                or not 1 <= len(artifact.filename) <= 256
                or not isinstance(getattr(artifact, "text", None), str)
                or not 1 <= len(artifact.text) <= 100_000
                or hashlib.sha256(artifact.text.encode("utf-8")).hexdigest()
                != ref["revision"]
            ):
                raise PermissionError("content_source_evidence_invalid")
            total_chars += len(artifact.text)
            if total_chars > 300_000:
                raise ValueError("content_source_budget_exceeded")
            documents.append({
                "id": ref["source_id"], "name": artifact.filename,
                "text": artifact.text,
            })
        payload: dict[str, Any] = {"operation": operation, "documents": documents}
        if operation == "search":
            payload["query"] = query
        if operation == "compare":
            payload.update({"left_id": left_id, "right_id": right_id})
        result = await self._kernel.execute(ExtensionExecutionRequest(
            plugin_id=PLUGIN, capability="execute", payload=payload,
            context=context, authorized_plan=plan,
        ))
        if getattr(result, "status", None) != "success":
            raise PermissionError("content_source_execution_denied")
        output = getattr(result, "payload", None)
        if not isinstance(output, dict) or output.get("operation") != operation:
            raise RuntimeError("content_source_output_invalid")
        logger.info("content_source_execution_completed", extra={
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id, "user_id": context.user_id,
            "source_count": len(references), "operation": operation,
            "status": "success",
        })
        return output

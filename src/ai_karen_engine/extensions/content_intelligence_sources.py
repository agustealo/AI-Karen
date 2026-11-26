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
# Fixed protocol ceiling, shared by ingress, execution and inventory metadata.
MAX_CONTENT_SOURCE_REFERENCES = 12


class TextStore(Protocol):
    async def read_owner_active_code(
        self, artifact_id: str, tenant_id: str, user_id: str,
    ) -> Any: ...


class Kernel(Protocol):
    def get_record(self, plugin_id: str) -> dict[str, Any] | None: ...
    async def execute(self, request: ExtensionExecutionRequest) -> Any: ...
    async def admit(self, request: ExtensionExecutionRequest) -> Any: ...


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

    @staticmethod
    async def admit_owner_access(
        *, kernel: Kernel, context: ExtensionExecutionContext,
        plan: AuthorizedExecutionPlan,
    ) -> None:
        """Check scoped runtime and kernel admission before any source read."""
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
        record = kernel.get_record(PLUGIN)
        if (
            not isinstance(record, dict)
            or record.get("status") != "enabled"
            or record.get("dependencies_resolved") is not True
        ):
            raise PermissionError("content_source_plugin_disabled")
        # Admission uses the SAME executor gates but runs no plugin handler.
        # Actual operation input schema is checked on final execution.
        admission = await kernel.admit(ExtensionExecutionRequest(
            plugin_id=PLUGIN,
            capability="execute",
            payload={},
            context=context,
            authorized_plan=plan,
        ))
        if getattr(admission, "status", None) != "admitted":
            raise PermissionError("content_source_kernel_admission_denied")

    async def execute_owner_text(
        self, *, context: ExtensionExecutionContext,
        plan: AuthorizedExecutionPlan, operation: str,
        references: list[dict[str, str]], query: str | None = None,
        left_id: str | None = None, right_id: str | None = None,
    ) -> dict[str, Any]:
        if operation not in {"analyze", "search", "compare"}:
            raise ValueError("content_source_operation_invalid")
        if not isinstance(references, list) or not 1 <= len(references) <= MAX_CONTENT_SOURCE_REFERENCES:
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

        await self.admit_owner_access(kernel=self._kernel, context=context, plan=plan)
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
        # Freeze authorization evidence before invoking the mutable plugin
        # kernel. A handler may replace its input document fields in place;
        # that must never redefine which source/revision was authorized.
        authorized = {
            document["id"]: {
                "name": document["name"],
                "sha256": hashlib.sha256(document["text"].encode("utf-8")).hexdigest(),
                "characters": len(document["text"]),
                "text": document["text"],
            }
            for document in documents
        }
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
        if (
            not isinstance(output, dict)
            or output.get("operation") != operation
            or output.get("persisted") is not False
        ):
            raise RuntimeError("content_source_output_invalid")

        # Kernel status is not source-lineage evidence. Check the returned
        # reference identities against the bytes already authorized and read.
        # No output may add, substitute or re-label an owner source.
        if operation == "analyze":
            analyzed = output.get("documents")
            if not isinstance(analyzed, list) or len(analyzed) != len(authorized):
                raise RuntimeError("content_source_output_invalid")
            returned_ids: set[str] = set()
            for item in analyzed:
                if not isinstance(item, dict):
                    raise RuntimeError("content_source_output_invalid")
                identifier = item.get("id")
                original = authorized.get(identifier) if isinstance(identifier, str) else None
                if (
                    original is None or identifier in returned_ids
                    or item.get("name") != original["name"]
                    # Owner-text admission never authorizes a folder. The
                    # canonical engine emits null; non-null labels are forged.
                    or item.get("folder_id") is not None
                    or item.get("sha256") != original["sha256"]
                    or type(item.get("characters")) is not int
                    or item["characters"] != original["characters"]
                    or not isinstance(item.get("top_terms"), list)
                    or len(item["top_terms"]) > 12
                    or any(
                        not isinstance(term, dict)
                        or not isinstance(term.get("term"), str)
                        or not term["term"]
                        or type(term.get("count")) is not int
                        or term["count"] < 1
                        for term in item["top_terms"]
                    )
                ):
                    raise RuntimeError("content_source_output_invalid")
                returned_ids.add(identifier)
            # The analysis engine may return document-pair relationships.
            # Validate every embedded source reference against the same
            # pre-kernel authorized snapshot used for document receipts.
            relationships = output.get("relationships", [])
            if not isinstance(relationships, list) or len(relationships) > 66:
                raise RuntimeError("content_source_output_invalid")
            for relationship in relationships:
                if (
                    not isinstance(relationship, dict)
                    or not isinstance(relationship.get("left_id"), str)
                    or not isinstance(relationship.get("right_id"), str)
                    or relationship["left_id"] not in authorized
                    or relationship["right_id"] not in authorized
                    or relationship["left_id"] == relationship["right_id"]
                ):
                    raise RuntimeError("content_source_output_invalid")
        elif operation == "compare":
            if (
                output.get("left_id") != left_id
                or output.get("right_id") != right_id
                or output.get("left_sha256") != authorized[left_id]["sha256"]
                or output.get("right_sha256") != authorized[right_id]["sha256"]
            ):
                raise RuntimeError("content_source_output_invalid")
        else:
            matches = output.get("matches")
            if (
                output.get("query") != query
                or not isinstance(matches, list)
                or len(matches) > 12
            ):
                raise RuntimeError("content_source_output_invalid")
            for hit in matches:
                if not isinstance(hit, dict):
                    raise RuntimeError("content_source_output_invalid")
                identifier = hit.get("document_id")
                original = authorized.get(identifier) if isinstance(identifier, str) else None
                start, end, excerpt = hit.get("offset"), hit.get("end_offset"), hit.get("excerpt")
                if (
                    original is None
                    or hit.get("document_name") != original["name"]
                    or hit.get("folder_id") is not None
                    or hit.get("sha256") != original["sha256"]
                    or type(start) is not int
                    or type(end) is not int
                    or not 0 <= start < end <= original["characters"]
                    or excerpt != original["text"][start:end]
                ):
                    raise RuntimeError("content_source_output_invalid")
        logger.info("content_source_execution_completed", extra={
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id, "user_id": context.user_id,
            "source_count": len(references), "operation": operation,
            "status": "success",
        })
        return output

"""Admit canonical owner-active inert text to Content Intelligence.

Host-only composition. RuntimePolicy and the extension kernel remain authoritative.
"""
from __future__ import annotations

import asyncio
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


def _validate_source_operation(
    operation: str, references: list[dict[str, str]], *,
    query: str | None, left_id: str | None, right_id: str | None,
) -> list[tuple[str, str]]:
    """Validate operation shape and pin selection before any await."""
    if operation not in {"analyze", "search", "compare"}:
        raise ValueError("content_source_operation_invalid")
    if not isinstance(references, list) or not 1 <= len(references) <= MAX_CONTENT_SOURCE_REFERENCES:
        raise ValueError("content_source_count_invalid")
    ids: set[str] = set()
    selection: list[tuple[str, str]] = []
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
        selection.append((ref["source_id"], ref["revision"]))
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
    return selection


def _snapshot_source_documents(
    documents: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    """Detach lineage evidence from mutable handler input."""
    # Freeze authorization evidence before invoking the mutable plugin
    # kernel. A handler may replace its input document fields in place;
    # that must never redefine which source/revision was authorized.
    return {
        document["id"]: {
            "name": document["name"],
            "sha256": hashlib.sha256(document["text"].encode("utf-8")).hexdigest(),
            "characters": len(document["text"]),
            "text": document["text"],
        }
        for document in documents
    }


def _validate_source_output(
    output: Any, *, operation: str, authorized: dict[str, dict[str, Any]],
    query: str | None, left_id: str | None, right_id: str | None,
) -> dict[str, Any]:
    """Validate source lineage, not independent analytical correctness."""
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
    return output


def _runtime_source_documents(
    context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Project only already-admitted owner evidence; never read storage here."""
    runtime_context, _ = context.runtime_attachment_context(PLUGIN, plan)
    if (
        not _uuid(context.tenant_id) or not _uuid(context.user_id)
        or not {PLUGIN, "data:read"}.issubset(plan.allowed_capabilities)
        or not {PLUGIN, "data:read"}.issubset(context.allowed_capabilities)
        or context.audit_context.get("user_roles") != runtime_context.roles
    ):
        raise PermissionError("content_source_authorization_required")
    records = runtime_context.runtime_attachment_evidence()
    references = [
        {"source_id": record.artifact_id, "revision": record.sha256}
        for record in records
    ]
    if references != plan.resource_scope.get("attachment_references"):
        raise PermissionError("content_source_reference_invalid")
    _validate_source_operation(
        "analyze", references, query=None, left_id=None, right_id=None,
    )
    documents: list[dict[str, str]] = []
    total = 0
    for record in records:
        if (
            record.tenant_id != context.tenant_id or record.user_id != context.user_id
            or record.mime_type != "text/plain"
            or not 1 <= len(record.filename) <= 256
            or not 1 <= len(record.text) <= 100_000
            or hashlib.sha256(record.text.encode("utf-8")).hexdigest() != record.sha256
        ):
            raise PermissionError("content_source_evidence_invalid")
        total += len(record.text)
        if total > 300_000:
            raise ValueError("content_source_budget_exceeded")
        documents.append({"id": record.artifact_id, "name": record.filename, "text": record.text})
    return references, documents


def validate_runtime_content_payload(
    context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
    payload: dict[str, Any],
) -> None:
    """The kernel verifies every submitted byte against pinned chat evidence."""
    references, documents = _runtime_source_documents(context, plan)
    if not isinstance(payload, dict) or payload.get("documents") != documents:
        raise PermissionError("content_source_evidence_invalid")
    operation = payload.get("operation")
    if not isinstance(operation, str):
        raise ValueError("content_source_operation_invalid")
    _validate_source_operation(
        operation, references, query=payload.get("query"),
        left_id=payload.get("left_id"), right_id=payload.get("right_id"),
    )
    fields = {"operation", "documents"}
    if operation == "search":
        fields.add("query")
    elif operation == "compare":
        fields.update({"left_id", "right_id"})
    if set(payload) != fields:
        raise ValueError("content_source_operation_invalid")


async def revalidate_runtime_content_session(
    context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
) -> None:
    """Use the same original clock and durable session witness, without renewal."""
    runtime_context, meter = context.runtime_attachment_context(PLUGIN, plan)
    remaining = await meter.remaining_admitted_duration_ms()
    if remaining <= 0:
        raise PermissionError("content_source_execution_deadline")
    async with asyncio.timeout(remaining / 1000):
        await runtime_context.revalidate_runtime_attachment_session()
    current_context, current_meter = context.runtime_attachment_context(PLUGIN, plan)
    if (
        current_context is not runtime_context or current_meter is not meter
        or await meter.remaining_admitted_duration_ms() <= 0
    ):
        raise PermissionError("content_source_authorization_required")


class ContentSourceHost:
    """Bridge a trusted authorized plan to the existing owner-text repository."""

    def __init__(self, *, store: TextStore, kernel: Kernel) -> None:
        self._store = store
        self._kernel = kernel

    @staticmethod
    def _require_standalone_owner_access(
        context: ExtensionExecutionContext, plan: AuthorizedExecutionPlan,
    ) -> None:
        """Do not reinterpret a scoped chat grant as standalone owner access."""
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
            or plan.resource_scope != {}
            or context.runtime_authority(PLUGIN) is not None
        ):
            raise PermissionError("content_source_authorization_required")

    @staticmethod
    async def admit_owner_access(
        *, kernel: Kernel, context: ExtensionExecutionContext,
        plan: AuthorizedExecutionPlan,
    ) -> None:
        """Check standalone scope and kernel admission before any source read."""
        ContentSourceHost._require_standalone_owner_access(context, plan)
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
        ContentSourceHost._require_standalone_owner_access(context, plan)

    @staticmethod
    async def execute_runtime_text(
        *, kernel: Kernel, context: ExtensionExecutionContext,
        plan: AuthorizedExecutionPlan, operation: str, query: str | None = None,
        left_id: str | None = None, right_id: str | None = None,
    ) -> dict[str, Any]:
        """Invoke only the original chat grant; no new policy or storage read."""
        references, documents = _runtime_source_documents(context, plan)
        _validate_source_operation(
            operation, references, query=query, left_id=left_id, right_id=right_id,
        )
        payload: dict[str, Any] = {"operation": operation, "documents": documents}
        if operation == "search":
            payload["query"] = query
        elif operation == "compare":
            payload.update({"left_id": left_id, "right_id": right_id})
        authorized = _snapshot_source_documents(documents)
        await revalidate_runtime_content_session(context, plan)
        validate_runtime_content_payload(context, plan, payload)
        record = kernel.get_record(PLUGIN)
        if (
            not isinstance(record, dict) or record.get("status") != "enabled"
            or record.get("dependencies_resolved") is not True
        ):
            raise PermissionError("content_source_plugin_disabled")
        _, meter = context.runtime_attachment_context(PLUGIN, plan)
        remaining = await meter.remaining_admitted_duration_ms()
        if remaining <= 0:
            raise PermissionError("content_source_execution_deadline")
        async with asyncio.timeout(remaining / 1000):
            # The executor owns the single reservation and repeats the byte check.
            result = await kernel.execute(ExtensionExecutionRequest(
                plugin_id=PLUGIN, capability="execute", payload=payload,
                context=context, authorized_plan=plan,
            ))
            if getattr(result, "status", None) != "success":
                raise PermissionError("content_source_execution_denied")
            output = _validate_source_output(
                getattr(result, "payload", None), operation=operation,
                authorized=authorized, query=query, left_id=left_id, right_id=right_id,
            )
            await revalidate_runtime_content_session(context, plan)
            return output

    async def execute_owner_text(
        self, *, context: ExtensionExecutionContext,
        plan: AuthorizedExecutionPlan, operation: str,
        references: list[dict[str, str]], query: str | None = None,
        left_id: str | None = None, right_id: str | None = None,
    ) -> dict[str, Any]:
        selection = _validate_source_operation(
            operation, references, query=query, left_id=left_id, right_id=right_id,
        )

        await self.admit_owner_access(kernel=self._kernel, context=context, plan=plan)
        documents: list[dict[str, str]] = []
        total_chars = 0
        # Use the validated snapshot, not caller-owned containers after an await.
        for source_id, revision in selection:
            self._require_standalone_owner_access(context, plan)
            response = await self._store.read_owner_active_code(
                source_id, context.tenant_id, context.user_id,
            )
            self._require_standalone_owner_access(context, plan)
            if not getattr(response, "success", False):
                raise PermissionError("content_source_unavailable")
            artifact = getattr(response, "data", None)
            if (
                artifact is None
                or getattr(artifact, "artifact_id", None) != source_id
                or getattr(artifact, "tenant_id", None) != context.tenant_id
                or getattr(artifact, "user_id", None) != context.user_id
                or getattr(artifact, "sha256", None) != revision
                or not isinstance(getattr(artifact, "filename", None), str)
                or not 1 <= len(artifact.filename) <= 256
                or not isinstance(getattr(artifact, "text", None), str)
                or not 1 <= len(artifact.text) <= 100_000
                or hashlib.sha256(artifact.text.encode("utf-8")).hexdigest()
                != revision
            ):
                raise PermissionError("content_source_evidence_invalid")
            total_chars += len(artifact.text)
            if total_chars > 300_000:
                raise ValueError("content_source_budget_exceeded")
            documents.append({
                "id": source_id, "name": artifact.filename,
                "text": artifact.text,
            })
        authorized = _snapshot_source_documents(documents)
        payload: dict[str, Any] = {"operation": operation, "documents": documents}
        if operation == "search":
            payload["query"] = query
        if operation == "compare":
            payload.update({"left_id": left_id, "right_id": right_id})
        self._require_standalone_owner_access(context, plan)
        result = await self._kernel.execute(ExtensionExecutionRequest(
            plugin_id=PLUGIN, capability="execute", payload=payload,
            context=context, authorized_plan=plan,
        ))
        self._require_standalone_owner_access(context, plan)
        if getattr(result, "status", None) != "success":
            raise PermissionError("content_source_execution_denied")
        output = getattr(result, "payload", None)
        output = _validate_source_output(
            output, operation=operation, authorized=authorized, query=query,
            left_id=left_id, right_id=right_id,
        )
        logger.info("content_source_execution_completed", extra={
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "tenant_id": context.tenant_id, "user_id": context.user_id,
            "source_count": len(selection), "operation": operation,
            "status": "success",
        })
        return output

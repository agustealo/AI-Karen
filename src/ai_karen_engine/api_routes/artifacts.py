"""
Artifact lifecycle API routes.

Exposes upload, download, metadata, archive, restore, list-archived,
and purge operations through the canonical ArtifactStore contract.
"""

from __future__ import annotations

import asyncio
import logging
import re
from uuid import UUID, uuid4
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from starlette.requests import ClientDisconnect

from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.core.services.dependencies import get_chat_execution_context, get_plugin_service
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
from ai_karen_engine.database.factory import DatabaseServiceFactory
from ai_karen_engine.database.id_types import coerce_tenant_id, coerce_user_id
from ai_karen_engine.config.artifact_storage import ArtifactStorageConfig
from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.core.runtime.conversation_runtime_gateway import read_owned_historical_attachment_reference
from ai_karen_engine.core.runtime.owned_history_projection import UnreplayableHistory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class ArtifactUploadResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str


class OwnerTextTransferResponse(BaseModel):
    session_id: str
    artifact_id: str
    filename: str
    sha256: str
    size_bytes: int


class ArtifactMetadataResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    kind: str
    mime_type: str
    filename: str
    size_bytes: int
    sha256: str
    created_at: str
    deleted_at: Optional[str] = None


def _get_artifact_store():
    factory = DatabaseServiceFactory()
    factory.create_canonical_repositories()
    store = factory.get_service("artifact_store")
    if store is None:
        raise HTTPException(status_code=503, detail="Artifact store unavailable")
    return store


def _artifact_principal(current_user):
    """Resolve trusted artifact scope from authenticated session context."""
    tenant = getattr(current_user, "tenant_id", None)
    user = getattr(current_user, "user_id", None)
    if not tenant or not user:
        raise HTTPException(status_code=403, detail="Artifact access denied")
    tenant_id = str(coerce_tenant_id(tenant))
    user_id = str(coerce_user_id(user))
    if not tenant_id or tenant_id == "default" or not user_id:
        raise HTTPException(status_code=403, detail="Artifact access denied")
    return tenant_id, user_id


async def _require_owned_artifact(store, artifact_id: str, tenant_id: str, user_id: str):
    """Owner-only lifecycle gate until shared-resource grants are implemented."""
    result = await store.get_metadata(artifact_id, tenant_id)
    if not result.success:
        raise HTTPException(status_code=503, detail="Artifact metadata unavailable")
    artifact = result.data
    if (
        artifact is None
        or artifact.tenant_id != tenant_id
        or artifact.user_id != user_id
    ):
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.post("/upload/text", response_model=OwnerTextTransferResponse)
async def transfer_owner_text(
    request: Request,
    response: Response,
    current_user=Depends(get_chat_execution_context),
):
    """Bounded raw UTF-8 ingress; delegate every durable operation to runtime.

    This narrowly scoped, default-off contract is not a general multipart
    upload API. Headers identify the exact destination, recipe and retry key,
    never the authenticated owner, session or conversation.
    """
    from ai_karen_engine.core.runtime.owner_text_upload import OwnerTextUploadReceipt
    from ai_karen_engine.services.database.repositories.upload_session import UploadSessionConflict

    try:
        config = ArtifactStorageConfig.from_environment()
    except ValueError:
        raise HTTPException(status_code=503, detail="Upload unavailable") from None
    if not config.governed_text_upload_ingress_enabled:
        raise HTTPException(status_code=404, detail="Upload unavailable")
    context = _artifact_access_context(request, current_user, write=True)
    if not context.request_id:
        context.request_id = str(uuid4())

    def required_header(name: str, max_length: int) -> str:
        values = request.headers.getlist(name)
        if len(values) != 1 or not 1 <= len(values[0]) <= max_length:
            raise HTTPException(status_code=422, detail="Invalid upload headers")
        return values[0]

    if request.query_params:
        raise HTTPException(status_code=422, detail="Upload query parameters are not supported")
    content_type = required_header("content-type", 80).lower()
    if content_type not in {"text/plain", "text/plain; charset=utf-8"}:
        raise HTTPException(status_code=415, detail="Only UTF-8 plain text is supported")
    if request.headers.getlist("content-encoding"):
        raise HTTPException(status_code=415, detail="Encoded upload bodies are not supported")
    filename = required_header("x-upload-filename", 160)
    key = required_header("idempotency-key", 36)
    destination = required_header("x-upload-destination", 32)
    recipe = required_header("x-upload-recipe", 32)
    try:
        if str(UUID(key)) != key:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid upload idempotency key") from None
    limit = config.governed_text_upload_max_bytes
    declared = request.headers.getlist("content-length")
    if declared:
        if len(declared) != 1 or re.fullmatch(r"[0-9]{1,20}", declared[0]) is None:
            raise HTTPException(status_code=422, detail="Invalid upload content length")
        if int(declared[0]) > limit:
            raise HTTPException(status_code=413, detail="Upload exceeds byte limit")

    # Authenticate before consuming any body bytes. No FastAPI File/Body
    # dependency is used: the bounded stream is the only body consumer.
    try:
        await context.revalidate_runtime_artifact_write_session()
    except PermissionError:
        raise HTTPException(status_code=403, detail="Upload access denied") from None
    data = bytearray()
    try:
        async with asyncio.timeout(config.governed_text_upload_deadline_seconds):
            async for chunk in request.stream():
                if len(chunk) > limit - len(data):
                    raise HTTPException(status_code=413, detail="Upload exceeds byte limit")
                data.extend(chunk)
    except TimeoutError:
        raise HTTPException(status_code=408, detail="Upload body deadline exceeded") from None
    except ClientDisconnect:
        raise HTTPException(status_code=400, detail="Upload body interrupted") from None
    if declared and len(data) != int(declared[0]):
        raise HTTPException(status_code=422, detail="Upload content length mismatch")
    try:
        await context.revalidate_runtime_artifact_write_session()
        service = await get_plugin_service()
        receipt = await service.transfer_owner_text(
            context, destination=destination, recipe=recipe, filename=filename,
            data=bytes(data), idempotency_key=key,
        )
        if not isinstance(receipt, OwnerTextUploadReceipt):
            raise RuntimeError("Unverified transfer receipt")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Upload access denied") from None
    except UploadSessionConflict:
        raise HTTPException(status_code=409, detail="Upload key conflicts with existing transfer") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid upload payload") from None
    except Exception as exc:
        logger.warning("Owner upload outcome unavailable", extra={
            "request_id": context.request_id, "correlation_id": context.correlation_id,
            "error_type": type(exc).__name__,
        })
        raise HTTPException(status_code=503, detail="Upload outcome unavailable; reuse the same key") from None

    response.headers["Cache-Control"] = "no-store"
    return OwnerTextTransferResponse(
        session_id=receipt.session_id, artifact_id=receipt.artifact_id,
        filename=receipt.filename, sha256=receipt.sha256, size_bytes=receipt.size_bytes,
    )


@router.post("/upload", response_model=ArtifactUploadResponse)
async def upload_artifact(
    request: Request,
    file: UploadFile = File(...),
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    kind: str = "attachment",
    current_user = Depends(get_chat_execution_context),
):
    """Legacy bounded upload: owner library only, not conversation attachment."""
    context = _artifact_access_context(request, current_user, write=True)
    # The legacy writer cannot durably bind an artifact to a message or
    # conversation. Reject even an owned binding instead of reporting a save
    # that the canonical metadata does not represent.
    if conversation_id is not None or message_id is not None:
        raise HTTPException(status_code=422, detail="Legacy upload does not support conversation binding")
    try:
        await context.revalidate_runtime_artifact_write_session()
    except PermissionError:
        raise HTTPException(status_code=403, detail="Artifact access denied") from None
    try:
        limit = ArtifactStorageConfig.from_environment().max_legacy_upload_bytes
    except ValueError:
        logger.error("Invalid artifact upload limit configuration")
        raise HTTPException(status_code=503, detail="Artifact upload unavailable") from None

    # Read at most limit + 1 bytes. The extra byte detects oversized bodies
    # without materializing the entire untrusted upload in process memory.
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail="Artifact exceeds upload limit")
    # Body reads can suspend; require fresh account and owner-create permission
    # again before invoking the only canonical Storage writer.
    try:
        await context.revalidate_runtime_artifact_write_session()
    except PermissionError:
        raise HTTPException(status_code=403, detail="Artifact access denied") from None
    store = _get_artifact_store()
    from ai_karen_engine.services.database.repositories.artifact_store import ArtifactUploadRequest
    upload = ArtifactUploadRequest(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        kind=kind,
        filename=file.filename or "uploaded",
        content_type=file.content_type or "application/octet-stream",
        data=data,
    )
    result = await store.upload(upload)
    if not result.success or not result.data:
        logger.error("Artifact upload repository rejected request")
        raise HTTPException(status_code=503, detail="Artifact upload failed")

    artifact = result.data
    return ArtifactUploadResponse(
        id=artifact.id,
        tenant_id=artifact.tenant_id,
        user_id=artifact.user_id,
        filename=artifact.filename,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
    )


@router.get("/archived", response_model=List[ArtifactMetadataResponse])
async def list_archived_artifacts(
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    current_user = Depends(get_current_user),
):
    """List archived artifacts."""
    store = _get_artifact_store()
    tenant_id, user_id = _artifact_principal(current_user)
    result = await store.list_archived(str(tenant_id), conversation_id, message_id)
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "List archived failed")

    items = []
    for artifact in result.data or []:
        if artifact.tenant_id != tenant_id or artifact.user_id != user_id:
            continue
        items.append(ArtifactMetadataResponse(
            id=artifact.id,
            tenant_id=artifact.tenant_id,
            user_id=artifact.user_id,
            conversation_id=artifact.conversation_id,
            message_id=artifact.message_id,
            kind=artifact.kind,
            mime_type=artifact.mime_type,
            filename=artifact.filename,
            size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
            created_at=artifact.created_at.isoformat() if artifact.created_at else "",
            deleted_at=artifact.deleted_at.isoformat() if artifact.deleted_at else None,
        ))
    return items


class OwnedArtifactPage(BaseModel):
    """Tenant-and-owner scoped metadata projection. No source bytes or URLs."""
    items: List[ArtifactMetadataResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False


@router.get("/owner-page", response_model=OwnedArtifactPage)
async def list_owned_artifact_page(
    limit: int = 100,
    cursor: Optional[str] = None,
    current_user = Depends(get_current_user),
):
    """Page through the existing canonical owner-only ArtifactStore query."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="Invalid owner page limit")
    if cursor is not None and (not cursor or len(cursor) > 768):
        raise HTTPException(status_code=422, detail="Invalid owner page cursor")
    tenant_id, user_id = _artifact_principal(current_user)
    store = _get_artifact_store()
    result = await store.list_owner_artifacts_page(
        tenant_id, user_id, limit=limit, cursor=cursor,
    )
    if not result.success:
        raise HTTPException(status_code=503, detail="Owned artifact inventory unavailable")
    # The repository, not this HTTP boundary, owns paging decisions. An
    # incomplete or malformed result must never masquerade as a final page.
    meta = result.metadata
    if (
        not isinstance(result.data, list)
        or len(result.data) > limit
        or not isinstance(meta, dict)
        or type(meta.get("has_more")) is not bool
    ):
        raise HTTPException(status_code=503, detail="Owned artifact page invalid")
    has_more = meta["has_more"]
    next_cursor = meta.get("next_cursor")
    if has_more and (
        not result.data
        or not isinstance(next_cursor, str)
        or not 1 <= len(next_cursor) <= 768
        or next_cursor == cursor
    ):
        raise HTTPException(status_code=503, detail="Owned artifact cursor unavailable")
    if not has_more and next_cursor is not None:
        raise HTTPException(status_code=503, detail="Owned artifact cursor inconsistent")
    items: List[ArtifactMetadataResponse] = []
    for artifact in result.data:
        if (
            artifact.tenant_id != tenant_id
            or artifact.user_id != user_id
            or artifact.deleted_at is not None
        ):
            raise HTTPException(status_code=503, detail="Owned artifact scope mismatch")
        items.append(ArtifactMetadataResponse(
            id=artifact.id,
            tenant_id=artifact.tenant_id,
            user_id=artifact.user_id,
            conversation_id=artifact.conversation_id,
            message_id=artifact.message_id,
            kind=artifact.kind,
            mime_type=artifact.mime_type,
            filename=artifact.filename,
            size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
            created_at=artifact.created_at.isoformat() if artifact.created_at else "",
            deleted_at=None,
        ))
    return OwnedArtifactPage(
        items=items, has_more=has_more,
        next_cursor=next_cursor if has_more else None,
    )


def _artifact_access_context(request: Request, current_user, *, conversation_id=None, write=False):
    tenant_id, user_id = _artifact_principal(current_user)
    rbac = get_rbac_manager()
    permissions = (Permission.DATA_READ, Permission.ARTIFACT_CREATE_OWN) if write else (Permission.DATA_READ,)
    operation = "artifact_owner_upload" if write else "artifact_owner_text_read"
    for permission in permissions:
        allowed = rbac.has_permission(current_user, permission)
        rbac.audit_access_attempt(
            current_user, permission, resource=request.url.path,
            granted=allowed, request=request,
            additional_context={"operation": operation},
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="Artifact access denied")
    return ChatExecutionContext(
        user_id=user_id, tenant_id=tenant_id, authenticated_user=current_user,
        conversation_id=conversation_id,
        request_id=getattr(request.state, "request_id", None),
    )


async def _revalidate_artifact_text_context(context: ChatExecutionContext) -> None:
    try:
        await context.revalidate_runtime_attachment_session()
    except PermissionError:
        raise HTTPException(status_code=403, detail="Artifact access denied") from None


async def _read_verified_artifact_text(
    context: ChatExecutionContext, artifact_id: str, revision: str | None,
    response: Response,
):
    """Shared current-access boundary for direct and historical owner reads."""
    from ai_karen_engine.services.database.repositories.artifact_store import VerifiedArtifactText

    try:
        if str(UUID(artifact_id)) != artifact_id:
            raise ValueError("noncanonical artifact ID")
        if revision is not None and (
            not isinstance(revision, str) or re.fullmatch(r"[a-f0-9]{64}", revision) is None
        ):
            raise ValueError("noncanonical artifact revision")
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Artifact text unavailable") from None
    await _revalidate_artifact_text_context(context)
    store = _get_artifact_store()
    try:
        result = await store.read_owner_active_text_bounded(
            artifact_id, context.tenant_id, context.user_id, max_bytes=65536,
            **({"expected_sha256": revision} if revision is not None else {}),
        )
    except TypeError:
        raise HTTPException(status_code=404, detail="Artifact text unavailable") from None
    value = result.data
    if (
        not result.success or not isinstance(value, VerifiedArtifactText)
        or (value.artifact_id, value.tenant_id, value.user_id)
        != (artifact_id, context.tenant_id, context.user_id)
        or (revision is not None and value.sha256 != revision)
    ):
        raise HTTPException(status_code=404, detail="Artifact text unavailable")
    await _revalidate_artifact_text_context(context)
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "artifact_id": value.artifact_id, "filename": value.filename,
        "mime_type": value.mime_type, "sha256": value.sha256,
        "size_bytes": len(value.text.encode("utf-8")), "text": value.text,
    }


@router.get("/{artifact_id}/text")
async def read_artifact_text(
    artifact_id: str,
    request: Request,
    response: Response,
    current_user=Depends(get_chat_execution_context),
    revision: str | None = None,
):
    """Return currently authorized owner text, optionally pinned to a revision."""
    context = _artifact_access_context(request, current_user)
    return await _read_verified_artifact_text(context, artifact_id, revision, response)


@router.get("/history/{thread_id}/{assistant_message_id}/{ordinal}/text")
async def read_historical_attachment_text(
    thread_id: str,
    assistant_message_id: str,
    ordinal: int,
    request: Request,
    response: Response,
    current_user=Depends(get_chat_execution_context),
):
    """Resolve original provenance and reauthorize the current owner text."""
    features = get_runtime_settings().features
    if not (
        features.enable_ag_ui_bridge
        and getattr(features, "enable_ag_ui_durable_runs", False)
    ):
        raise HTTPException(status_code=404, detail="Artifact text unavailable")
    try:
        if str(UUID(thread_id)) != thread_id or str(UUID(assistant_message_id)) != assistant_message_id:
            raise ValueError("noncanonical history identity")
        if type(ordinal) is not int or not 1 <= ordinal <= 12:
            raise ValueError("invalid attachment ordinal")
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Artifact text unavailable") from None
    context = _artifact_access_context(request, current_user, conversation_id=thread_id)
    await _revalidate_artifact_text_context(context)
    try:
        reference = await read_owned_historical_attachment_reference(
            context, assistant_message_id=assistant_message_id, ordinal=ordinal,
        )
    except (PermissionError, UnreplayableHistory):
        raise HTTPException(status_code=404, detail="Artifact text unavailable") from None
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc) == "conversation_not_found":
            raise HTTPException(status_code=404, detail="Artifact text unavailable") from None
        logger.warning("Historical artifact provenance unavailable", extra={
            "correlation_id": context.correlation_id, "error_type": type(exc).__name__,
        })
        raise HTTPException(status_code=503, detail="Artifact text unavailable") from None
    value = await _read_verified_artifact_text(
        context, reference["source_id"], reference["revision"], response,
    )
    # Do not expose internal reference identities or revisions on this surface.
    return {key: value[key] for key in ("filename", "mime_type", "size_bytes", "text")}


@router.get("/{artifact_id}", response_model=ArtifactMetadataResponse)
async def get_artifact_metadata(
    artifact_id: str,
    current_user = Depends(get_current_user),
):
    """Retrieve artifact metadata."""
    store = _get_artifact_store()
    tenant_id, user_id = _artifact_principal(current_user)
    artifact = await _require_owned_artifact(
        store, artifact_id, tenant_id, user_id
    )
    return ArtifactMetadataResponse(
        id=artifact.id,
        tenant_id=artifact.tenant_id,
        user_id=artifact.user_id,
        conversation_id=artifact.conversation_id,
        message_id=artifact.message_id,
        kind=artifact.kind,
        mime_type=artifact.mime_type,
        filename=artifact.filename,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        created_at=artifact.created_at.isoformat() if artifact.created_at else "",
        deleted_at=artifact.deleted_at.isoformat() if artifact.deleted_at else None,
    )


@router.get("/", response_model=List[ArtifactMetadataResponse])
async def list_artifacts(
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    current_user = Depends(get_current_user),
):
    """List active artifacts."""
    store = _get_artifact_store()
    tenant_id, user_id = _artifact_principal(current_user)
    result = await store.list_artifacts(str(tenant_id), conversation_id, message_id)
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "List failed")

    items = []
    for artifact in result.data or []:
        if artifact.tenant_id != tenant_id or artifact.user_id != user_id:
            continue
        items.append(ArtifactMetadataResponse(
            id=artifact.id,
            tenant_id=artifact.tenant_id,
            user_id=artifact.user_id,
            conversation_id=artifact.conversation_id,
            message_id=artifact.message_id,
            kind=artifact.kind,
            mime_type=artifact.mime_type,
            filename=artifact.filename,
            size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
            created_at=artifact.created_at.isoformat() if artifact.created_at else "",
            deleted_at=artifact.deleted_at.isoformat() if artifact.deleted_at else None,
        ))
    return items


@router.delete("/{artifact_id}")
async def delete_artifact(
    artifact_id: str,
    current_user = Depends(get_current_user),
):
    """Permanently delete an artifact."""
    store = _get_artifact_store()
    tenant_id, user_id = _artifact_principal(current_user)
    await _require_owned_artifact(store, artifact_id, tenant_id, user_id)
    result = await store.delete(artifact_id, str(tenant_id))
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Delete failed")
    return {"deleted": True}


@router.post("/{artifact_id}/archive")
async def archive_artifact(
    artifact_id: str,
    current_user = Depends(get_current_user),
):
    """Soft-delete (archive) an artifact."""
    store = _get_artifact_store()
    tenant_id, user_id = _artifact_principal(current_user)
    await _require_owned_artifact(store, artifact_id, tenant_id, user_id)
    result = await store.archive(artifact_id, str(tenant_id))
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Archive failed")
    return {"archived": True}


@router.post("/{artifact_id}/restore")
async def restore_artifact(
    artifact_id: str,
    current_user = Depends(get_current_user),
):
    """Restore an archived artifact."""
    store = _get_artifact_store()
    tenant_id, user_id = _artifact_principal(current_user)
    await _require_owned_artifact(store, artifact_id, tenant_id, user_id)
    result = await store.restore(artifact_id, str(tenant_id))
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Restore failed")
    return {"restored": True}


@router.delete("/{artifact_id}/purge")
async def purge_artifact(
    artifact_id: str,
    current_user = Depends(get_current_user),
):
    """Permanently purge an archived artifact."""
    store = _get_artifact_store()
    tenant_id, user_id = _artifact_principal(current_user)
    await _require_owned_artifact(store, artifact_id, tenant_id, user_id)
    result = await store.purge(artifact_id, str(tenant_id))
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Purge failed")
    return {"purged": True}

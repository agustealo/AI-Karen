"""
Artifact lifecycle API routes.

Exposes upload, download, metadata, archive, restore, list-archived,
and purge operations through the canonical ArtifactStore contract.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.database.factory import DatabaseServiceFactory
from ai_karen_engine.database.id_types import coerce_tenant_id, coerce_user_id

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


@router.post("/upload", response_model=ArtifactUploadResponse)
async def upload_artifact(
    file: UploadFile = File(...),
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    kind: str = "attachment",
    current_user = Depends(get_current_user),
):
    """Upload an artifact."""
    store = _get_artifact_store()
    tenant_id, user_id = _artifact_principal(current_user)

    data = await file.read()
    from ai_karen_engine.services.database.repositories.artifact_store import ArtifactUploadRequest
    request = ArtifactUploadRequest(
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        conversation_id=conversation_id,
        message_id=message_id,
        kind=kind,
        filename=file.filename or "uploaded",
        content_type=file.content_type or "application/octet-stream",
        data=data,
    )
    result = await store.upload(request)
    if not result.success or not result.data:
        raise HTTPException(status_code=500, detail=result.error or "Upload failed")

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

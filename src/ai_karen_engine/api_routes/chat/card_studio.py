"""Thin authenticated HTTP transport for inert Card Studio template CRUD.

Identity is obtained only through canonical authentication middleware.
RuntimePolicy and the runtime service authorize every read and mutation.
This transport cannot publish templates, bind evidence, execute plugins,
change ownership, or manufacture a successful persistence response.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ai_karen_engine.api_routes.chat.execution_identity import (
    build_chat_execution_context,
)
from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.core.runtime.card_studio_template_service import (
    CardStudioAuthorizationError,
    CardStudioTemplateService,
)
from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.persistence.repositories.card_studio_template_repository import (
    CardTemplateConflict,
    CardTemplateUnavailable,
    SavedCardTemplate,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Card Studio"])


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateTemplateBody(_StrictBody):
    idempotency_key: uuid.UUID
    draft: dict[str, Any]


class ReviseTemplateBody(_StrictBody):
    idempotency_key: uuid.UUID
    expected_revision: int = Field(strict=True, ge=1, le=9223372036854775805)
    draft: dict[str, Any]


class ArchiveTemplateBody(_StrictBody):
    idempotency_key: uuid.UUID
    expected_revision: int = Field(ge=1, le=9223372036854775805)


def _require_bearer(request: Request) -> None:
    """Prevent cookie-only cross-site writes; auth middleware verifies the bearer."""
    authorization = request.headers.get("authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not (1 <= len(token) <= 8192 and token.strip() == token and " " not in token):
        raise HTTPException(
            status_code=403, detail="Card Studio mutations require bearer authentication"
        )


def _public_template(template: SavedCardTemplate) -> dict[str, Any]:
    """Return only the owner-visible declarative schema, not identity grants."""
    return {
        "template_id": template.template_id,
        "template_key": template.template_key,
        "revision": template.revision,
        "lifecycle": template.lifecycle,
        "definition": template.definition,
    }


async def _call(
    *, user: dict[str, Any], operation: Literal[
        "catalog", "list", "read", "history", "create", "revise", "archive"
    ], **kwargs: Any,
) -> JSONResponse:
    """One mapping of runtime outcomes to guarded HTTP responses."""
    if not get_runtime_settings().features.enable_card_studio_crud:
        raise HTTPException(status_code=404, detail="Card Studio unavailable")
    correlation_id = str(uuid.uuid4())
    headers = {
        "Cache-Control": "private, no-store",
        "X-Correlation-Id": correlation_id,
    }
    try:
        context = build_chat_execution_context(
            user=user,
            session_id=correlation_id,
            conversation_id="",
            request_id=correlation_id,
            correlation_id=correlation_id,
        )
        context.require_authenticated_user()
    except (HTTPException, PermissionError, TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=401,
            detail="Authenticated Card Studio principal required",
            headers=headers,
        ) from exc

    service = CardStudioTemplateService()
    try:
        if operation == "catalog":
            catalog = await service.system_catalog(context=context)
            content: dict[str, Any] = {
                "schema_version": 1,
                "catalog": catalog,
            }
        elif operation == "list":
            templates = await service.list_owned(context=context, **kwargs)
            content: dict[str, Any] = {
                "schema_version": 1,
                "templates": [_public_template(template) for template in templates],
            }
        elif operation == "read":
            template = await service.read_owned(context=context, **kwargs)
            content = {"schema_version": 1, "template": _public_template(template)}
        elif operation == "history":
            templates = await service.list_revisions(context=context, **kwargs)
            content = {
                "schema_version": 1,
                "revisions": [_public_template(template) for template in templates],
            }
        else:
            committed = await service.mutate(
                context=context, operation=operation, **kwargs
            )
            content = {
                "schema_version": 1,
                "committed": True,
                "template": _public_template(committed.template),
                "receipt": {
                    "idempotency_key": committed.receipt.idempotency_key,
                    "operation": committed.receipt.operation,
                    "template_id": committed.receipt.template_id,
                    "revision": committed.receipt.revision,
                },
            }
        return JSONResponse(status_code=200, content=content, headers=headers)
    except CardStudioAuthorizationError as exc:
        raise HTTPException(
            status_code=403, detail="Card Studio permission denied", headers=headers,
        ) from exc
    except CardTemplateUnavailable as exc:
        raise HTTPException(
            status_code=404, detail="Card template unavailable", headers=headers,
        ) from exc
    except CardTemplateConflict as exc:
        raise HTTPException(
            status_code=409, detail="Card template conflict", headers=headers,
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="Invalid Card Studio request", headers=headers,
        ) from exc
    except Exception as exc:
        logger.error(
            "card_studio_transport_unavailable",
            extra={
                "event": "card_studio_transport_unavailable",
                "correlation_id": correlation_id,
                "error_type": type(exc).__name__,
                "operation": operation,
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Card Studio temporarily unavailable",
            headers=headers,
        ) from exc


@router.get("/chat/card-studio/catalog")
async def list_card_studio_catalog(
    user: dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    """Catalog of host-supported inert template types, never live content."""
    return await _call(user=user, operation="catalog")


@router.get("/chat/card-studio/templates")
async def list_card_templates(
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    include_archived: bool = False,
    user: dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    return await _call(
        user=user, operation="list", limit=limit, include_archived=include_archived,
    )


@router.post("/chat/card-studio/templates")
async def create_card_template(
    body: CreateTemplateBody,
    _bearer: None = Depends(_require_bearer),
    user: dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    return await _call(
        user=user, operation="create",
        draft=body.draft, idempotency_key=str(body.idempotency_key),
    )


@router.get("/chat/card-studio/templates/{template_id}")
async def read_card_template(
    template_id: uuid.UUID,
    user: dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    return await _call(
        user=user, operation="read", template_id=str(template_id),
    )


@router.put("/chat/card-studio/templates/{template_id}")
async def revise_card_template(
    template_id: uuid.UUID,
    body: ReviseTemplateBody,
    _bearer: None = Depends(_require_bearer),
    user: dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    return await _call(
        user=user, operation="revise",
        template_id=str(template_id),
        draft=body.draft,
        expected_revision=body.expected_revision,
        idempotency_key=str(body.idempotency_key),
    )


@router.post("/chat/card-studio/templates/{template_id}/archive")
async def archive_card_template(
    template_id: uuid.UUID,
    body: ArchiveTemplateBody,
    _bearer: None = Depends(_require_bearer),
    user: dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    return await _call(
        user=user, operation="archive",
        template_id=str(template_id),
        expected_revision=body.expected_revision,
        idempotency_key=str(body.idempotency_key),
    )


@router.get("/chat/card-studio/templates/{template_id}/revisions")
async def list_card_template_revisions(
    template_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    user: dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    return await _call(
        user=user, operation="history",
        template_id=str(template_id), limit=limit,
    )


@router.get("/chat/card-studio/templates/{template_id}/revisions/{revision}")
async def read_card_template_revision(
    template_id: uuid.UUID,
    revision: Annotated[int, Path(ge=1, le=9223372036854775805)],
    user: dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    return await _call(
        user=user, operation="read",
        template_id=str(template_id), revision=revision,
    )

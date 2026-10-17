"""Thin public ingress for signed, installed communication-channel webhooks.

The route has no user session because a provider is the caller. Only the
canonical channel verifier, tenant-scoped enabled DB connection, installation
registry and native signature may admit an event. No ChatRuntime invocation or
outbound send occurs in the HTTP handler.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ai_karen_engine.persistence.repositories.channel_repository import (
    ChannelAdmissionDenied,
)
from ai_karen_engine.services.channels.ingress import ChannelIngressService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["communication-channels"])

# Narrow exception to the global session-auth middleware. The provider's
# credential-based native signature is checked inside ChannelIngressService.
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_NATIVE_PATH = re.compile(
    rf"^/api/channels/webhooks/{_UUID}/{_UUID}$"
)


def is_native_channel_webhook_path(path: str, method: str) -> bool:
    """Exactly one signed-provider ingress path is exempt from JWT auth."""
    return method == "POST" and _NATIVE_PATH.fullmatch(path) is not None


async def _read_bounded_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise HTTPException(status_code=413, detail="Native event too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid request length") from None
    total = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="Native event too large")
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="Empty native event")
    return b"".join(chunks)


@router.post("/api/channels/webhooks/{tenant_id}/{connection_id}")
async def receive_signed_channel_event(
    tenant_id: UUID, connection_id: UUID, request: Request,
) -> JSONResponse:
    """Native verification and durable admission only; never return model text."""
    if not is_native_channel_webhook_path(request.url.path, request.method):
        raise HTTPException(status_code=404, detail="Not found")

    # Runtime host explicitly binds its provisioned channel service at startup
    # after registry, vault resolver and tenant-scoped DB owners are ready.
    service = getattr(request.app.state, "channel_ingress_service", None)
    if not isinstance(service, ChannelIngressService):
        raise HTTPException(status_code=503, detail="Channel ingress unavailable")

    body = await _read_bounded_body(request, service.max_native_body_bytes)
    try:
        await service.verify_and_route_installed(
            tenant_id=str(tenant_id),
            connection_id=str(connection_id),
            headers=request.headers,
            body=body,
        )
    except ChannelAdmissionDenied:
        # No user IDs, link secrets or provider credentials in HTTP responses.
        raise HTTPException(
            status_code=403, detail="Native channel event rejected",
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid native channel event",
        ) from None
    except Exception as exc:
        logger.error(
            "channel.webhook.admission_unavailable",
            extra={
                "error_type": type(exc).__name__,
                "tenant_id": str(tenant_id),
                "connection_id": str(connection_id),
            },
        )
        raise HTTPException(
            status_code=503, detail="Channel admission unavailable",
        ) from None
    return JSONResponse(status_code=202, content={"accepted": True})


__all__ = [
    "is_native_channel_webhook_path",
    "receive_signed_channel_event",
    "router",
]

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
from fastapi.responses import JSONResponse, PlainTextResponse

from ai_karen_engine.persistence.repositories.channel_repository import (
    ChannelAdmissionDenied,
)
from ai_karen_engine.services.channels.ingress import (
    ChannelIngressService,
    ChannelNativeBodyTooLarge,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["communication-channels"])

# Narrow exceptions to the global session-auth middleware. Provider POST
# authenticity is verified inside ChannelIngressService; a GET challenge is
# authenticated by the host against a scoped Vault subscription token.
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_NATIVE_PATH = re.compile(
    rf"^/api/channels/webhooks/{_UUID}/{_UUID}$"
)
_PAIRING_PATH = re.compile(
    rf"^/api/channels/personal/callbacks/{_UUID}/{_UUID}$"
)
_PERSONAL_CALLBACK_LIMIT = 16_384


def is_personal_pairing_callback_path(path: str, method: str) -> bool:
    """The sole unsigned-session route for provider-signed pairing evidence."""
    return method == "POST" and _PAIRING_PATH.fullmatch(path) is not None




def is_native_channel_webhook_path(path: str, method: str) -> bool:
    """Only provider POST events and GET subscription challenges bypass JWT."""
    return method in {"POST", "GET"} and _NATIVE_PATH.fullmatch(path) is not None


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


@router.post("/api/channels/personal/callbacks/{tenant_id}/{connection_id}")
async def receive_signed_personal_pairing_callback(
    tenant_id: UUID, connection_id: UUID, request: Request,
) -> JSONResponse:
    """Narrow signed ingress; Host verifies Vault key and persists evidence."""
    from ai_karen_engine.services.channels.host import ChannelHostServices
    from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
        PairingEvidenceDenied,
    )

    if not is_personal_pairing_callback_path(
        request.url.path, request.method,
    ):
        raise HTTPException(status_code=404, detail="Not found")
    host = getattr(request.app.state, "channel_host_services", None)
    if not isinstance(host, ChannelHostServices):
        raise HTTPException(status_code=503, detail="Pairing admission unavailable")
    body = await _read_bounded_body(request, _PERSONAL_CALLBACK_LIMIT)
    try:
        await host.admit_signed_personal_pairing_event(
            tenant_id=str(tenant_id), connection_id=str(connection_id),
            headers=request.headers, body=body,
        )
    except (PairingEvidenceDenied, PermissionError, ValueError):
        # Never surface provider identifiers, receipt IDs, or secret details.
        raise HTTPException(
            status_code=403, detail="Personal pairing event rejected",
        ) from None
    except Exception as exc:
        logger.error(
            "channel.personal_pairing.admission_unavailable",
            extra={
                "error_type": type(exc).__name__,
                "tenant_id": str(tenant_id),
                "connection_id": str(connection_id),
            },
        )
        raise HTTPException(
            status_code=503, detail="Pairing admission unavailable",
        ) from None
    return JSONResponse(status_code=202, content={"accepted": True})


@router.get("/api/channels/webhooks/{tenant_id}/{connection_id}")
async def verify_native_channel_subscription(
    tenant_id: UUID, connection_id: UUID, request: Request,
) -> PlainTextResponse:
    """Meta-style GET callback challenge; no tenant ID or token is an auth grant."""
    from ai_karen_engine.services.channels.host import ChannelHostServices

    if not is_native_channel_webhook_path(request.url.path, request.method):
        raise HTTPException(status_code=404, detail="Not found")
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if (
        mode != "subscribe"
        or not isinstance(token, str)
        or not 8 <= len(token) <= 256
        or not isinstance(challenge, str)
        or re.fullmatch(r"[0-9]{1,128}", challenge) is None
    ):
        raise HTTPException(status_code=403, detail="Channel subscription rejected")
    host = getattr(request.app.state, "channel_host_services", None)
    if not isinstance(host, ChannelHostServices):
        raise HTTPException(status_code=503, detail="Channel subscription unavailable")
    try:
        admitted = await host.verify_native_webhook_subscription(
            tenant_id=str(tenant_id),
            connection_id=str(connection_id),
            verify_token=token,
        )
    except (PermissionError, ValueError):
        raise HTTPException(
            status_code=403, detail="Channel subscription rejected",
        ) from None
    except Exception as exc:
        logger.error(
            "channel.webhook.subscription_unavailable",
            extra={
                "error_type": type(exc).__name__,
                "tenant_id": str(tenant_id),
                "connection_id": str(connection_id),
            },
        )
        raise HTTPException(
            status_code=503, detail="Channel subscription unavailable",
        ) from None
    if not admitted:
        raise HTTPException(status_code=403, detail="Channel subscription rejected")
    return PlainTextResponse(
        content=challenge, headers={"Cache-Control": "no-store"},
    )


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
    except ChannelNativeBodyTooLarge:
        raise HTTPException(status_code=413, detail="Native event too large") from None
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
    # Provider success requires HTTP 200, and only follows durable admission.
    return JSONResponse(status_code=200, content={"accepted": True})


__all__ = [
    "is_native_channel_webhook_path",
    "is_personal_pairing_callback_path",
    "receive_signed_personal_pairing_callback",
    "receive_signed_channel_event",
    "verify_native_channel_subscription",
    "router",
]

"""Zulip Cloud outgoing-webhook bot transport. Host owns AI and identities."""
from __future__ import annotations

import hmac
import json
import re
from typing import Any, Mapping, Protocol

import httpx
from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection, ChannelDeliveryReceipt, ChannelDeliveryRequest,
    ChannelDeliveryState, InboundChannelEvent,
)
from ai_karen_engine.extensions.platform.core.host.base import (
    ExtensionBase, HookContext, HookPoint,
)

_ORG_URL = re.compile(r"^https://[a-z0-9][a-z0-9-]{0,62}\\.zulipchat\\.com$")
_TOKEN = re.compile(r"^[A-Za-z0-9]{16,256}$")
_MAX_BODY = 65_536
_MAX_TEXT = 4096


class HostSecretResolver(Protocol):
    async def __call__(
        self, *, tenant_id: str, credential_handle: str,
    ) -> Mapping[str, str]: ...


class MainExtension(ExtensionBase):
    """Dedicated Zulip hosted bot, restricted to one-to-one direct messages."""

    def __init__(self, manifest: Any, context: Any) -> None:
        super().__init__(manifest, context)
        self._secret_resolver: HostSecretResolver | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._started: set[tuple[str, str, int]] = set()

    def bind_host_services(
        self, *, secret_resolver: HostSecretResolver, http_client: httpx.AsyncClient,
    ) -> None:
        if self._started:
            raise RuntimeError("Cannot rebind an active Zulip transport")
        if not callable(secret_resolver) or not callable(getattr(http_client, "post", None)):
            raise TypeError("Host resolver and HTTP client required")
        self._secret_resolver, self._http_client = secret_resolver, http_client

    async def initialize(self) -> None:
        self._started.clear()

    async def shutdown(self) -> None:
        self._started.clear()

    async def execute_hook(self, hook_point: HookPoint, context: HookContext) -> dict[str, Any]:
        raise PermissionError("Zulip transport cannot execute model or generic hooks")

    async def validate_config(self, settings: Mapping[str, Any]) -> None:
        if not isinstance(settings, Mapping) or set(settings) - {"direct_only"}:
            raise ValueError("Unsupported Zulip settings")
        if settings.get("direct_only", True) is not True:
            raise ValueError("Only one-to-one Zulip direct messages are supported")

    async def _credentials(self, connection: ChannelConnection) -> Mapping[str, str]:
        if self._secret_resolver is None:
            raise PermissionError("Zulip credential vault unavailable")
        value = await self._secret_resolver(
            tenant_id=connection.tenant_id, credential_handle=connection.credential_handle,
        )
        if not isinstance(value, Mapping):
            raise PermissionError("Zulip credentials unavailable")
        url, email, key, token = (
            value.get("organization_url"), value.get("bot_email"),
            value.get("api_key"), value.get("webhook_token"),
        )
        if (
            not isinstance(url, str) or not _ORG_URL.fullmatch(url)
            or not isinstance(email, str) or not (3 <= len(email) <= 254)
            or "@" not in email or any(ch.isspace() for ch in email)
            or not isinstance(key, str) or not (16 <= len(key) <= 256)
            or not isinstance(token, str) or not _TOKEN.fullmatch(token)
        ):
            raise PermissionError("Zulip hosted organization or credentials invalid")
        return value

    @staticmethod
    def _key(connection: ChannelConnection) -> tuple[str, str, int]:
        return connection.tenant_id, connection.connection_id, connection.revision

    def _require_active(self, connection: ChannelConnection) -> None:
        if not connection.enabled or self._key(connection) not in self._started or self._http_client is None:
            raise PermissionError("Zulip connection not activated by the host")

    async def start(self, *, connection: ChannelConnection) -> None:
        if not connection.enabled or self._http_client is None:
            raise PermissionError("Enabled host connection required")
        await self._credentials(connection)
        self._started.add(self._key(connection))

    async def stop(self, *, connection: ChannelConnection) -> None:
        self._started = {key for key in self._started if key[:2] != self._key(connection)[:2]}

    async def health(self, *, connection: ChannelConnection) -> Mapping[str, Any]:
        return {
            "transport": "zulip-cloud",
            "running": connection.enabled and self._key(connection) in self._started,
            "host_services_bound": self._secret_resolver is not None and self._http_client is not None,
        }

    async def verify_event(
        self, *, connection: ChannelConnection,
        headers: Mapping[str, str], body: bytes,
    ) -> bool:
        self._require_active(connection)
        if not body or len(body) > _MAX_BODY:
            return False
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        credentials = await self._credentials(connection)
        return (
            isinstance(payload, dict)
            and isinstance(payload.get("token"), str)
            and hmac.compare_digest(payload["token"], credentials["webhook_token"])
            and payload.get("bot_email") == credentials["bot_email"]
        )

    async def normalize_event(
        self, *, connection: ChannelConnection,
        headers: Mapping[str, str], body: bytes,
    ) -> InboundChannelEvent:
        self._require_active(connection)
        if not body or len(body) > _MAX_BODY:
            raise ValueError("Invalid Zulip webhook length")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid Zulip webhook JSON") from exc
        if not isinstance(payload, dict) or payload.get("trigger") not in ("direct_message", "private_message"):
            raise ValueError("Only direct Zulip bot requests supported")
        msg = payload.get("message")
        if not isinstance(msg, dict) or msg.get("type") not in ("private", "direct"):
            raise ValueError("Zulip webhook is not a direct message")
        sender, event_id, recipients = (
            msg.get("sender_id"), msg.get("id"), msg.get("display_recipient"),
        )
        content = msg.get("content")
        credentials = await self._credentials(connection)
        if (
            type(sender) is not int or sender <= 0
            or type(event_id) is not int or event_id <= 0
            or not isinstance(content, str) or not (0 < len(content) <= _MAX_TEXT)
            or msg.get("sender_email") == credentials["bot_email"]
            or not isinstance(recipients, list) or len(recipients) != 2
            or not all(isinstance(x, dict) and type(x.get("id")) is int for x in recipients)
            or {x["id"] for x in recipients} != {
                sender, next((x["id"] for x in recipients if x.get("email") == credentials["bot_email"]), -1)
            }
        ):
            raise ValueError("Zulip message must be a one-to-one human-to-bot DM")
        return InboundChannelEvent(
            connection_id=connection.connection_id,
            external_event_id=str(event_id), external_sender_id=str(sender),
            external_conversation_id=str(sender), message_kind="text", text=content,
        )

    async def send(
        self, *, connection: ChannelConnection, delivery: ChannelDeliveryRequest,
    ) -> ChannelDeliveryReceipt:
        self._require_active(connection)
        if delivery.connection_id != connection.connection_id:
            raise PermissionError("Zulip delivery connection mismatch")
        if (
            delivery.message_kind != "text" or not isinstance(delivery.text, str)
            or not (0 < len(delivery.text) <= _MAX_TEXT)
            or not delivery.destination_id.isascii() or not delivery.destination_id.isdecimal()
            or int(delivery.destination_id) <= 0
        ):
            raise ValueError("Zulip destination must be a positive numeric user ID")
        credentials = await self._credentials(connection)
        response = await self._http_client.post(
            f"{credentials['organization_url']}/api/v1/messages",
            auth=(credentials["bot_email"], credentials["api_key"]),
            data={
                "type": "direct", "to": json.dumps([int(delivery.destination_id)]),
                "content": delivery.text,
            },
        )
        if response.status_code == 429 or response.status_code >= 500:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id, state=ChannelDeliveryState.UNKNOWN,
                error_code="zulip_response_uncertain",
            )
        if response.status_code >= 400:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id, state=ChannelDeliveryState.FAILED,
                error_code="zulip_request_rejected",
            )
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Zulip provider response unreadable") from exc
        if (
            not isinstance(payload, dict) or payload.get("result") != "success"
            or type(payload.get("id")) is not int or payload["id"] <= 0
        ):
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id, state=ChannelDeliveryState.UNKNOWN,
                error_code="zulip_receipt_unverified",
            )
        return ChannelDeliveryReceipt(
            delivery_id=delivery.delivery_id, state=ChannelDeliveryState.SENT,
            provider_message_id=str(payload["id"]),
        )


__all__ = ["MainExtension", "HostSecretResolver"]

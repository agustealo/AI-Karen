"""Telegram Bot API transport. No AI, identity linking, or persistence authority.

The host-owned Channel Gateway injects secret resolution and a network client
after the ExtensionRegistry/RBAC gates. This extension is never allowed to
invoke ChatRuntime, choose providers, or mark a message as delivered.
"""

from __future__ import annotations

import hmac
import json
import re
from typing import Any, Mapping, Protocol

import httpx

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    ChannelDeliveryReceipt,
    ChannelDeliveryRequest,
    ChannelDeliveryState,
    InboundChannelEvent,
)
from ai_karen_engine.extensions.platform.core.host.base import (
    ExtensionBase,
    HookContext,
    HookPoint,
)

_SECRET_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_TELEGRAM_API_BASE = "https://api.telegram.org"
_MAX_NATIVE_BYTES = 65_536
_MAX_TEXT_LENGTH = 4_096


class HostSecretResolver(Protocol):
    async def __call__(
        self, *, tenant_id: str, credential_handle: str,
    ) -> Mapping[str, str]: ...


class MainExtension(ExtensionBase):
    """Optional Telegram transport with injectable host-governed dependencies."""

    def __init__(self, manifest: Any, context: Any) -> None:
        super().__init__(manifest, context)
        self._secret_resolver: HostSecretResolver | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._started: set[str] = set()

    def bind_host_services(
        self, *, secret_resolver: HostSecretResolver, http_client: httpx.AsyncClient,
    ) -> None:
        """Called by the future host Gateway, not by API routes or user prompts."""
        if self._started:
            raise RuntimeError("Cannot replace transport services while active")
        if not callable(secret_resolver) or not callable(getattr(http_client, "post", None)):
            raise TypeError("Validated host secret resolver and HTTP client are required")
        self._secret_resolver = secret_resolver
        self._http_client = http_client

    async def initialize(self) -> None:
        """Extension installed; no automatic credential lookup or provider call."""
        self._started.clear()

    async def shutdown(self) -> None:
        self._started.clear()

    async def execute_hook(
        self, hook_point: HookPoint, context: HookContext,
    ) -> dict[str, Any]:
        raise PermissionError(
            "Telegram transport has no generic hook or model execution capability"
        )

    async def validate_config(self, settings: Mapping[str, Any]) -> None:
        if not isinstance(settings, Mapping) or set(settings) - {"private_chats_only"}:
            raise ValueError("Unsupported Telegram transport configuration")
        if settings.get("private_chats_only", True) is not True:
            raise ValueError("Only authenticated private text chats are supported")

    async def _secrets(self, connection: ChannelConnection) -> tuple[str, str]:
        if self._secret_resolver is None:
            raise PermissionError("Host-governed credential resolution is unavailable")
        bundle = await self._secret_resolver(
            tenant_id=connection.tenant_id,
            credential_handle=connection.credential_handle,
        )
        if not isinstance(bundle, Mapping):
            raise PermissionError("Channel credential bundle is unavailable")
        webhook_secret = bundle.get("webhook_secret")
        bot_token = bundle.get("bot_token")
        if (
            not isinstance(webhook_secret, str)
            or _SECRET_TOKEN.fullmatch(webhook_secret) is None
            or not isinstance(bot_token, str)
            or ":" not in bot_token
            or not bot_token.split(":", 1)[0].isdigit()
            or any(c.isspace() for c in bot_token)
        ):
            raise PermissionError("Telegram channel credentials are incomplete")
        return webhook_secret, bot_token

    def _require_active(self, connection: ChannelConnection) -> None:
        if (
            not connection.enabled
            or connection.connection_id not in self._started
            or self._http_client is None
        ):
            raise PermissionError("Telegram channel is not active in the governed host")

    async def start(self, *, connection: ChannelConnection) -> None:
        if not connection.enabled or self._http_client is None:
            raise PermissionError("Host must provision an enabled connection and network client")
        await self._secrets(connection)
        self._started.add(connection.connection_id)

    async def stop(self, *, connection: ChannelConnection) -> None:
        self._started.discard(connection.connection_id)

    async def health(self, *, connection: ChannelConnection) -> Mapping[str, Any]:
        return {
            "transport": "telegram-bot",
            "running": connection.enabled and connection.connection_id in self._started,
            "host_services_bound": self._secret_resolver is not None and self._http_client is not None,
        }

    async def verify_event(
        self, *, connection: ChannelConnection,
        headers: Mapping[str, str], body: bytes,
    ) -> bool:
        self._require_active(connection)
        if len(body) > _MAX_NATIVE_BYTES or not body:
            return False
        header_values = [
            value for key, value in headers.items()
            if key.lower() == "x-telegram-bot-api-secret-token"
        ]
        if len(header_values) != 1:
            return False
        webhook_secret, _ = await self._secrets(connection)
        supplied = header_values[0]
        return (
            isinstance(supplied, str)
            and _SECRET_TOKEN.fullmatch(supplied) is not None
            and hmac.compare_digest(supplied, webhook_secret)
        )

    async def normalize_event(
        self, *, connection: ChannelConnection,
        headers: Mapping[str, str], body: bytes,
    ) -> InboundChannelEvent:
        self._require_active(connection)
        if len(body) > _MAX_NATIVE_BYTES:
            raise ValueError("Telegram update exceeds the channel body ceiling")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Malformed Telegram update") from exc
        if not isinstance(payload, dict):
            raise ValueError("Telegram update must be an object")

        update_id = payload.get("update_id")
        message = payload.get("message")
        if (
            type(update_id) is not int
            or update_id < 0
            or not isinstance(message, dict)
        ):
            raise ValueError("Unsupported Telegram update format")

        sender = message.get("from")
        chat = message.get("chat")
        text = message.get("text")
        if (
            not isinstance(sender, dict)
            or not isinstance(chat, dict)
            or type(sender.get("id")) is not int
            or sender["id"] <= 0
            or type(chat.get("id")) is not int
            or chat.get("type") != "private"
            or sender["id"] != chat["id"]
            or not isinstance(text, str)
            or not (0 < len(text) <= _MAX_TEXT_LENGTH)
        ):
            raise ValueError("Only Telegram private text messages are supported")

        return InboundChannelEvent(
            connection_id=connection.connection_id,
            external_event_id=str(update_id),
            external_sender_id=str(sender["id"]),
            external_conversation_id=str(chat["id"]),
            message_kind="text",
            text=text,
        )

    async def send(
        self, *, connection: ChannelConnection,
        delivery: ChannelDeliveryRequest,
    ) -> ChannelDeliveryReceipt:
        self._require_active(connection)
        if delivery.connection_id != connection.connection_id:
            raise PermissionError("Telegram delivery connection mismatch")
        if (
            delivery.message_kind != "text"
            or not isinstance(delivery.text, str)
            or not (0 < len(delivery.text) <= _MAX_TEXT_LENGTH)
        ):
            raise ValueError("Unsupported Telegram outbound message")
        try:
            chat_id = int(delivery.destination_id)
        except ValueError as exc:
            raise ValueError("Telegram recipient must be a numeric chat ID") from exc
        if chat_id <= 0:
            raise ValueError("Telegram private chat recipient must be positive")

        _, token = await self._secrets(connection)
        # This endpoint is Telegram's documented Bot API protocol endpoint.
        # Host-injected httpx.AsyncClient controls outbound timeout/proxy/TLS.
        response = await self._http_client.post(
            f"{_TELEGRAM_API_BASE}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": delivery.text},
        )
        if response.status_code >= 500 or response.status_code == 429:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id,
                state=ChannelDeliveryState.UNKNOWN,
                error_code="telegram_response_uncertain",
            )
        if response.status_code >= 400:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id,
                state=ChannelDeliveryState.FAILED,
                error_code="telegram_request_rejected",
            )
        try:
            result = response.json()
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Telegram returned an unparseable provider receipt") from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id,
                state=ChannelDeliveryState.UNKNOWN,
                error_code="telegram_receipt_unverified",
            )
        sent = result.get("result")
        if not isinstance(sent, dict) or type(sent.get("message_id")) is not int:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id,
                state=ChannelDeliveryState.UNKNOWN,
                error_code="telegram_receipt_unverified",
            )
        result_chat = sent.get("chat")
        if not isinstance(result_chat, dict) or result_chat.get("id") != chat_id:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id,
                state=ChannelDeliveryState.UNKNOWN,
                error_code="telegram_receipt_unverified",
            )
        return ChannelDeliveryReceipt(
            delivery_id=delivery.delivery_id,
            state=ChannelDeliveryState.SENT,
            provider_message_id=str(sent["message_id"]),
        )


__all__ = ["MainExtension", "HostSecretResolver"]

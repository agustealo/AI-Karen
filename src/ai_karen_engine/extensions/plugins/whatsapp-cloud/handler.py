"""Meta-hosted WhatsApp Cloud API transport; never owns user identity or AI."""
from __future__ import annotations

import hashlib
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

_GRAPH_VERSION = re.compile(r"^v[0-9]{1,3}\.[0-9]{1,2}$")
_PHONE_ID = re.compile(r"^[0-9]{1,32}$")
_ACCESS_TOKEN = re.compile(r"^[A-Za-z0-9|._-]{20,1024}$")
_SIGNATURE = re.compile(r"^sha256=[0-9a-f]{64}$")
_MAX_BODY = 65_536
_MAX_TEXT = 4096


class HostSecretResolver(Protocol):
    async def __call__(
        self, *, tenant_id: str, credential_handle: str,
    ) -> Mapping[str, str]: ...


class MainExtension(ExtensionBase):
    """Host-injected, revision-scoped transport to third-party Meta infrastructure."""

    def __init__(self, manifest: Any, context: Any) -> None:
        super().__init__(manifest, context)
        self._secret_resolver: HostSecretResolver | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._started: set[tuple[str, str, int]] = set()

    def bind_host_services(
        self, *, secret_resolver: HostSecretResolver, http_client: httpx.AsyncClient,
    ) -> None:
        if self._started:
            raise RuntimeError("Cannot rebind an active WhatsApp adapter")
        if not callable(secret_resolver) or not callable(getattr(http_client, "post", None)):
            raise TypeError("Host secret resolver and HTTP client required")
        self._secret_resolver, self._http_client = secret_resolver, http_client

    async def initialize(self) -> None:
        self._started.clear()

    async def shutdown(self) -> None:
        self._started.clear()

    async def execute_hook(self, hook_point: HookPoint, context: HookContext) -> dict[str, Any]:
        raise PermissionError("WhatsApp transport may not run model or generic hooks")

    async def validate_config(self, settings: Mapping[str, Any]) -> None:
        if not isinstance(settings, Mapping) or set(settings) - {"private_text_only"}:
            raise ValueError("Unsupported WhatsApp transport settings")
        if settings.get("private_text_only", True) is not True:
            raise ValueError("WhatsApp channel accepts only private text messages")

    async def _credentials(self, connection: ChannelConnection) -> Mapping[str, str]:
        if self._secret_resolver is None:
            raise PermissionError("Host credential vault is not configured")
        value = await self._secret_resolver(
            tenant_id=connection.tenant_id, credential_handle=connection.credential_handle,
        )
        if not isinstance(value, Mapping):
            raise PermissionError("Host credential bundle unavailable")
        token, secret, phone_id, version = (
            value.get("access_token"), value.get("app_secret"),
            value.get("phone_number_id"), value.get("graph_api_version"),
        )
        if (
            not isinstance(token, str) or not _ACCESS_TOKEN.fullmatch(token)
            or not isinstance(secret, str) or len(secret) < 16 or len(secret) > 512
            or not isinstance(phone_id, str) or not _PHONE_ID.fullmatch(phone_id)
            or not isinstance(version, str) or not _GRAPH_VERSION.fullmatch(version)
        ):
            raise PermissionError("WhatsApp credentials or Graph API version invalid")
        return value

    @staticmethod
    def _key(connection: ChannelConnection) -> tuple[str, str, int]:
        return connection.tenant_id, connection.connection_id, connection.revision

    def _require_active(self, connection: ChannelConnection) -> None:
        if not connection.enabled or self._key(connection) not in self._started or self._http_client is None:
            raise PermissionError("WhatsApp connection not activated by channel host")

    async def start(self, *, connection: ChannelConnection) -> None:
        if not connection.enabled or self._http_client is None:
            raise PermissionError("Host must enable the connection first")
        await self._credentials(connection)
        self._started.add(self._key(connection))

    async def stop(self, *, connection: ChannelConnection) -> None:
        self._started = {key for key in self._started if key[:2] != self._key(connection)[:2]}

    async def health(self, *, connection: ChannelConnection) -> Mapping[str, Any]:
        return {
            "transport": "whatsapp-cloud",
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
        values = [v for k, v in headers.items() if k.lower() == "x-hub-signature-256"]
        if len(values) != 1 or not isinstance(values[0], str) or not _SIGNATURE.fullmatch(values[0]):
            return False
        credentials = await self._credentials(connection)
        digest = hmac.new(
            credentials["app_secret"].encode("utf-8"), body, hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(values[0], f"sha256={digest}")

    async def normalize_event(
        self, *, connection: ChannelConnection,
        headers: Mapping[str, str], body: bytes,
    ) -> InboundChannelEvent:
        self._require_active(connection)
        if not body or len(body) > _MAX_BODY:
            raise ValueError("Invalid WhatsApp event size")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Malformed WhatsApp event JSON") from exc
        if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
            raise ValueError("Not a WhatsApp Business webhook")
        entries = payload.get("entry")
        if not isinstance(entries, list) or len(entries) != 1:
            raise ValueError("Require exactly one WhatsApp webhook entry")
        changes = entries[0].get("changes") if isinstance(entries[0], dict) else None
        if not isinstance(changes, list) or len(changes) != 1 or not isinstance(changes[0], dict):
            raise ValueError("Require exactly one WhatsApp message change")
        item = changes[0]
        data = item.get("value")
        if item.get("field") != "messages" or not isinstance(data, dict):
            raise ValueError("Unsupported WhatsApp webhook event")
        credentials = await self._credentials(connection)
        metadata = data.get("metadata")
        if (
            not isinstance(metadata, dict)
            or metadata.get("phone_number_id") != credentials["phone_number_id"]
            or data.get("messaging_product") != "whatsapp"
        ):
            raise ValueError("WhatsApp phone account mismatch")
        messages = data.get("messages")
        if not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict):
            raise ValueError("WhatsApp status or batch updates are not user messages")
        message = messages[0]
        sender, message_id, content = message.get("from"), message.get("id"), message.get("text")
        if (
            message.get("type") != "text"
            or not isinstance(sender, str) or not _PHONE_ID.fullmatch(sender)
            or not isinstance(message_id, str) or not message_id.startswith("wamid.")
            or len(message_id) > 256
            or not isinstance(content, dict) or not isinstance(content.get("body"), str)
            or not (0 < len(content["body"]) <= _MAX_TEXT)
        ):
            raise ValueError("Only direct WhatsApp text messages are supported")
        return InboundChannelEvent(
            connection_id=connection.connection_id,
            external_event_id=message_id, external_sender_id=sender,
            external_conversation_id=sender, message_kind="text", text=content["body"],
        )

    async def send(
        self, *, connection: ChannelConnection, delivery: ChannelDeliveryRequest,
    ) -> ChannelDeliveryReceipt:
        self._require_active(connection)
        if delivery.connection_id != connection.connection_id:
            raise PermissionError("WhatsApp delivery connection mismatch")
        if (
            delivery.message_kind != "text"
            or not isinstance(delivery.text, str)
            or not (0 < len(delivery.text) <= _MAX_TEXT)
            or not _PHONE_ID.fullmatch(delivery.destination_id)
        ):
            raise ValueError("Invalid WhatsApp outbound text or destination")
        credentials = await self._credentials(connection)
        # Only host-staged replies enter this method; never initiate unrestricted
        # marketing or template sends outside WhatsApp's conversation policies.
        response = await self._http_client.post(
            f"https://graph.facebook.com/{credentials['graph_api_version']}/{credentials['phone_number_id']}/messages",
            headers={"Authorization": f"Bearer {credentials['access_token']}"},
            json={
                "messaging_product": "whatsapp", "recipient_type": "individual",
                "to": delivery.destination_id, "type": "text",
                "text": {"body": delivery.text, "preview_url": False},
            },
        )
        if response.status_code in {429} or response.status_code >= 500:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id, state=ChannelDeliveryState.UNKNOWN,
                error_code="whatsapp_response_uncertain",
            )
        if response.status_code >= 400:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id, state=ChannelDeliveryState.FAILED,
                error_code="whatsapp_request_rejected",
            )
        try:
            result = response.json()
        except (ValueError, TypeError) as exc:
            raise RuntimeError("WhatsApp provider receipt unreadable") from exc
        if not isinstance(result, dict):
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id, state=ChannelDeliveryState.UNKNOWN,
                error_code="whatsapp_receipt_unverified",
            )
        messages, contacts = result.get("messages"), result.get("contacts")
        valid = (
            result.get("messaging_product") == "whatsapp"
            and isinstance(messages, list) and len(messages) == 1
            and isinstance(messages[0], dict)
            and isinstance(messages[0].get("id"), str)
            and messages[0]["id"].startswith("wamid.")
            and isinstance(contacts, list) and len(contacts) == 1
            and isinstance(contacts[0], dict)
            and contacts[0].get("wa_id") == delivery.destination_id
        )
        if not valid:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id, state=ChannelDeliveryState.UNKNOWN,
                error_code="whatsapp_receipt_unverified",
            )
        return ChannelDeliveryReceipt(
            delivery_id=delivery.delivery_id, state=ChannelDeliveryState.SENT,
            provider_message_id=messages[0]["id"],
        )


__all__ = ["MainExtension", "HostSecretResolver"]

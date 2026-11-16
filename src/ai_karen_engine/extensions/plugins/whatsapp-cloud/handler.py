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
    ChannelDeliveryState, ChannelProviderStatusEvent, ChannelWebhookBatch,
    InboundChannelEvent,
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
            or phone_id != connection.provider_account_id
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

    async def verify_subscription(
        self, *, connection: ChannelConnection, verify_token: str,
    ) -> bool:
        """Verify Meta's callback handshake using host-resolved Vault secret.

        No query-string token is a user credential; the host still resolves
        this connection from tenant-scoped, enabled persistence and checks the
        canonical installed transport before calling this method.
        """
        self._require_active(connection)
        if (
            not isinstance(verify_token, str)
            or not 8 <= len(verify_token) <= 256
            or any(ord(char) < 33 or ord(char) > 126 for char in verify_token)
        ):
            return False
        credentials = await self._credentials(connection)
        expected = credentials.get("webhook_verify_token")
        if (
            not isinstance(expected, str)
            or not 8 <= len(expected) <= 256
            or any(ord(char) < 33 or ord(char) > 126 for char in expected)
        ):
            return False
        return hmac.compare_digest(
            expected.encode("utf-8"), verify_token.encode("utf-8"),
        )

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

    @staticmethod
    def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        record: dict[str, Any] = {}
        for key, value in pairs:
            if key in record:
                raise ValueError("Duplicate WhatsApp webhook JSON key")
            record[key] = value
        return record

    async def normalize_events(
        self, *, connection: ChannelConnection,
        headers: Mapping[str, str], body: bytes,
    ) -> ChannelWebhookBatch:
        """Parse a bounded signed Meta delivery with no authority over identity.

        The host verifies the original byte signature *before* calling this
        normalizer. Unsupported media/events become ignored observations, never
        prompts; invalid phone/account scope rejects the entire callback.
        """
        self._require_active(connection)
        if not body or len(body) > _MAX_BODY:
            raise ValueError("Invalid WhatsApp webhook size")
        try:
            payload = json.loads(body, object_pairs_hook=self._unique_json_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Malformed WhatsApp webhook JSON") from exc
        if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
            raise ValueError("Not a WhatsApp Business webhook")
        entries = payload.get("entry")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
            raise ValueError("Invalid WhatsApp webhook entry count")
        credentials = await self._credentials(connection)
        messages: list[InboundChannelEvent] = []
        statuses: list[ChannelProviderStatusEvent] = []
        ignored = 0
        changes_seen = 0
        for entry in entries:
            changes = entry.get("changes") if isinstance(entry, dict) else None
            if not isinstance(changes, list) or not 1 <= len(changes) <= 16:
                raise ValueError("Invalid WhatsApp webhook changes")
            changes_seen += len(changes)
            if changes_seen > 32:
                raise ValueError("Too many WhatsApp webhook changes")
            for change in changes:
                if not isinstance(change, dict):
                    raise ValueError("Malformed WhatsApp webhook change")
                if change.get("field") != "messages":
                    ignored += 1
                    continue
                data = change.get("value")
                if not isinstance(data, dict):
                    raise ValueError("Malformed WhatsApp message container")
                metadata = data.get("metadata")
                if (
                    data.get("messaging_product") != "whatsapp"
                    or not isinstance(metadata, dict)
                    or metadata.get("phone_number_id") != credentials["phone_number_id"]
                ):
                    raise ValueError("WhatsApp phone account mismatch")
                native_messages = data.get("messages", [])
                native_statuses = data.get("statuses", [])
                if not isinstance(native_messages, list) or not isinstance(native_statuses, list):
                    raise ValueError("Invalid WhatsApp message or status array")
                if len(native_messages) + len(native_statuses) > 100:
                    raise ValueError("WhatsApp webhook event count exceeds limit")
                if not native_messages and not native_statuses:
                    ignored += 1
                for item in native_messages:
                    if not isinstance(item, dict):
                        raise ValueError("Malformed WhatsApp message")
                    if item.get("type") != "text":
                        ignored += 1
                        continue
                    sender, message_id, content = item.get("from"), item.get("id"), item.get("text")
                    if (
                        not isinstance(sender, str) or not _PHONE_ID.fullmatch(sender)
                        or not isinstance(message_id, str)
                        or not message_id.startswith("wamid.") or len(message_id) > 256
                        or not isinstance(content, dict)
                        or not isinstance(content.get("body"), str)
                        or not (0 < len(content["body"]) <= _MAX_TEXT)
                    ):
                        raise ValueError("Malformed WhatsApp text message")
                    messages.append(InboundChannelEvent(
                        connection_id=connection.connection_id,
                        external_event_id=message_id,
                        external_sender_id=sender,
                        external_conversation_id=sender,
                        message_kind="text",
                        text=content["body"],
                    ))
                for item in native_statuses:
                    if not isinstance(item, dict):
                        raise ValueError("Malformed WhatsApp status")
                    state = item.get("status")
                    if state not in {"sent", "delivered", "read", "failed"}:
                        ignored += 1
                        continue
                    message_id = item.get("id")
                    recipient = item.get("recipient_id")
                    timestamp = item.get("timestamp")
                    if (
                        not isinstance(message_id, str)
                        or not message_id.startswith("wamid.") or len(message_id) > 256
                        or not isinstance(recipient, str) or not _PHONE_ID.fullmatch(recipient)
                        or not isinstance(timestamp, str)
                        or not 1 <= len(timestamp) <= 12 or not timestamp.isascii()
                        or not timestamp.isdigit()
                    ):
                        raise ValueError("Malformed WhatsApp provider receipt")
                    timestamp_number = int(timestamp)
                    if not 1 <= timestamp_number <= 4102444800:
                        raise ValueError("Invalid WhatsApp provider timestamp")
                    receipt_id = ChannelProviderStatusEvent.receipt_for(
                        provider_message_id=message_id,
                        recipient_id=recipient,
                        state=ChannelDeliveryState(state),
                        provider_timestamp=timestamp_number,
                    )
                    statuses.append(ChannelProviderStatusEvent(
                        connection_id=connection.connection_id,
                        provider_message_id=message_id,
                        recipient_id=recipient,
                        state=ChannelDeliveryState(state),
                        provider_timestamp=timestamp_number,
                        provider_receipt_id=receipt_id,
                        error_code="whatsapp_provider_failed" if state == "failed" else None,
                    ))
                if len(messages) + len(statuses) + ignored > 100:
                    raise ValueError("WhatsApp webhook event count exceeds limit")
        return ChannelWebhookBatch(
            messages=tuple(messages), statuses=tuple(statuses), ignored_count=ignored,
        )

    async def normalize_event(
        self, *, connection: ChannelConnection,
        headers: Mapping[str, str], body: bytes,
    ) -> InboundChannelEvent:
        """Legacy single-event contract for explicit link/admit methods."""
        result = await self.normalize_events(
            connection=connection, headers=headers, body=body,
        )
        if len(result.messages) != 1 or result.statuses or result.ignored_count:
            raise ValueError("Single-event admission requires one WhatsApp text")
        return result.messages[0]

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

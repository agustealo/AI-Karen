"""Telegram Bot API transport. No AI, identity linking, or persistence authority.

The host-owned Channel Gateway injects secret resolution and a network client
after the ExtensionRegistry/RBAC gates. This extension is never allowed to
invoke ChatRuntime, choose providers, or mark a message as delivered.
"""

from __future__ import annotations

import hmac
import json
import re
from urllib.parse import urlsplit
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
_BOT_TOKEN = re.compile(r"^[0-9]{6,20}:[A-Za-z0-9_-]{20,128}$")
_TELEGRAM_API_BASE = "https://api.telegram.org"
_MAX_TEXT_LENGTH = 4_096


class HostSecretResolver(Protocol):
    async def __call__(
        self, *, tenant_id: str, credential_handle: str,
    ) -> Mapping[str, str]: ...


class MainExtension(ExtensionBase):
    """Optional Telegram transport with injectable host-governed dependencies."""

    def __init__(self, manifest: Any, context: Any) -> None:
        super().__init__(manifest, context)
        channel = getattr(manifest.capabilities, "communication_channel", None)
        if channel is None or type(channel.max_native_body_bytes) is not int:
            raise ValueError("Canonical channel manifest body budget required")
        self._native_body_limit = channel.max_native_body_bytes
        self._secret_resolver: HostSecretResolver | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._started: set[tuple[str, str, int]] = set()

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
            or _BOT_TOKEN.fullmatch(bot_token) is None
        ):
            raise PermissionError("Telegram channel credentials are incomplete")
        return webhook_secret, bot_token

    @staticmethod
    def _activation_key(connection: ChannelConnection) -> tuple[str, str, int]:
        return connection.tenant_id, connection.connection_id, connection.revision

    def _require_active(self, connection: ChannelConnection) -> None:
        if (
            not connection.enabled
            or self._activation_key(connection) not in self._started
            or self._http_client is None
        ):
            raise PermissionError("Telegram channel is not active in the governed host")

    async def start(self, *, connection: ChannelConnection) -> None:
        if not connection.enabled or self._http_client is None:
            raise PermissionError("Host must provision an enabled connection and network client")
        _, token = await self._secrets(connection)
        # Host authorization is not a claim that Telegram recognizes this bot.
        # Probe read-only identity before the channel activation CAS may commit.
        # The host-owned client enforces the configured network timeout and TLS.
        probe = getattr(self._http_client, "get", None)
        if not callable(probe):
            raise PermissionError("Telegram provider identity check unavailable")
        try:
            response = await probe(f"{_TELEGRAM_API_BASE}/bot{token}/getMe")
            if response.status_code != 200:
                raise PermissionError("Telegram provider identity check failed")
            data = response.json()
            identity = data.get("result") if isinstance(data, dict) else None
            if (
                data.get("ok") is not True
                or not isinstance(identity, dict)
                or type(identity.get("id")) is not int
                or identity["id"] <= 0
                or identity.get("is_bot") is not True
            ):
                raise PermissionError("Telegram provider identity check failed")
        except Exception:
            # Never leak bot tokens, native request URLs or provider body text.
            raise PermissionError("Telegram provider identity check failed") from None
        self._started.add(self._activation_key(connection))

    async def stop(self, *, connection: ChannelConnection) -> None:
        self._started = {
            key for key in self._started
            if key[:2] != (connection.tenant_id, connection.connection_id)
        }

    async def health(self, *, connection: ChannelConnection) -> Mapping[str, Any]:
        return {
            "transport": "telegram-bot",
            "running": connection.enabled and self._activation_key(connection) in self._started,
            "host_services_bound": self._secret_resolver is not None and self._http_client is not None,
        }

    async def inspect_webhook(
        self, *, connection: ChannelConnection,
    ) -> Mapping[str, Any]:
        """Read limited Telegram webhook evidence, never a connection claim.

        This is a privileged host-only diagnostic: native provider data cannot
        establish a trusted Karen endpoint or prove delivery. The actual URL,
        provider error text, token and native IP are deliberately not returned.
        """
        self._require_active(connection)
        _, token = await self._secrets(connection)
        try:
            response = await self._http_client.get(
                f"{_TELEGRAM_API_BASE}/bot{token}/getWebhookInfo"
            )
            if response.status_code != 200:
                raise ValueError("Provider webhook inspection failed")
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise ValueError("Provider webhook inspection failed")
            info = payload.get("result")
            if not isinstance(info, dict):
                raise ValueError("Provider webhook inspection failed")
            url = info.get("url")
            count = info.get("pending_update_count")
            if (
                not isinstance(url, str)
                or len(url) > 2048
                or type(count) is not int
                or not 0 <= count <= 1_000_000
            ):
                raise ValueError("Provider webhook inspection failed")
            registered = bool(url)
            matches_path = False
            if registered:
                parts = urlsplit(url)
                if (
                    parts.scheme != "https"
                    or not parts.hostname
                    or parts.username is not None
                    or parts.password is not None
                    or parts.query
                    or parts.fragment
                ):
                    raise ValueError("Provider webhook inspection failed")
                matches_path = parts.path == (
                    f"/api/channels/webhooks/{connection.tenant_id}/"
                    f"{connection.connection_id}"
                )
            error_date = info.get("last_error_date")
            if error_date is not None and (
                type(error_date) is not int or error_date < 0
            ):
                raise ValueError("Provider webhook inspection failed")
            return {
                "registered": registered,
                "path_matches": matches_path,
                "pending_update_count": count,
                "provider_reported_error": bool(error_date),
                "endpoint_origin_verified": False,
            }
        except Exception:
            # Provider errors and httpx request URLs can include bot secrets.
            raise PermissionError("Telegram webhook inspection unavailable") from None

    async def observe_registration(
        self, *, connection: ChannelConnection, public_origin: str,
    ) -> Mapping[str, bool]:
        """Read-only exact URL comparison with the host-owned HTTPS origin.

        A match is provider-reported registration evidence, never proof that
        Telegram delivered a signed inbound message to ChatRuntime.
        """
        self._require_active(connection)
        if not isinstance(public_origin, str):
            raise PermissionError("Telegram registration observation unavailable")
        expected = (
            f"{public_origin}/api/channels/webhooks/"
            f"{connection.tenant_id}/{connection.connection_id}"
        )
        _, token = await self._secrets(connection)
        try:
            response = await self._http_client.get(
                f"{_TELEGRAM_API_BASE}/bot{token}/getWebhookInfo"
            )
            if response.status_code != 200:
                raise ValueError("Provider inspection unavailable")
            payload = response.json()
            info = payload.get("result") if isinstance(payload, dict) else None
            if payload.get("ok") is not True or not isinstance(info, dict):
                raise ValueError("Provider inspection unavailable")
            url = info.get("url")
            if not isinstance(url, str) or len(url) > 2048:
                raise ValueError("Provider inspection unavailable")
            return {
                "provider_url_matches": url == expected,
                "provider_webhook_registered": bool(url),
                "live_connected": False,
            }
        except Exception:
            raise PermissionError("Telegram registration observation unavailable") from None

    async def identify_bot(
        self, *, connection: ChannelConnection,
    ) -> int:
        """Resolve the numeric provider identity under the trusted host Vault.

        The numeric ID is safe for database ownership; the secret token and
        provider response must never enter a log or HTTP response.
        """
        self._require_active(connection)
        _, token = await self._secrets(connection)
        try:
            response = await self._http_client.get(
                f"{_TELEGRAM_API_BASE}/bot{token}/getMe"
            )
            if response.status_code != 200:
                raise ValueError("Telegram bot identity unavailable")
            body = response.json()
            result = body.get("result") if isinstance(body, dict) else None
            if (
                body.get("ok") is not True
                or not isinstance(result, dict)
                or result.get("is_bot") is not True
                or type(result.get("id")) is not int
                or not 0 < result["id"] < 2**63
            ):
                raise ValueError("Telegram bot identity invalid")
            return result["id"]
        except Exception:
            raise PermissionError("Telegram bot identity verification unavailable") from None

    async def verify_registration_for_recovery(
        self, *, connection: ChannelConnection, public_origin: str,
    ) -> int:
        """Read provider bot and exact webhook using one Vault-resolved token.

        This is only a host-owned recovery observation. It cannot mutate the
        provider, unlink the bot, or prove inbound ChatRuntime delivery.
        """
        self._require_active(connection)
        if not isinstance(public_origin, str) or not public_origin.startswith(
            "https://"
        ):
            raise PermissionError("Telegram recovery verification unavailable")
        expected = (
            f"{public_origin}/api/channels/webhooks/"
            f"{connection.tenant_id}/{connection.connection_id}"
        )
        _, token = await self._secrets(connection)
        try:
            identity_response = await self._http_client.get(
                f"{_TELEGRAM_API_BASE}/bot{token}/getMe"
            )
            if identity_response.status_code != 200:
                raise ValueError("Bot identity unavailable")
            identity_body = identity_response.json()
            identity = (
                identity_body.get("result")
                if isinstance(identity_body, dict) else None
            )
            if (
                not isinstance(identity_body, dict)
                or identity_body.get("ok") is not True
                or not isinstance(identity, dict)
                or identity.get("is_bot") is not True
                or type(identity.get("id")) is not int
                or not 0 < identity["id"] < 2**63
            ):
                raise ValueError("Bot identity unavailable")
            webhook_response = await self._http_client.get(
                f"{_TELEGRAM_API_BASE}/bot{token}/getWebhookInfo"
            )
            if webhook_response.status_code != 200:
                raise ValueError("Webhook status unavailable")
            webhook_body = webhook_response.json()
            webhook = (
                webhook_body.get("result")
                if isinstance(webhook_body, dict) else None
            )
            if (
                not isinstance(webhook_body, dict)
                or webhook_body.get("ok") is not True
                or not isinstance(webhook, dict)
                or webhook.get("url") != expected
            ):
                raise ValueError("Webhook registration unverified")
            return identity["id"]
        except Exception:
            # Httpx errors may contain the bot token in their native URL.
            raise PermissionError("Telegram recovery verification unavailable") from None

    async def register_webhook(
        self, *, connection: ChannelConnection, public_origin: str,
        expected_bot_id: int,
    ) -> Mapping[str, bool]:
        """Explicit host-authorized setWebhook, followed by live read-back.

        The host is responsible for validating the configured public origin,
        fresh RuntimePolicy authorization, and connection revision fencing.
        Neither success nor an error proves inbound ChatRuntime delivery.
        """
        self._require_active(connection)
        if type(expected_bot_id) is not int or not 0 < expected_bot_id < 2**63:
            raise PermissionError("Telegram bot ownership verification unavailable")
        if (
            not isinstance(public_origin, str)
            or not public_origin.startswith("https://")
            or public_origin.endswith("/")
            or len(public_origin) > 300
        ):
            raise PermissionError("Telegram webhook registration unavailable")
        # Defense in depth: reject origin paths, credentials, and fragments
        # even when a noncanonical caller bypassed the host's configuration.
        try:
            origin_parts = urlsplit(public_origin)
            if (
                origin_parts.scheme != "https"
                or not origin_parts.hostname
                or origin_parts.netloc != origin_parts.hostname
                or origin_parts.path or origin_parts.query or origin_parts.fragment
                or origin_parts.username is not None
                or origin_parts.password is not None
                or origin_parts.port is not None
            ):
                raise ValueError("Invalid registered origin")
        except (ValueError, TypeError, AttributeError):
            raise PermissionError("Telegram webhook registration unavailable") from None
        signing_secret, token = await self._secrets(connection)
        destination = (
            f"{public_origin}/api/channels/webhooks/"
            f"{connection.tenant_id}/{connection.connection_id}"
        )
        try:
            # Credential rotation between host identity reservation and this
            # Vault resolution must not redirect a webhook to another bot.
            # The SAME resolved token is used for the identity recheck and
            # the mutation. No provider write occurs if IDs differ.
            proof = await self._http_client.get(
                f"{_TELEGRAM_API_BASE}/bot{token}/getMe"
            )
            if proof.status_code != 200:
                raise ValueError("Telegram bot ownership changed")
            identity_payload = proof.json()
            identity = (
                identity_payload.get("result")
                if isinstance(identity_payload, dict) else None
            )
            if (
                identity_payload.get("ok") is not True
                or not isinstance(identity, dict)
                or identity.get("is_bot") is not True
                or type(identity.get("id")) is not int
                or identity["id"] != expected_bot_id
            ):
                raise ValueError("Telegram bot ownership changed")
            response = await self._http_client.post(
                f"{_TELEGRAM_API_BASE}/bot{token}/setWebhook",
                json={
                    "url": destination,
                    "secret_token": signing_secret,
                    "allowed_updates": ["message"],
                    "drop_pending_updates": False,
                },
            )
            if response.status_code != 200:
                raise ValueError("Telegram refused webhook registration")
            accepted = response.json()
            if (
                not isinstance(accepted, dict)
                or accepted.get("ok") is not True
                or accepted.get("result") is not True
            ):
                raise ValueError("Telegram did not confirm webhook registration")
            proof = await self._http_client.get(
                f"{_TELEGRAM_API_BASE}/bot{token}/getWebhookInfo"
            )
            if proof.status_code != 200:
                raise ValueError("Telegram webhook read-back failed")
            payload = proof.json()
            info = payload.get("result") if isinstance(payload, dict) else None
            if (
                payload.get("ok") is not True
                or not isinstance(info, dict)
                or info.get("url") != destination
            ):
                raise ValueError("Telegram webhook URL did not match")
            # This is remote registration evidence only, not a delivery test.
            return {"provider_registration_verified": True, "live_connected": False}
        except Exception:
            # The POST may have succeeded even if the read-back timed out.
            # Caller receives an explicit UNKNOWN result, not an invented
            # rollback, and never provider text or token-bearing URLs.
            raise PermissionError("Telegram webhook registration unverified") from None

    async def verify_event(
        self, *, connection: ChannelConnection,
        headers: Mapping[str, str], body: bytes,
    ) -> bool:
        self._require_active(connection)
        if len(body) > self._native_body_limit or not body:
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
        if len(body) > self._native_body_limit:
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
        if 400 <= response.status_code < 500:
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id,
                state=ChannelDeliveryState.FAILED,
                error_code="telegram_request_rejected",
            )
        if response.status_code != 200:
            # Redirects and unexpected 2xx statuses are not provider evidence.
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id,
                state=ChannelDeliveryState.UNKNOWN,
                error_code="telegram_receipt_unverified",
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
        if (
            not isinstance(sent, dict)
            or type(sent.get("message_id")) is not int
            or sent["message_id"] <= 0
        ):
            return ChannelDeliveryReceipt(
                delivery_id=delivery.delivery_id,
                state=ChannelDeliveryState.UNKNOWN,
                error_code="telegram_receipt_unverified",
            )
        result_chat = sent.get("chat")
        if (
            not isinstance(result_chat, dict)
            or type(result_chat.get("id")) is not int
            or result_chat["id"] != chat_id
        ):
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

from __future__ import annotations

"""Core-owned provider execution for canonical runtime endpoints.

This module depends on Core contracts and the shared asynchronous HTTP client. Extensions and integrations may register/configure endpoints, but Core
never imports their implementations to execute a model request.
"""

import asyncio
import json
import os
import ipaddress
import socket
import time
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpoint
from ai_karen_engine.core.model_runtime.runtime_engine import (
    EndpointKind,
    EndpointProtocol,
    Locality,
    RuntimeEngine,
)

if TYPE_CHECKING:
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan


@dataclass(frozen=True)
class ProviderExecutionResult:
    text: str
    model: str | None
    provider_id: str
    runtime_engine: str | None
    usage: dict[str, int] | None = None
    finish_reason: str | None = None


class ProviderExecutionError(RuntimeError):
    """Raised when a canonical provider endpoint cannot execute a request."""

    # Only the transport observer may set this after shared-health admission.
    shared_health_failure_observed: bool = False


class _HttpExecutionObservation:
    """Own one terminal observation, not a reservation or inferred dispatch.

    The client handoff starts the latency clock. A response or a classified
    network exception supplies evidence. Local deadlines, cancellation,
    request-specific HTTP rejection and unknown errors remain neutral.
    """

    _INVALID_RESPONSE_CODES = frozenset({
        "provider_invalid_response_object", "provider_response_too_large",
        "provider_response_unverified_model", "provider_response_requested_model_mismatch",
        "provider_response_unsupported_choices", "provider_response_invalid_choice",
        "provider_response_invalid_message", "provider_response_non_assistant_role",
        "provider_response_invalid_content", "provider_response_invalid_finish_reason",
        "tool_call_response_has_no_choices", "tool_call_response_invalid_choice",
        "tool_call_response_invalid_assistant", "tool_call_response_invalid_content",
        "tool_call_model_changed_unexpectedly",
        "provider_stream_invalid_content_type", "provider_stream_invalid_json",
        "provider_stream_invalid_event", "provider_stream_invalid_model",
        "provider_stream_model_switched", "provider_stream_requested_model_mismatch",
        "provider_stream_invalid_choices", "provider_stream_unsupported_choices",
        "provider_stream_unexpected_choice_index", "provider_stream_invalid_delta",
        "provider_stream_non_assistant_role", "provider_stream_invalid_content",
        "provider_stream_invalid_finish_reason", "provider_stream_invalid_frame",
        "provider_stream_data_after_finish", "provider_stream_unverified_model",
        "provider_stream_incomplete_frame", "provider_stream_incomplete",
        "provider_stream_unverified_completion",
    })

    def __init__(
        self, endpoint: ProviderEndpoint, *, transport: str, shared: bool,
    ) -> None:
        self.endpoint = endpoint
        self.transport = transport
        self.shared = shared and endpoint.tenant_scoped is False
        self.started: float | None = None
        self.registration: object | None = None
        self.response_status: int | None = None
        self.connection_failed = False
        self.finished = False

    def __enter__(self) -> _HttpExecutionObservation:
        return self

    def handoff(self) -> None:
        if self.shared:
            try:
                from ai_karen_engine.core.model_runtime.provider_health_monitor import (
                    get_health_monitor,
                )
                self.registration = get_health_monitor().capture_endpoint_registration(self.endpoint)
            except Exception:
                # Evidence failure cannot change execution admission.
                self.registration = None
        self.started = time.perf_counter()

    def note_http_error(self, exc: BaseException) -> None:
        import httpx

        # Pool saturation, invalid client options and local protocol errors
        # are not evidence of endpoint failure.
        self.connection_failed = isinstance(exc, (
            httpx.ConnectError, httpx.ReadError, httpx.WriteError,
            httpx.RemoteProtocolError, httpx.ConnectTimeout,
            httpx.ReadTimeout, httpx.WriteTimeout,
        ))

    def _record(self, outcome: str) -> bool:
        if self.finished or self.started is None or not self.shared:
            return False
        self.finished = True
        try:
            from ai_karen_engine.core.model_runtime.provider_health_monitor import (
                get_health_monitor,
            )
            return get_health_monitor().record_shared_http_execution(
                self.endpoint, transport=self.transport, outcome=outcome,
                response_time=time.perf_counter() - self.started,
                registration=self.registration,
            )
        except Exception:
            # Observation is never a model-execution dependency.
            return False

    def complete(self) -> None:
        if self.response_status is not None and 200 <= self.response_status < 300:
            self._record("success")

    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        if not isinstance(exc, ProviderExecutionError):
            return
        status = self.response_status
        outcome = None
        if status is not None and 500 <= status < 600:
            outcome = "http_server_error"
        elif self.connection_failed and (status is None or 200 <= status < 300):
            outcome = "connection_failure"
        elif (
            status is not None and 200 <= status < 300
            and str(exc) in self._INVALID_RESPONSE_CODES
        ):
            outcome = "invalid_provider_response"
        if outcome is not None:
            exc.shared_health_failure_observed = self._record(outcome)


@dataclass(frozen=True, slots=True, repr=False)
class PersonalModelTransportGrant:
    """Host-only execution identity. No secret or client-supplied bearer.

    This is an invocation descriptor, not a grant issuer. Identity Vault still
    validates the exact RuntimePolicy plan and commits its secret-access audit.
    The canonical chat runtime does not issue such grants yet.
    """

    context: "ChatExecutionContext"
    plan: "AuthorizedExecutionPlan"
    credential_id: UUID
    provider_id: str
    model_id: str


async def _resolve_personal_transport_key(
    endpoint: ProviderEndpoint,
    model: str | None,
    grant: PersonalModelTransportGrant,
) -> str:
    """Resolve a fresh personal credential for exactly this host invocation.

    Never trust a supplied endpoint URL. Only the registered HTTPS external
    vendor endpoint may receive personal credentials, and never a local,
    custom, plugin-owned, redirected or fallback endpoint.
    """
    denial = "personal_model_transport_denied"
    if (
        not isinstance(grant, PersonalModelTransportGrant)
        or not isinstance(model, str)
        or not model
        or model == "auto"
        or model != grant.model_id
        or endpoint.provider_id != grant.provider_id
        or not endpoint.enabled
        or endpoint.tenant_scoped is not True
        or endpoint.fallback_eligible is not False
        or endpoint.kind is not EndpointKind.CLOUD_PROVIDER
        or endpoint.runtime_engine is not RuntimeEngine.REMOTE_API
        or endpoint.protocol is not EndpointProtocol.OPENAI_COMPATIBLE
        or endpoint.metadata.get("configuration_owner") != "llm_provider_config"
        or not endpoint.api_key_env
    ):
        raise ProviderExecutionError(denial)

    try:
        from ai_karen_engine.config.llm_provider_config import (
            AuthenticationType,
            OPENAI_COMPATIBLE_PROVIDER_DEFAULTS,
            ProviderType,
            get_provider_config_manager,
        )
        from ai_karen_engine.services.identity_vault.credential_vault_service import (
            get_credential_vault_service,
        )

        approved = OPENAI_COMPATIBLE_PROVIDER_DEFAULTS.get(endpoint.provider_id)
        if not isinstance(approved, dict):
            raise ProviderExecutionError(denial)
        approved_url = str(approved.get("base_url") or "").rstrip("/")
        base_url = str(endpoint.base_url or "").rstrip("/")
        parsed = urlsplit(base_url)
        if (
            not approved_url
            or base_url != approved_url
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or endpoint.api_key_env != approved.get("api_key_env")
        ):
            raise ProviderExecutionError(denial)

        # The registry endpoint may have been obtained before an administrator
        # disabled or changed its provider. Re-read the canonical current
        # provider definition immediately before the Vault resolution.
        # Unlike workspace credential resolution, a personal key does not
        # require an unrelated workspace API key to be configured.
        config = get_provider_config_manager().get_provider(endpoint.provider_id)
        if (
            config is None
            or not config.enabled
            or config.provider_type != ProviderType.EXTERNAL
            or config.authentication is None
            or config.authentication.type != AuthenticationType.API_KEY
            or config.authentication.api_key_env_var != endpoint.api_key_env
            or config.endpoint is None
            or str(config.endpoint.base_url or "").rstrip("/") != approved_url
        ):
            raise ProviderExecutionError(denial)

        key = await get_credential_vault_service().resolve_authorized_personal_model_key(
            context=grant.context,
            plan=grant.plan,
            credential_id=grant.credential_id,
            provider_id=grant.provider_id,
            model_id=grant.model_id,
        )
        if not isinstance(key, str) or not key or key != key.strip():
            raise ProviderExecutionError(denial)
        return key
    except Exception:
        # Includes an audit-commit failure. Never surface raw Vault/transport
        # exceptions or secret contents to a model, consumer, log or receipt.
        raise ProviderExecutionError(denial) from None


class _RejectProviderRedirect(HTTPRedirectHandler):
    """Prevent urllib from forwarding bearer headers to redirect targets."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _require_safe_provider_destination(url: str, *, wire_host: str | None = None) -> None:
    """Shared literal/authority guard for blocking and asynchronous HTTP.

    DNS resolution and socket pinning are deliberately outside this guard.
    This validates the destination syntax, not permission to execute inference.
    """
    # External RuntimePolicy authorization is not permission to contact cloud
    # instance metadata or interface-local addresses. Reject these wire targets
    # even for an otherwise authorized external provider attempt. This is an
    # IP-literal guard; DNS resolution and socket pinning require separate proof.
    # urllib.Request decodes percent-escaped authority text when setting
    # request.host, while urlsplit(request.full_url).hostname leaves it encoded.
    # Never classify one host and connect to another. Reject encoded
    # authorities and mismatched Request hosts before opener construction.
    try:
        # urlsplit and HTTP clients can normalize controls differently.
        if any(ord(char) <= 32 or ord(char) == 127 for char in url) or "\\" in url:
            raise ValueError("invalid provider URL")
        parsed = urlsplit(url)
        parsed_hostname = parsed.hostname
        parsed.port  # validate port syntax and range before constructing a client
    except ValueError:
        raise ProviderExecutionError("provider_destination_not_allowed") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed_hostname
        or "%" in parsed.netloc
        # libc's IDNA conversion can normalize Unicode digits/dot lookalikes
        # into a forbidden numeric IP, bypassing ipaddress and inet_aton.
        # Configured IDN servers must use their canonical ASCII/punycode host.
        or not parsed.netloc.isascii()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (wire_host is not None and wire_host.lower() != parsed.netloc.lower())
    ):
        raise ProviderExecutionError("provider_destination_not_allowed")
    try:
        destination = ipaddress.ip_address(parsed_hostname)
    except ValueError:
        # libc's IPv4 parser accepts noncanonical numeric aliases that
        # ipaddress rejects (decimal dword, hexadecimal and octal forms).
        # urllib's resolver can send those directly to metadata addresses.
        # Reject every such alias before constructing an HTTP opener, even
        # for otherwise authorized external provider execution. inet_aton
        # parses numeric IPv4 only; it performs no DNS lookup.
        try:
            socket.inet_aton(parsed_hostname)
        except OSError:
            destination = None
        else:
            raise ProviderExecutionError("provider_destination_not_allowed")
    if isinstance(destination, ipaddress.IPv6Address) and destination.ipv4_mapped:
        destination = destination.ipv4_mapped
    if destination is not None and (
        destination.is_link_local
        or destination.is_unspecified
        or destination.is_multicast
    ):
        raise ProviderExecutionError("provider_destination_not_allowed")



def _open_provider_request(request: Request, timeout: float):
    """Use a fresh, no-redirect and metadata-safe provider HTTP opener."""
    _require_safe_provider_destination(request.full_url, wire_host=request.host)
    # urllib otherwise installs its default ProxyHandler, which honors
    # ambient HTTP(S)_PROXY / ALL_PROXY. An apparently local approved
    # endpoint could therefore egress through an unapproved proxy and
    # disclose prompt text or an endpoint-specific bearer credential.
    # Explicit governed proxy configuration must be a separate policy owner.
    return build_opener(_RejectProviderRedirect(), ProxyHandler({})).open(
        request, timeout=timeout
    )


def discover_openai_compatible_model_ids(
    base_url: str, *, api_key: str | None, timeout_seconds: float = 3.0,
) -> list[str]:
    """Read actual /models inventory without fallback, inference, or health writes.

    The caller owns endpoint and credential authorization. Never consult
    ambient provider credentials or merge configured model hints into evidence.
    """
    url = base_url.rstrip("/") + "/models"
    _require_safe_provider_destination(url)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, headers=headers, method="GET")
    max_bytes = 4 * 1024 * 1024
    with _open_provider_request(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise ProviderExecutionError("provider_inventory_unavailable")
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ProviderExecutionError("provider_inventory_response_too_large")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ProviderExecutionError("provider_inventory_invalid_response") from None
    if (
        not isinstance(body, dict)
        or body.get("error") is not None
        or not isinstance(body.get("data"), list)
    ):
        raise ProviderExecutionError("provider_inventory_invalid_response")
    ids: list[str] = []
    for item in body["data"]:
        model_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(model_id, str) or not model_id.strip():
            raise ProviderExecutionError("provider_inventory_invalid_model")
        ids.append(model_id)
    return list(dict.fromkeys(ids))


def _inherit_registered_api_path(
    runtime_url: str,
    registered_url: str | None,
) -> str:
    """Preserve the canonical API path when a runtime override only changes host.

    Environment overrides commonly point at a Docker/host gateway origin.
    Built-in OpenAI-compatible endpoints register their required API prefix
    (for example /v1). Treat a host-only override as a host replacement
    rather than silently dropping that prefix. Explicit override paths remain
    authoritative.
    """
    normalized = runtime_url.rstrip("/")
    if not registered_url:
        return normalized

    runtime_parts = urlsplit(normalized)
    if runtime_parts.path not in {"", "/"}:
        return normalized

    registered_parts = urlsplit(registered_url.rstrip("/"))
    registered_path = registered_parts.path.rstrip("/")
    if not registered_path:
        return normalized

    return urlunsplit(
        (
            runtime_parts.scheme,
            runtime_parts.netloc,
            registered_path,
            runtime_parts.query,
            runtime_parts.fragment,
        )
    ).rstrip("/")


def _resolve_base_url(endpoint: ProviderEndpoint) -> str | None:
    env_names = {
        RuntimeEngine.VLLM: ("VLLM_BASE_URL", "KAREN_VLLM_BASE_URL"),
        RuntimeEngine.LMSTUDIO: ("LMSTUDIO_BASE_URL", "LM_STUDIO_BASE_URL"),
        RuntimeEngine.OLLAMA: ("OLLAMA_BASE_URL",),
        RuntimeEngine.LLAMACPP: ("LLAMACPP_BASE_URL", "LLAMA_CPP_BASE_URL"),
    }
    defaults = {
        RuntimeEngine.VLLM: "http://localhost:8000/v1",
        RuntimeEngine.LMSTUDIO: "http://localhost:1234/v1",
        RuntimeEngine.OLLAMA: "http://localhost:11434/v1",
        RuntimeEngine.LLAMACPP: "http://localhost:8080/v1",
    }

    for env_name in env_names.get(endpoint.runtime_engine, ()):
        value = (os.getenv(env_name) or "").strip()
        if value:
            return _inherit_registered_api_path(value, endpoint.base_url)

    if endpoint.base_url:
        return endpoint.base_url.rstrip("/")
    return defaults.get(endpoint.runtime_engine)


# A configured OpenAI-compatible endpoint is not necessarily local. Use
# the effective transport URL (including approved host environment overrides),
# not registry defaults or self-described endpoint locality, to classify it.
# Named Docker host bridges are trusted installation-local aliases; other DNS
# names require RuntimePolicy external execution permission unless separately
# admitted by a future governed destination inventory.
_LOCAL_PROVIDER_HOSTS = frozenset({
    "localhost", "host.docker.internal", "gateway.docker.internal",
    "host.containers.internal",
})
# Never classify link-local destinations as trusted local model servers.
# IPv4 169.254/16 includes cloud instance metadata; IPv6 fe80::/10 is
# interface-scoped and must not bypass RuntimePolicy merely for being local.
_LOCAL_PROVIDER_NETWORKS = tuple(ipaddress.ip_network(net) for net in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "::1/128", "fc00::/7",
))


def provider_endpoint_requires_external_permission(endpoint: ProviderEndpoint) -> bool:
    """Classify the actual model transport destination, failing closed.

    Kind/locality describe configured intent; the effective URL is the wire
    destination. An endpoint labeled local with a public/unknown host must not
    bypass installation external opt-out or authenticated administrator RBAC.
    Return True for unknown or malformed targets, never infer cloud permission.
    """
    return _resolved_destination_requires_external_permission(endpoint, _resolve_base_url(endpoint))


def _resolved_destination_requires_external_permission(
    endpoint: ProviderEndpoint, url: str | None,
) -> bool:
    """Classify exactly the URL that will be used by the transport."""
    if (
        endpoint.kind is EndpointKind.CLOUD_PROVIDER
        or endpoint.locality is Locality.CLOUD
        or endpoint.runtime_engine is RuntimeEngine.REMOTE_API
    ):
        return True
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        if (
            parsed is None
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            return True
        host = parsed.hostname.rstrip(".").lower()
        if host in _LOCAL_PROVIDER_HOSTS:
            return False
        address = ipaddress.ip_address(host)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return not any(address in network for network in _LOCAL_PROVIDER_NETWORKS)
    except (ValueError, TypeError):
        # Unknown DNS hostnames and invalid URLs never imply local authority.
        return True


def _resolve_api_key(endpoint: ProviderEndpoint) -> str | None:
    """Resolve a credential through its configured owner at execution time.

    Workspace credentials stored through Application Settings must reach both
    regular and streamed requests without environment mutation or stale global
    key caches. Governed endpoints fail closed when their bound credential is
    missing or the current provider configuration no longer authorizes them.
    """
    if not endpoint.api_key_env:
        return None

    if endpoint.metadata.get("configuration_owner") == "llm_provider_config":
        try:
            from ai_karen_engine.config.llm_provider_config import (
                get_provider_config_manager,
            )

            manager = get_provider_config_manager()
            config = manager.get_provider(endpoint.provider_id)
            if (
                config is None
                or not config.enabled
                or config.authentication is None
                or config.authentication.api_key_env_var != endpoint.api_key_env
                or config.endpoint is None
                or str(config.endpoint.base_url or "").rstrip("/")
                != str(endpoint.base_url or "").rstrip("/")
                or not manager.is_provider_configured(endpoint.provider_id)
            ):
                return None
            return manager.get_api_key(endpoint.provider_id)
        except Exception:
            return None

    # Explicitly registered runtime endpoints retain their existing
    # environment credential contract. No cross-provider secret lookup.
    value = (os.getenv(endpoint.api_key_env) or "").strip()
    return value or None


# Bound the decoded JSON envelope, including tool arguments and metadata.
# This is a wire-safety ceiling, independent of the provider's token budget.
_MAX_COMPLETION_RESPONSE_BYTES = 2 * 1024 * 1024


def _provider_headers(
    endpoint: ProviderEndpoint, personal_key: str | None, *, accept: str,
) -> dict[str, str]:
    headers = {"Accept": accept, "Content-Type": "application/json"}
    api_key = personal_key if personal_key is not None else _resolve_api_key(endpoint)
    if endpoint.api_key_env and not api_key:
        raise ProviderExecutionError(
            f"provider_credential_unavailable:{endpoint.provider_id}"
        )
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _provider_http_client(timeout_seconds: float):
    import httpx

    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds), follow_redirects=False, trust_env=False,
    )


async def _post_chat_completions(
    endpoint: ProviderEndpoint,
    base_url: str,
    payload: dict[str, Any],
    *,
    personal_key: str | None = None,
    observation: _HttpExecutionObservation | None = None,
) -> dict[str, Any]:
    """Bounded asynchronous JSON transport for text and structured-tool models."""
    import httpx

    _require_safe_provider_destination(base_url)
    headers = _provider_headers(endpoint, personal_key, accept="application/json")
    total_seconds = endpoint.timeout_seconds
    raw = bytearray()
    try:
        async with asyncio.timeout(total_seconds):
            async with _provider_http_client(total_seconds) as client:
                if observation is not None:
                    observation.handoff()
                async with client.stream(
                    "POST", f"{base_url}/chat/completions", json=payload, headers=headers,
                ) as response:
                    if observation is not None:
                        observation.response_status = response.status_code
                    if not 200 <= response.status_code < 300:
                        raise ProviderExecutionError(
                            f"provider_http_error:{endpoint.provider_id}:{response.status_code}"
                        )
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if len(raw) + len(chunk) > _MAX_COMPLETION_RESPONSE_BYTES:
                            raise ProviderExecutionError("provider_response_too_large")
                        raw.extend(chunk)
    except TimeoutError:
        raise ProviderExecutionError("provider_deadline_exceeded") from None
    except httpx.HTTPError as exc:
        if observation is not None:
            observation.note_http_error(exc)
        raise ProviderExecutionError(
            f"provider_connection_error:{endpoint.provider_id}"
        ) from None
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise ProviderExecutionError("provider_invalid_response_object") from None
    if not isinstance(body, dict):
        raise ProviderExecutionError("provider_invalid_response_object")
    return body


@dataclass(frozen=True)
class StructuredChatResult:
    """Canonical structured output, retaining provider-emitted tool calls."""

    message: dict[str, Any]
    provider_id: str
    model: str
    runtime_engine: str
    finish_reason: str | None
    usage: dict[str, int]


async def _request_structured_chat(
    endpoint: ProviderEndpoint,
    *,
    messages: Sequence[Mapping[str, Any]],
    model: str,
    tools: Sequence[Mapping[str, Any]],
    max_tokens: int,
    temperature: float,
    personal_key: str | None = None,
    observation: _HttpExecutionObservation | None = None,
) -> StructuredChatResult:
    """Emit only explicitly registered tools, never model-side fake calls."""
    if endpoint.protocol is not EndpointProtocol.OPENAI_COMPATIBLE:
        raise ProviderExecutionError("tool_call_protocol_unsupported")
    if not endpoint.enabled or "tools" not in set(endpoint.capabilities):
        raise ProviderExecutionError("tool_call_provider_not_eligible")
    if not model or model == "auto":
        raise ProviderExecutionError("tool_call_model_identity_required")
    base_url = _resolve_base_url(endpoint)
    if not base_url:
        raise ProviderExecutionError("tool_call_endpoint_unavailable")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [dict(message) for message in messages],
        "tools": [dict(tool) for tool in tools],
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    body = await _post_chat_completions(
        endpoint, base_url, payload, personal_key=personal_key, observation=observation,
    )
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderExecutionError("tool_call_response_has_no_choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ProviderExecutionError("tool_call_response_invalid_choice")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ProviderExecutionError("tool_call_response_invalid_assistant")
    tool_calls = message.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        raise ProviderExecutionError("tool_call_response_invalid_calls")
    verified_calls: list[dict[str, Any]] = []
    allowed = {
        tool.get("function", {}).get("name")
        for tool in tools if isinstance(tool.get("function"), dict)
    }
    for call in tool_calls:
        if not isinstance(call, dict):
            raise ProviderExecutionError("tool_call_response_invalid_call")
        function = call.get("function")
        if (
            not isinstance(function, dict)
            or not isinstance(call.get("id"), str)
            or not call["id"]
            or function.get("name") not in allowed
            or not isinstance(function.get("arguments"), str)
        ):
            raise ProviderExecutionError("tool_call_response_unknown_tool")
        try:
            arguments = json.loads(function["arguments"])
        except (ValueError, TypeError) as exc:
            raise ProviderExecutionError("tool_call_response_invalid_arguments") from exc
        if not isinstance(arguments, dict):
            raise ProviderExecutionError("tool_call_response_arguments_not_object")
        verified_calls.append({
            "id": call["id"],
            "name": function["name"],
            "args": arguments,
        })
    content = message.get("content") or ""
    if not isinstance(content, str):
        raise ProviderExecutionError("tool_call_response_invalid_content")
    if not content.strip() and not verified_calls:
        raise ProviderExecutionError("tool_call_response_empty")
    usage: dict[str, int] = {}
    if isinstance(body.get("usage"), dict):
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = body["usage"].get(key)
            if isinstance(value, int) and value >= 0:
                usage[key] = value
    actual_model = str(body.get("model") or model)
    if actual_model != model:
        raise ProviderExecutionError("tool_call_model_changed_unexpectedly")
    # Preserve the legacy structured result contract, but a requested-model
    # default is not observed model identity and must not certify health.
    if observation is not None and body.get("model") == model:
        observation.complete()
    return StructuredChatResult(
        message={"content": content, "tool_calls": verified_calls},
        provider_id=endpoint.provider_id,
        model=actual_model,
        runtime_engine=endpoint.runtime_engine.value,
        finish_reason=str(choice.get("finish_reason") or "") or None,
        usage=usage,
    )


async def execute_structured_provider_endpoint(
    endpoint: ProviderEndpoint,
    *,
    messages: Sequence[Mapping[str, Any]],
    model: str,
    tools: Sequence[Mapping[str, Any]],
    max_tokens: int,
    temperature: float,
    personal_model_grant: PersonalModelTransportGrant | None = None,
) -> StructuredChatResult:
    """Canonical provider transport used by governed LangChain adapters."""
    personal_key = (
        await _resolve_personal_transport_key(endpoint, model, personal_model_grant)
        if personal_model_grant is not None else None
    )
    with _HttpExecutionObservation(
        endpoint, transport="structured", shared=personal_model_grant is None,
    ) as observation:
        return await _request_structured_chat(
            endpoint,
            messages=messages,
            model=model,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            personal_key=personal_key,
            observation=observation,
        )


async def _request_text_chat(
    endpoint: ProviderEndpoint,
    *,
    messages: Sequence[Mapping[str, str]],
    model: str | None,
    max_tokens: int,
    temperature: float,
    personal_key: str | None = None,
    local_only: bool = False,
    observation: _HttpExecutionObservation | None = None,
) -> ProviderExecutionResult:
    base_url = _resolve_base_url(endpoint)
    if local_only and _resolved_destination_requires_external_permission(endpoint, base_url):
        raise ProviderExecutionError("private_evidence_local_only")
    if not base_url:
        raise ProviderExecutionError(
            f"provider_endpoint_missing_base_url:{endpoint.provider_id}"
        )

    request_model = model or endpoint.default_model
    if request_model == "auto":
        request_model = None

    payload: dict[str, Any] = {
        "messages": [dict(message) for message in messages],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if request_model:
        payload["model"] = request_model

    body = await _post_chat_completions(
        endpoint, base_url, payload, personal_key=personal_key, observation=observation,
    )

    # Non-streaming chat must prove the same model and assistant-content
    # identity as the native SSE terminal contract. Never manufacture an
    # observed model from the requested/default model or stringify structured
    # payloads into apparent assistant speech.
    reported_model = body.get("model")
    if not isinstance(reported_model, str) or not reported_model.strip():
        raise ProviderExecutionError("provider_response_unverified_model")
    if request_model is not None and reported_model != request_model:
        raise ProviderExecutionError("provider_response_requested_model_mismatch")

    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ProviderExecutionError("provider_response_unsupported_choices")
    first = choices[0]
    if not isinstance(first, dict) or first.get("index", 0) != 0:
        raise ProviderExecutionError("provider_response_invalid_choice")
    message = first.get("message")
    if message is None:
        message = {}
    if not isinstance(message, dict):
        raise ProviderExecutionError("provider_response_invalid_message")
    if message.get("role") not in (None, "assistant"):
        raise ProviderExecutionError("provider_response_non_assistant_role")
    if message.get("tool_calls") or message.get("function_call"):
        raise ProviderExecutionError("provider_response_tool_call_not_authorized")

    content = message.get("content")
    if content is None:
        content = first.get("text")
    if not isinstance(content, str):
        raise ProviderExecutionError("provider_response_invalid_content")
    text = content.strip()
    if not text:
        raise ProviderExecutionError(
            f"provider_empty_response:{endpoint.provider_id}"
        )
    finish_reason = first.get("finish_reason")
    if finish_reason is not None and (
        not isinstance(finish_reason, str) or not finish_reason
    ):
        raise ProviderExecutionError("provider_response_invalid_finish_reason")

    raw_usage = body.get("usage")
    usage = None
    if isinstance(raw_usage, dict):
        usage = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = raw_usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                usage[key] = value
        if not usage:
            usage = None

    return ProviderExecutionResult(
        text=text,
        model=reported_model,
        provider_id=endpoint.provider_id,
        runtime_engine=endpoint.runtime_engine.value,
        usage=usage,
        finish_reason=finish_reason,
    )


async def execute_provider_endpoint(
    endpoint: ProviderEndpoint,
    *,
    messages: Sequence[Mapping[str, str]],
    model: str | None,
    max_tokens: int,
    temperature: float,
    personal_model_grant: PersonalModelTransportGrant | None = None,
    local_only: bool = False,
) -> ProviderExecutionResult:
    """Execute a canonical endpoint without importing extension implementations."""

    if endpoint.protocol is not EndpointProtocol.OPENAI_COMPATIBLE:
        raise ProviderExecutionError(
            f"unsupported_core_provider_protocol:{endpoint.provider_id}:{endpoint.protocol.value}"
        )

    personal_key = (
        await _resolve_personal_transport_key(endpoint, model, personal_model_grant)
        if personal_model_grant is not None else None
    )
    with _HttpExecutionObservation(
        endpoint, transport="text", shared=personal_model_grant is None,
    ) as observation:
        result = await _request_text_chat(
            endpoint,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            personal_key=personal_key,
            observation=observation,
            **({"local_only": True} if local_only else {}),
        )
        observation.complete()
        return result


@dataclass(frozen=True)
class ProviderStreamEvent:
    """One observed OpenAI-compatible wire delta or verified terminal receipt."""

    kind: Literal["delta", "complete"]
    delta: str = ""
    result: ProviderExecutionResult | None = None


def _decode_stream_event(
    raw_payload: str,
    *,
    expected_model: str | None,
    observed_model: str | None,
) -> tuple[str, str | None, dict[str, int], str | None]:
    """Validate one SSE JSON event; never elevate model tool calls to chat text."""
    try:
        payload = json.loads(raw_payload)
    except (ValueError, TypeError) as exc:
        raise ProviderExecutionError("provider_stream_invalid_json") from exc
    if not isinstance(payload, dict):
        raise ProviderExecutionError("provider_stream_invalid_event")

    reported = payload.get("model")
    if reported is not None:
        if not isinstance(reported, str) or not reported.strip():
            raise ProviderExecutionError("provider_stream_invalid_model")
        # An explicitly selected model is part of the execution contract.
        # Do not silently elevate a different reported executor to its receipt.
        # Once an initially verified model is observed, a later change is
        # a mid-stream model switch. The first mismatching receipt remains a
        # requested-model mismatch; both cases fail closed before projection.
        if observed_model is not None and reported != observed_model:
            raise ProviderExecutionError("provider_stream_model_switched")
        if expected_model is not None and reported != expected_model:
            raise ProviderExecutionError("provider_stream_requested_model_mismatch")
        observed_model = reported

    raw_usage = payload.get("usage")
    usage: dict[str, int] = {}
    if isinstance(raw_usage, dict):
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = raw_usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                usage[key] = value

    choices = payload.get("choices", [])
    if not isinstance(choices, list):
        raise ProviderExecutionError("provider_stream_invalid_choices")
    # Final usage events are allowed to have no choices.
    if not choices:
        return "", None, usage, observed_model
    if len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderExecutionError("provider_stream_unsupported_choices")
    first = choices[0]
    if first.get("index", 0) != 0:
        raise ProviderExecutionError("provider_stream_unexpected_choice_index")
    delta = first.get("delta") or {}
    if not isinstance(delta, dict):
        raise ProviderExecutionError("provider_stream_invalid_delta")
    if delta.get("tool_calls") or delta.get("function_call"):
        raise ProviderExecutionError("provider_stream_tool_call_not_authorized")
    if delta.get("role") not in (None, "assistant"):
        raise ProviderExecutionError("provider_stream_non_assistant_role")
    content = delta.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise ProviderExecutionError("provider_stream_invalid_content")
    reason = first.get("finish_reason")
    if reason is not None:
        if not isinstance(reason, str) or not reason:
            raise ProviderExecutionError("provider_stream_invalid_finish_reason")
    return content, reason, usage, observed_model


async def stream_provider_endpoint(
    endpoint: ProviderEndpoint,
    *,
    messages: Sequence[Mapping[str, str]],
    model: str | None,
    max_tokens: int,
    temperature: float,
    timeout_ms: int,
    personal_model_grant: PersonalModelTransportGrant | None = None,
    local_only: bool = False,
) -> AsyncIterator[ProviderStreamEvent]:
    """Stream actual provider tokens from the existing canonical endpoint.

    Registry eligibility, action/RBAC gates, prompt assembly, model selection,
    and transcript ownership remain with their existing owners. This method
    only implements OpenAI-compatible HTTP event transport. No fallback to a
    fake model answer, no automatic network retry, and no local message store.

    A cancelled consumer closes the HTTP response through async context
    managers. An incomplete stream raises without a terminal receipt, so the
    chat runtime must not persist an allegedly completed response.
    """
    if endpoint.protocol is not EndpointProtocol.OPENAI_COMPATIBLE:
        raise ProviderExecutionError("unsupported_core_provider_protocol")
    if not endpoint.enabled or not endpoint.supports_streaming:
        raise ProviderExecutionError("provider_stream_not_supported")
    if max_tokens <= 0 or timeout_ms <= 0:
        raise ProviderExecutionError("provider_stream_invalid_budget")
    base_url = _resolve_base_url(endpoint)
    if local_only and _resolved_destination_requires_external_permission(endpoint, base_url):
        raise ProviderExecutionError("private_evidence_local_only")
    if not base_url:
        raise ProviderExecutionError("provider_stream_endpoint_missing")
    # Validate the effective URL before resolving a credential or opening a
    # client. Native SSE must not bypass the blocking transport's wire guard.
    _require_safe_provider_destination(base_url)

    import httpx

    selected_model = model or endpoint.default_model
    if selected_model == "auto":
        selected_model = None
    payload: dict[str, Any] = {
        "messages": [dict(message) for message in messages],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    if selected_model:
        payload["model"] = selected_model

    personal_key = (
        await _resolve_personal_transport_key(endpoint, selected_model, personal_model_grant)
        if personal_model_grant is not None else None
    )
    headers = _provider_headers(endpoint, personal_key, accept="text/event-stream")

    # The request-level CORTEX budget cannot be extended by an endpoint
    # timeout setting. The read timeout also guards stalled event streams.
    total_seconds = min(timeout_ms / 1000.0, endpoint.timeout_seconds)
    max_text_bytes = min(524288, max(4096, max_tokens * 48))
    text_parts: list[str] = []
    total_text_bytes = 0
    finish_reason: str | None = None
    actual_model: str | None = None
    usage: dict[str, int] = {}
    done = False
    data_lines: list[str] = []
    with _HttpExecutionObservation(
        endpoint, transport="sse", shared=personal_model_grant is None,
    ) as observation:
        try:
            async with asyncio.timeout(total_seconds):
                async with _provider_http_client(total_seconds) as client:
                    observation.handoff()
                    async with client.stream(
                        "POST", f"{base_url}/chat/completions",
                        json=payload, headers=headers,
                    ) as response:
                        observation.response_status = response.status_code
                        if not 200 <= response.status_code < 300:
                            raise ProviderExecutionError(
                                f"provider_stream_http_error:{endpoint.provider_id}:{response.status_code}"
                            )
                        if "text/event-stream" not in response.headers.get("content-type", "").lower():
                            raise ProviderExecutionError("provider_stream_invalid_content_type")

                        async for line in response.aiter_lines():
                            if line.startswith(":"):
                                continue
                            if line.startswith("data:"):
                                data = line[5:].lstrip()
                                if len(data.encode("utf-8")) > 65536:
                                    raise ProviderExecutionError("provider_stream_event_too_large")
                                data_lines.append(data)
                                if sum(len(item) for item in data_lines) > 65536:
                                    raise ProviderExecutionError("provider_stream_event_too_large")
                                continue
                            if line.strip():
                                # Event type / id fields are harmless transport
                                # metadata; never put them into the user transcript.
                                if not line.startswith(("event:", "id:", "retry:")):
                                    raise ProviderExecutionError("provider_stream_invalid_frame")
                                continue
                            if not data_lines:
                                continue

                            raw_data = "\n".join(data_lines)
                            data_lines.clear()
                            if raw_data.strip() == "[DONE]":
                                done = True
                                break
                            if finish_reason is not None:
                                # OpenAI-compatible usage-only terminal chunks may
                                # follow finish_reason; any new text is rejected.
                                chunk, ending, new_usage, actual_model = _decode_stream_event(
                                    raw_data, expected_model=selected_model,
                                    observed_model=actual_model,
                                )
                                if chunk or ending is not None:
                                    raise ProviderExecutionError("provider_stream_data_after_finish")
                            else:
                                chunk, ending, new_usage, actual_model = _decode_stream_event(
                                    raw_data, expected_model=selected_model,
                                    observed_model=actual_model,
                                )
                                if chunk:
                                    if actual_model is None:
                                        raise ProviderExecutionError("provider_stream_unverified_model")
                                    total_text_bytes += len(chunk.encode("utf-8"))
                                    if total_text_bytes > max_text_bytes:
                                        raise ProviderExecutionError("provider_stream_output_limit")
                                    text_parts.append(chunk)
                                    yield ProviderStreamEvent(kind="delta", delta=chunk)
                                if ending is not None:
                                    finish_reason = ending
                            if new_usage:
                                usage.update(new_usage)
                        # Most servers emit a final blank line; do not silently
                        # drop a frame that was buffered at EOF.
                        if data_lines and not done:
                            raw_data = "\n".join(data_lines)
                            if raw_data.strip() == "[DONE]":
                                done = True
                            else:
                                raise ProviderExecutionError("provider_stream_incomplete_frame")
        except TimeoutError as exc:
            raise ProviderExecutionError("provider_stream_deadline_exceeded") from exc
        except httpx.HTTPError as exc:
            observation.note_http_error(exc)
            raise ProviderExecutionError(
                f"provider_stream_transport_failed:{endpoint.provider_id}"
            ) from exc

        if not done or finish_reason is None:
            raise ProviderExecutionError("provider_stream_incomplete")
        text = "".join(text_parts)
        if not text.strip() or not actual_model:
            raise ProviderExecutionError("provider_stream_unverified_completion")

        observation.complete()
        yield ProviderStreamEvent(
            kind="complete",
            result=ProviderExecutionResult(
                text=text,
                model=actual_model,
                provider_id=endpoint.provider_id,
                runtime_engine=endpoint.runtime_engine.value,
                usage=usage or None,
                finish_reason=finish_reason,
            ),
        )

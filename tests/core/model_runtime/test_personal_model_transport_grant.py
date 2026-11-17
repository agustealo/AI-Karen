"""Host-only personal model-key handoff remains scoped to one provider call.

These transport tests use a fake Vault secret and local/mock HTTP transport.
They do not mint runtime permissions or claim real consumer execution.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from ai_karen_engine.core.model_runtime import provider_execution as transport
from ai_karen_engine.core.model_runtime.provider_endpoint import (
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.runtime_engine import (
    EndpointKind,
    EndpointProtocol,
    Locality,
    RuntimeEngine,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan


def _endpoint() -> ProviderEndpoint:
    return ProviderEndpoint(
        provider_id="openai",
        display_name="OpenAI",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        kind=EndpointKind.CLOUD_PROVIDER,
        protocol=EndpointProtocol.OPENAI_COMPATIBLE,
        locality=Locality.CLOUD,
        runtime_engine=RuntimeEngine.REMOTE_API,
        fallback_eligible=False,
        tenant_scoped=True,
        supports_streaming=True,
        capabilities=("chat_completion", "streaming"),
        metadata={"configuration_owner": "llm_provider_config"},
    )


def _grant(
    *,
    credential_id: uuid.UUID | None = None,
    user_id: str = "00000000-0000-4000-8000-000000000001",
    tenant_id: str = "00000000-0000-4000-8000-000000000002",
    model_id: str = "authorized-model",
) -> transport.PersonalModelTransportGrant:
    credential = credential_id or uuid.UUID("00000000-0000-4000-8000-000000000003")
    context = ChatExecutionContext(
        user_id=user_id,
        tenant_id=tenant_id,
        session_id="session-1",
        request_id="request-1",
        correlation_id="corr-1",
    )
    plan = AuthorizedExecutionPlan(
        execution_id="execution-1",
        policy_decision_id="policy-1",
        authorized_user_id=user_id,
        authorized_tenant_id=tenant_id,
        authorized_session_id="session-1",
        allowed_capabilities=["model.personal_key.execute"],
        provider_constraints={
            "personal_model_credential": {
                "provider_id": "openai",
                "model_id": model_id,
                "credential_id": str(credential),
            },
            "eligible_providers": ["openai"],
            "forbidden_providers": [],
            "local_only": False,
            "external_allowed": True,
        },
    )
    return transport.PersonalModelTransportGrant(
        context=context,
        plan=plan,
        credential_id=credential,
        provider_id="openai",
        model_id=model_id,
    )


def _configured_provider():
    from ai_karen_engine.config.llm_provider_config import (
        AuthenticationType,
        ProviderType,
    )

    return SimpleNamespace(
        enabled=True,
        provider_type=ProviderType.EXTERNAL,
        authentication=SimpleNamespace(
            type=AuthenticationType.API_KEY,
            api_key_env_var="OPENAI_API_KEY",
        ),
        endpoint=SimpleNamespace(base_url="https://api.openai.com/v1"),
    )


def _fake_vault(monkeypatch: pytest.MonkeyPatch, *, secret="personal-only-token"):
    from ai_karen_engine.config import llm_provider_config
    from ai_karen_engine.services.identity_vault import credential_vault_service

    # A personal key must not require a workspace key, but the provider must
    # remain currently enabled and point to its registered vendor endpoint.
    monkeypatch.setattr(
        llm_provider_config,
        "get_provider_config_manager",
        lambda: SimpleNamespace(get_provider=lambda _provider: _configured_provider()),
    )
    calls = []

    async def resolve(**kwargs):
        calls.append(kwargs)
        if isinstance(secret, Exception):
            raise secret
        return secret

    monkeypatch.setattr(
        credential_vault_service,
        "get_credential_vault_service",
        lambda: SimpleNamespace(resolve_authorized_personal_model_key=resolve),
    )
    return calls


def _no_workspace_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(_endpoint):
        raise AssertionError("personal key must not use a shared workspace key")

    monkeypatch.setattr(transport, "_resolve_api_key", forbidden)


def _execute(endpoint, grant):
    return transport.execute_provider_endpoint(
        endpoint,
        messages=[{"role": "user", "content": "A verified question"}],
        model="authorized-model",
        max_tokens=32,
        temperature=0.1,
        personal_model_grant=grant,
    )


@pytest.mark.asyncio
async def test_personal_key_flows_only_to_selected_sync_request(monkeypatch):
    endpoint = _endpoint()
    grant = _grant()
    vault_reads = _fake_vault(monkeypatch)
    _no_workspace_credential(monkeypatch)
    wire = []

    class Response:
        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "Approved model reply"}}],
                "model": "authorized-model",
            }).encode()

    @contextmanager
    def open_request(request, timeout):
        wire.append((request.full_url, request.get_header("Authorization")))
        yield Response()

    monkeypatch.setattr(transport, "_open_provider_request", open_request)
    result = await _execute(endpoint, grant)

    assert result.text == "Approved model reply"
    assert result.model == "authorized-model"
    assert wire == [(
        "https://api.openai.com/v1/chat/completions", "Bearer personal-only-token"
    )]
    assert len(vault_reads) == 1
    assert vault_reads[0]["context"] is grant.context
    assert vault_reads[0]["plan"] is grant.plan
    assert vault_reads[0]["credential_id"] == grant.credential_id
    assert vault_reads[0]["provider_id"] == "openai"
    assert vault_reads[0]["model_id"] == "authorized-model"


@pytest.mark.asyncio
async def test_streamed_personal_key_uses_fresh_audited_vault_resolution(monkeypatch):
    grant = _grant()
    vault_reads = _fake_vault(monkeypatch)
    _no_workspace_credential(monkeypatch)
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append((
            str(request.url),
            request.headers.get("authorization"),
        ))
        chunk = lambda content, finish: json.dumps({
            "model": "authorized-model",
            "choices": [{
                "index": 0,
                "delta": {"content": content} if content else {},
                "finish_reason": finish,
            }],
        })
        body = (
            "data: " + chunk("Actual streamed text", None) + "\n\n"
            + "data: " + chunk("", "stop") + "\n\n"
            + "data: [DONE]\n\n"
        )
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    original_client = httpx.AsyncClient
    mock = httpx.MockTransport(respond)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original_client(transport=mock, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    stream = transport.stream_provider_endpoint(
        _endpoint(),
        messages=[{"role": "user", "content": "A verified question"}],
        model="authorized-model",
        max_tokens=32,
        temperature=0.1,
        timeout_ms=5000,
        personal_model_grant=grant,
    )
    events = [part async for part in stream]
    assert [event.kind for event in events] == ["delta", "complete"]
    assert events[-1].result.text == "Actual streamed text"
    assert len(vault_reads) == 1
    assert seen == [(
        "https://api.openai.com/v1/chat/completions", "Bearer personal-only-token"
    )]


@pytest.mark.asyncio
async def test_structured_tool_transport_uses_same_one_shot_personal_key(monkeypatch):
    endpoint = replace(_endpoint(), capabilities=("chat_completion", "tools"))
    grant = _grant()
    vault_reads = _fake_vault(monkeypatch)
    _no_workspace_credential(monkeypatch)
    seen = []

    class Response:
        def read(self):
            return json.dumps({
                "model": "authorized-model",
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "Structured provider reply",
                        "tool_calls": [],
                    },
                    "finish_reason": "stop",
                }],
            }).encode()

    @contextmanager
    def open_request(request, timeout):
        seen.append(request.get_header("Authorization"))
        yield Response()

    monkeypatch.setattr(transport, "_open_provider_request", open_request)
    result = await transport.execute_structured_provider_endpoint(
        endpoint,
        messages=[{"role": "user", "content": "Classify this"}],
        model="authorized-model",
        tools=[],
        max_tokens=40,
        temperature=0.0,
        personal_model_grant=grant,
    )
    assert result.message["content"] == "Structured provider reply"
    assert result.model == "authorized-model"
    assert seen == ["Bearer personal-only-token"]
    assert len(vault_reads) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"base_url": "https://attacker.invalid/v1"},
    {"base_url": "http://api.openai.com/v1"},
    {"provider_id": "another-provider"},
    {"fallback_eligible": True},
    {"tenant_scoped": False},
    {"enabled": False},
    {"kind": EndpointKind.LOCAL_ENDPOINT},
    {"runtime_engine": RuntimeEngine.CUSTOM},
    {"metadata": {"configuration_owner": "plugin"}},
])
async def test_personal_grant_refuses_other_target_before_vault_and_network(
    monkeypatch, change
):
    endpoint = replace(_endpoint(), **change)
    vault_reads = _fake_vault(monkeypatch)
    wire = []

    def forbidden(*_args, **_kwargs):
        wire.append("called")
        raise AssertionError("no network for mismatched provider")

    monkeypatch.setattr(transport, "_open_provider_request", forbidden)
    with pytest.raises(transport.ProviderExecutionError, match="personal_model_transport_denied"):
        await _execute(endpoint, _grant())
    assert vault_reads == []
    assert wire == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"enabled": False},
    {"endpoint": SimpleNamespace(base_url="https://attacker.invalid/v1")},
    {"authentication": SimpleNamespace(type="none", api_key_env_var="OPENAI_API_KEY")},
    {"authentication": SimpleNamespace(type="api_key", api_key_env_var="FOREIGN_KEY")},
])
async def test_current_provider_config_drift_blocks_personal_key_before_vault(
    monkeypatch, change
):
    from ai_karen_engine.config import llm_provider_config

    vault_reads = _fake_vault(monkeypatch)
    actual = vars(_configured_provider()).copy()
    actual.update(change)
    monkeypatch.setattr(
        llm_provider_config,
        "get_provider_config_manager",
        lambda: SimpleNamespace(get_provider=lambda _provider: SimpleNamespace(**actual)),
    )
    wire = []

    def forbidden(*_args, **_kwargs):
        wire.append(True)
        raise AssertionError("disabled or changed provider must not execute")

    monkeypatch.setattr(transport, "_open_provider_request", forbidden)
    with pytest.raises(transport.ProviderExecutionError, match="personal_model_transport_denied"):
        await _execute(_endpoint(), _grant())
    assert vault_reads == []
    assert wire == []


@pytest.mark.asyncio
async def test_model_mismatch_prevents_audit_and_network(monkeypatch):
    vault_reads = _fake_vault(monkeypatch)
    wire = []
    monkeypatch.setattr(
        transport, "_open_provider_request", lambda *_args, **_kw: wire.append(True)
    )
    with pytest.raises(transport.ProviderExecutionError, match="personal_model_transport_denied"):
        await _execute(_endpoint(), _grant(model_id="different-model"))
    assert vault_reads == []
    assert wire == []


@pytest.mark.asyncio
async def test_vault_audit_failure_blocks_transport_without_secret_leak(monkeypatch):
    vault_reads = _fake_vault(
        monkeypatch, secret=PermissionError("private database audit payload")
    )
    wire = []
    monkeypatch.setattr(
        transport, "_open_provider_request", lambda *_args, **_kw: wire.append(True)
    )
    with pytest.raises(transport.ProviderExecutionError) as error:
        await _execute(_endpoint(), _grant())
    assert str(error.value) == "personal_model_transport_denied"
    assert "private database" not in repr(error.value)
    assert len(vault_reads) == 1
    assert wire == []


@pytest.mark.asyncio
async def test_concurrent_users_same_provider_keep_distinct_bearer_headers(monkeypatch):
    endpoint = _endpoint()
    from ai_karen_engine.services.identity_vault import credential_vault_service

    left_id = uuid.UUID("00000000-0000-4000-8000-000000000011")
    right_id = uuid.UUID("00000000-0000-4000-8000-000000000022")
    left = _grant(credential_id=left_id)
    right = _grant(
        credential_id=right_id,
        user_id="00000000-0000-4000-8000-000000000031",
        tenant_id="00000000-0000-4000-8000-000000000032",
    )
    reads = []

    async def resolve(**kwargs):
        reads.append((kwargs["context"].tenant_id, kwargs["credential_id"]))
        await asyncio.sleep(0)
        return "left-only" if kwargs["credential_id"] == left_id else "right-only"

    monkeypatch.setattr(
        credential_vault_service, "get_credential_vault_service",
        lambda: SimpleNamespace(resolve_authorized_personal_model_key=resolve),
    )
    _no_workspace_credential(monkeypatch)
    wires = []

    class Response:
        def read(self):
            return json.dumps({
                "model": "authorized-model",
                "choices": [{"message": {"content": "Response"}}],
            }).encode()

    @contextmanager
    def open_request(request, timeout):
        wires.append(request.get_header("Authorization"))
        yield Response()

    monkeypatch.setattr(transport, "_open_provider_request", open_request)
    results = await asyncio.gather(
        _execute(endpoint, left), _execute(endpoint, right)
    )
    assert [result.text for result in results] == ["Response", "Response"]
    assert set(wires) == {"Bearer left-only", "Bearer right-only"}
    assert set(reads) == {
        (left.context.tenant_id, left_id),
        (right.context.tenant_id, right_id),
    }


def test_sync_redirect_handler_never_authorizes_new_request():
    handler = transport._RejectProviderRedirect()
    for code in (301, 302, 303, 307, 308):
        assert handler.redirect_request(
            object(), None, code, "moved",
            {"Location": "https://attacker.invalid/capture"},
            "https://attacker.invalid/capture",
        ) is None


def test_sync_provider_uses_nonglobal_no_redirect_opener(monkeypatch):
    calls = []
    dummy = object()

    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            return dummy

    def build(*handlers):
        assert len(handlers) == 2
        assert isinstance(handlers[0], transport._RejectProviderRedirect)
        assert isinstance(handlers[1], transport.ProxyHandler)
        assert handlers[1].proxies == {}
        return Opener()

    monkeypatch.setattr(transport, "build_opener", build)
    request = transport.Request("https://api.openai.com/v1/chat/completions")
    assert transport._open_provider_request(request, timeout=3.5) is dummy
    assert calls == [(request, 3.5)]


def test_sync_runtime_ignores_ambient_proxy_environment(monkeypatch):
    """A server-local endpoint must not be rerouted through process env."""
    monkeypatch.setenv("HTTP_PROXY", "http://unapproved-relay.example:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://unapproved-relay.example:3128")
    monkeypatch.setenv("ALL_PROXY", "socks5://unapproved-relay.example:9050")
    monkeypatch.setenv("NO_PROXY", "")
    seen = []

    class Opener:
        def open(self, request, timeout):
            seen.append((request.full_url, timeout))
            return object()

    def guarded_builder(*handlers):
        assert len(handlers) == 2
        assert isinstance(handlers[0], transport._RejectProviderRedirect)
        assert isinstance(handlers[1], transport.ProxyHandler)
        assert handlers[1].proxies == {}
        return Opener()

    monkeypatch.setattr(transport, "build_opener", guarded_builder)
    req = transport.Request("http://127.0.0.1:11434/v1/chat/completions")
    transport._open_provider_request(req, timeout=4.0)
    assert seen == [("http://127.0.0.1:11434/v1/chat/completions", 4.0)]

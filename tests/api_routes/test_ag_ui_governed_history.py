"""CK-07D canonical owned-history ingress: auth, RLS and no execution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.chat import runtime as route
from ai_karen_engine.core.runtime.conversation_runtime_gateway import ConversationSnapshot
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Conversation, Message, canonical_message_digest,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
THREAD = "44444444-4444-4444-8444-444444444444"
ASSISTANT = "22222222-2222-5222-8222-222222222222"
REQUEST = "33333333-3333-4333-8333-333333333333"


def snapshot(*, rich=False):
    return ConversationSnapshot(
        conversation=Conversation(id=THREAD, user_id=USER, tenant_id=TENANT),
        messages=(
            Message(id="user-1", conversation_id=THREAD, tenant_id=TENANT,
                    role="user", content="hello", metadata={}),
            Message(
                id=ASSISTANT, conversation_id=THREAD, tenant_id=TENANT,
                role="assistant", content="canonical answer",
                metadata={
                    **({
                        "source": "chat_runtime",
                        "request_id": REQUEST,
                        "requested_model": "model-selected",
                        "actual_provider": "local",
                        "actual_model": "model-observed",
                        "response_source": "local_inference",
                    } if rich else {}),
                    "secret_debug_field": "never expose",
                },
            ),
        ),
    )


@pytest.fixture
def replay_on(monkeypatch):
    monkeypatch.setattr(route, "get_runtime_settings", lambda: SimpleNamespace(
        features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=True,
        ),
    ))


@pytest.mark.asyncio
async def test_backend_governed_history_uses_canonical_owner_and_ledger_only(
    monkeypatch, replay_on,
):
    calls = []

    class Owned:
        async def get_owned_snapshot(self, ctx, *, message_limit):
            calls.append(("owned", ctx.tenant_id, ctx.user_id, ctx.conversation_id, message_limit))
            return snapshot(rich=True)

    class Attestation:
        async def completed_replay_attestations(self, **kwargs):
            calls.append(("attested", kwargs))
            saved = snapshot(rich=True).messages[1]
            return {ASSISTANT: (REQUEST, canonical_message_digest(saved))}

    from ai_karen_engine.core.runtime import conversation_runtime_gateway
    monkeypatch.setattr(
        conversation_runtime_gateway, "get_conversation_runtime_gateway",
        lambda: Owned(),
    )
    monkeypatch.setattr(route, "SqlChatRunRepository", Attestation)

    result = await route.get_ag_ui_owned_history(
        thread_id=THREAD, user={"user_id": USER, "tenant_id": TENANT},
    )
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    import json
    body = json.loads(result.body)
    assert body["threadId"] == THREAD
    assert body["owner_user_id"] == USER
    assert body["owner_tenant_id"] == TENANT
    assert [e["name"] for e in body["replayEvents"]] == [
        "karen.execution_receipt.v1",
    ]
    assert "never expose" not in str(body)
    assert calls[0] == ("owned", TENANT, USER, THREAD, 501)
    assert calls[1] == ("attested", {
        "tenant_id": TENANT, "user_id": USER, "conversation_id": THREAD,
    })


@pytest.mark.asyncio
async def test_governed_history_refuses_foreign_conversation_and_skips_attestation(
    monkeypatch, replay_on,
):
    calls = []

    class Forbidden:
        async def get_owned_snapshot(self, ctx, *, message_limit):
            raise PermissionError("conversation_user_mismatch")

    class NoLedger:
        def __init__(self):
            calls.append("created")

    from ai_karen_engine.core.runtime import conversation_runtime_gateway
    monkeypatch.setattr(
        conversation_runtime_gateway, "get_conversation_runtime_gateway",
        lambda: Forbidden(),
    )
    monkeypatch.setattr(route, "SqlChatRunRepository", NoLedger)
    with pytest.raises(HTTPException) as error:
        await route.get_ag_ui_owned_history(
            thread_id=THREAD, user={"user_id": USER, "tenant_id": TENANT},
        )
    assert error.value.status_code == 404
    assert calls == []


@pytest.mark.asyncio
async def test_unknown_or_unattested_rich_history_refuses_entire_snapshot(
    monkeypatch, replay_on,
):
    class Owned:
        async def get_owned_snapshot(self, ctx, *, message_limit):
            return snapshot(rich=True)

    class NoAttestation:
        async def completed_replay_attestations(self, **kwargs):
            return {}

    from ai_karen_engine.core.runtime import conversation_runtime_gateway
    monkeypatch.setattr(
        conversation_runtime_gateway, "get_conversation_runtime_gateway",
        lambda: Owned(),
    )
    monkeypatch.setattr(route, "SqlChatRunRepository", NoAttestation)
    with pytest.raises(HTTPException) as error:
        await route.get_ag_ui_owned_history(
            thread_id=THREAD, user={"user_id": USER, "tenant_id": TENANT},
        )
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_feature_gate_and_malformed_thread_denied_before_history_lookup(
    monkeypatch,
):
    calls = []

    class NoGateway:
        def __init__(self):
            calls.append("unwanted")

    from ai_karen_engine.core.runtime import conversation_runtime_gateway
    monkeypatch.setattr(
        conversation_runtime_gateway, "get_conversation_runtime_gateway",
        NoGateway,
    )
    monkeypatch.setattr(route, "get_runtime_settings", lambda: SimpleNamespace(
        features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=False,
        ),
    ))
    with pytest.raises(HTTPException) as disabled:
        await route.get_ag_ui_owned_history(
            thread_id=THREAD, user={"user_id": USER, "tenant_id": TENANT},
        )
    assert disabled.value.status_code == 404
    monkeypatch.setattr(route, "get_runtime_settings", lambda: SimpleNamespace(
        features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=True,
        ),
    ))
    with pytest.raises(HTTPException) as malformed:
        await route.get_ag_ui_owned_history(
            thread_id="not-a-uuid", user={"user_id": USER, "tenant_id": TENANT},
        )
    assert malformed.value.status_code == 422
    assert calls == []

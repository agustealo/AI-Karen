"""CK-07E6: canonical authenticated composer draft contract, no AI execution."""

from __future__ import annotations

import uuid
import json

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.chat import conversation as routes
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
)
from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Conversation,
)

TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OTHER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
CONV = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


def context(*, user_id: str = USER, tenant: str = TENANT) -> ChatExecutionContext:
    return ChatExecutionContext(
        tenant_id=tenant, user_id=user_id, conversation_id=CONV,
        request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
    )


class OwnedDraftRepo:
    def __init__(self):
        self.text = ""
        self.revision = 0
        self.calls = []

    async def get_conversation(self, conversation_id, tenant_id):
        self.calls.append(("owned_lookup", tenant_id))
        if conversation_id != CONV or tenant_id != TENANT:
            return RepositoryResult(success=True, data=None)
        return RepositoryResult(success=True, data=Conversation(
            id=CONV, tenant_id=TENANT, user_id=USER,
        ))

    async def get_composer_draft(self, conversation_id, tenant_id, *, user_id):
        self.calls.append(("read", tenant_id, user_id))
        return RepositoryResult(
            success=True, data={"text": self.text, "revision": self.revision},
        )

    async def put_composer_draft(
        self, conversation_id, tenant_id, *, user_id,
        content, expected_revision,
    ):
        self.calls.append(("write", tenant_id, user_id, expected_revision))
        if self.revision != expected_revision:
            return RepositoryResult(
                success=False, error="composer_draft_revision_conflict",
            )
        self.text = content
        self.revision += 1
        return RepositoryResult(
            success=True, data={"text": self.text, "revision": self.revision},
        )


@pytest.mark.asyncio
async def test_owned_draft_uses_only_canonical_repository_not_model_or_memory():
    repo = OwnedDraftRepo()
    gateway = ConversationRuntimeGateway(repo)
    assert await gateway.read_composer_draft(context()) == {
        "text": "", "revision": 0,
    }
    changed = await gateway.write_composer_draft(
        context(), text="Unsent only", expected_revision=0,
    )
    assert changed == {"text": "Unsent only", "revision": 1}
    assert await gateway.read_composer_draft(context()) == changed
    assert repo.calls.count(("write", TENANT, USER, 0)) == 1


@pytest.mark.asyncio
async def test_stale_window_must_not_overwrite_confirmed_revision():
    repo = OwnedDraftRepo()
    gateway = ConversationRuntimeGateway(repo)
    await gateway.write_composer_draft(
        context(), text="First tab", expected_revision=0,
    )
    with pytest.raises(ValueError, match="revision_conflict"):
        await gateway.write_composer_draft(
            context(), text="Stale second tab", expected_revision=0,
        )
    assert await gateway.read_composer_draft(context()) == {
        "text": "First tab", "revision": 1,
    }


@pytest.mark.asyncio
async def test_foreign_principal_cannot_read_or_edit_draft():
    repo = OwnedDraftRepo()
    gateway = ConversationRuntimeGateway(repo)
    with pytest.raises(PermissionError, match="user_mismatch"):
        await gateway.read_composer_draft(context(user_id=OTHER))
    with pytest.raises(PermissionError, match="user_mismatch"):
        await gateway.write_composer_draft(
            context(user_id=OTHER), text="No access", expected_revision=0,
        )
    assert not any(call[0] in {"read", "write"} for call in repo.calls)


@pytest.mark.asyncio
async def test_wrong_tenant_refused_before_draft_query():
    repo = OwnedDraftRepo()
    gateway = ConversationRuntimeGateway(repo)
    with pytest.raises(RuntimeError, match="conversation_not_found"):
        await gateway.read_composer_draft(context(tenant=OTHER))
    assert not any(call[0] == "read" for call in repo.calls)


@pytest.mark.asyncio
async def test_bounded_utf8_draft_is_checked_before_repository_mutation():
    repo = OwnedDraftRepo()
    gateway = ConversationRuntimeGateway(repo)
    for message, revision in [
        ("x" * 65537, 0),
        ("🚀" * 65537, 0),
        ("valid", -1),
        ("valid", True),
    ]:
        with pytest.raises(ValueError, match="composer_draft_invalid"):
            await gateway.write_composer_draft(
                context(), text=message, expected_revision=revision,
            )
    assert not any(call[0] == "write" for call in repo.calls)


@pytest.mark.asyncio
async def test_http_read_and_write_are_authenticated_thin_gateway_calls():
    repo = OwnedDraftRepo()
    gateway = ConversationRuntimeGateway(repo)
    owner = {"user_id": USER, "tenant_id": TENANT}
    read = await routes.get_composer_draft(
        CONV, conversation_gateway=gateway, tenant_id=TENANT, user_ctx=owner,
    )
    assert read.headers["cache-control"] == "private, no-store"
    assert json.loads(read.body) == {"text": "", "revision": 0}
    updated = await routes.put_composer_draft(
        CONV, routes.UpdateComposerDraftRequest(
            text="Own saved draft", expected_revision=0,
        ),
        conversation_gateway=gateway, tenant_id=TENANT, user_ctx=owner,
    )
    assert updated.headers["cache-control"] == "private, no-store"
    assert json.loads(updated.body) == {
        "text": "Own saved draft", "revision": 1,
    }
    with pytest.raises(HTTPException) as stale:
        await routes.put_composer_draft(
            CONV, routes.UpdateComposerDraftRequest(
                text="Outdated", expected_revision=0,
            ),
            conversation_gateway=gateway, tenant_id=TENANT, user_ctx=owner,
        )
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as foreign:
        await routes.get_composer_draft(
            CONV, conversation_gateway=gateway, tenant_id=TENANT,
            user_ctx={"user_id": OTHER, "tenant_id": TENANT},
        )
    assert foreign.value.status_code == 404


@pytest.mark.asyncio
async def test_read_backend_unavailable_never_invents_a_saved_draft():
    repo = OwnedDraftRepo()
    gateway = ConversationRuntimeGateway(repo)
    async def unavailable(*args, **kwargs):
        return RepositoryResult(success=False, error="composer_draft_storage_unavailable")
    repo.get_composer_draft = unavailable
    with pytest.raises(HTTPException) as failure:
        await routes.get_composer_draft(
            CONV, conversation_gateway=gateway, tenant_id=TENANT,
            user_ctx={"user_id": USER, "tenant_id": TENANT},
        )
    assert failure.value.status_code == 503

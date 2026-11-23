"""KGUI-CARD-STUDIO-01C: real policy decisions and owned CRUD delegation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
from ai_karen_engine.core.runtime.card_studio_template_service import (
    CardStudioAuthorizationError,
    CardStudioTemplateService,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.persistence.repositories.card_studio_template_repository import (
    CardTemplateConflict,
    CardTemplateMutationReceipt,
    SavedCardTemplate,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OWNER = "11111111-1111-1111-1111-111111111111"
OTHER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
KEY = "99999999-9999-4999-8999-999999999999"
TEMPLATE = "55555555-5555-4555-8555-555555555555"


def draft():
    return {
        "schema_version": 1, "template_key": "personal-clock",
        "title": "Observed clock", "layout": "stack",
        "density": "comfortable", "interaction_mode": "read_only",
        "slots": [{"slot_id": "main", "component_type": "time.observation"}],
    }


def context(*, role="user", active=True, user_id=OWNER, principal_id=None):
    principal = UserData(
        user_id=principal_id or user_id, tenant_id=TENANT,
        roles=[role], permissions=[],
        is_active=active, is_verified=True,
    )
    return ChatExecutionContext(
        user_id=user_id, tenant_id=TENANT,
        session_id="card-studio-api-request",
        conversation_id=None,
        request_id="server-request", correlation_id="server-correlation",
        authenticated_user=principal,
    )


def repository():
    saved = SavedCardTemplate(
        template_id=TEMPLATE, tenant_id=TENANT, user_id=OWNER,
        template_key="personal-clock", revision=1,
        lifecycle="draft", definition=draft(),
    )
    receipt = CardTemplateMutationReceipt(
        template_id=TEMPLATE, revision=1, operation="create",
        idempotency_key=KEY, request_digest="f" * 64,
    )
    return SimpleNamespace(
        create_draft=AsyncMock(return_value=(saved, receipt)),
        revise_draft=AsyncMock(return_value=(saved, receipt)),
        archive_draft=AsyncMock(return_value=(saved, receipt)),
        list_owned=AsyncMock(return_value=[saved]),
        read_owned=AsyncMock(return_value=saved),
        list_revisions=AsyncMock(return_value=[saved]),
    )


@pytest.mark.asyncio
async def test_standard_user_grants_are_owned_by_canonical_rbac():
    principal = context().require_authenticated_user()
    manager = get_rbac_manager()
    assert manager.has_permission(principal, Permission.CARD_STUDIO_READ)
    assert manager.has_permission(principal, Permission.CARD_STUDIO_WRITE)
    readonly = context(role="readonly").require_authenticated_user()
    assert not manager.has_permission(readonly, Permission.CARD_STUDIO_READ)
    assert not manager.has_permission(readonly, Permission.CARD_STUDIO_WRITE)


@pytest.mark.asyncio
async def test_policy_issuer_denies_unknown_or_readonly_card_actions():
    policy = RuntimePolicyEnforcer()
    rejected = await policy.evaluate(PolicyEvaluationRequest(
        user_id=OWNER, tenant_id=TENANT, session_id="test",
        roles=["user"], permissions=[],
        action="card_studio.publish",
        requested_capabilities=["card_studio.publish"],
        max_model_calls=0,
    ))
    assert not rejected.allowed
    assert "card_studio.publish" in rejected.denied_capabilities

    rejected = await policy.evaluate(PolicyEvaluationRequest(
        user_id=OWNER, tenant_id=TENANT, session_id="test",
        roles=["readonly"], permissions=[],
        action="card_studio.write",
        requested_capabilities=["card_studio.write"],
        max_model_calls=0,
    ))
    assert not rejected.allowed


@pytest.mark.asyncio
async def test_runtime_service_passes_only_authenticated_scope_and_exact_receipt():
    backend = repository()
    service = CardStudioTemplateService(repository=backend)
    ctx = context()
    mutation = await service.mutate(
        context=ctx, operation="create", idempotency_key=KEY, draft=draft(),
    )
    assert mutation.template.template_id == TEMPLATE
    assert mutation.receipt.idempotency_key == KEY
    backend.create_draft.assert_awaited_once_with(
        authenticated_tenant_id=TENANT,
        authenticated_user_id=OWNER,
        idempotency_key=KEY,
        draft=draft(),
    )
    listed = await service.list_owned(context=ctx, limit=4)
    assert listed == [mutation.template]
    backend.list_owned.assert_awaited_once_with(
        authenticated_tenant_id=TENANT,
        authenticated_user_id=OWNER,
        limit=4,
        include_archived=False,
    )
    assert (await service.read_owned(
        context=ctx, template_id=TEMPLATE, revision=1,
    )).template_id == TEMPLATE
    assert (await service.list_revisions(
        context=ctx, template_id=TEMPLATE,
    ))[0].revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ctx",
    [
        context(role="readonly"),
        context(active=False),
        context(user_id=OTHER, principal_id=OWNER),
    ],
)
async def test_denied_read_or_write_never_opens_repository(ctx):
    backend = repository()
    service = CardStudioTemplateService(repository=backend)
    with pytest.raises(CardStudioAuthorizationError):
        await service.mutate(
            context=ctx, operation="create", idempotency_key=KEY, draft=draft(),
        )
    with pytest.raises(CardStudioAuthorizationError):
        await service.list_owned(context=ctx)
    backend.create_draft.assert_not_awaited()
    backend.list_owned.assert_not_awaited()


@pytest.mark.asyncio
async def test_revision_and_archive_are_delegated_to_existing_repository():
    backend = repository()
    service = CardStudioTemplateService(repository=backend)
    await service.mutate(
        context=context(), operation="revise",
        idempotency_key=KEY, template_id=TEMPLATE,
        expected_revision=1, draft=draft(),
    )
    backend.revise_draft.assert_awaited_once_with(
        authenticated_tenant_id=TENANT,
        authenticated_user_id=OWNER,
        idempotency_key=KEY,
        template_id=TEMPLATE,
        expected_revision=1,
        draft=draft(),
    )
    await service.mutate(
        context=context(), operation="archive",
        idempotency_key=KEY, template_id=TEMPLATE,
        expected_revision=1,
    )
    backend.archive_draft.assert_awaited_once_with(
        authenticated_tenant_id=TENANT,
        authenticated_user_id=OWNER,
        idempotency_key=KEY,
        template_id=TEMPLATE,
        expected_revision=1,
    )


@pytest.mark.asyncio
async def test_conflict_and_uncertain_failure_propagate_without_fake_commit():
    backend = repository()
    backend.create_draft.side_effect = CardTemplateConflict("stale")
    service = CardStudioTemplateService(repository=backend)
    with pytest.raises(CardTemplateConflict):
        await service.mutate(
            context=context(), operation="create",
            idempotency_key=KEY, draft=draft(),
        )

    backend.create_draft.side_effect = RuntimeError("driver disconnected after commit")
    with pytest.raises(RuntimeError):
        await service.mutate(
            context=context(), operation="create",
            idempotency_key=KEY, draft=draft(),
        )


@pytest.mark.asyncio
async def test_unsupported_mutations_fail_before_policy_or_database():
    backend = repository()
    service = CardStudioTemplateService(repository=backend)
    with pytest.raises(ValueError):
        await service.mutate(
            context=context(), operation="publish",
            idempotency_key=KEY, draft=draft(),
        )
    backend.create_draft.assert_not_awaited()
    backend.revise_draft.assert_not_awaited()
    backend.archive_draft.assert_not_awaited()

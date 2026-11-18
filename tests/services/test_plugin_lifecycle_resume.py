"""Only persisted actor/session-bound human consent may resume lifecycle."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.plugin_lifecycle_approval import PluginLifecycleApprovalScope
from ai_karen_engine.services import approvals as approval_module
from ai_karen_engine.services.approvals import ApprovalScopeError, ApprovalStateError
from ai_karen_engine.services.plugin_service import PluginService


def _subject():
    tenant_id, user_id, conversation_id, approval_id = (str(uuid.uuid4()) for _ in range(4))
    principal = UserData(user_id=user_id, tenant_id=tenant_id, roles=["admin"])
    context = ChatExecutionContext(
        user_id=user_id,
        tenant_id=tenant_id,
        session_id="server-token-1",
        conversation_id=conversation_id,
        request_id="request-1",
        correlation_id="correlation-1",
        authenticated_user=principal,
    )
    scope = PluginLifecycleApprovalScope(
        installation_id="timezone-clock",
        action="enable",
        manifest_checksum="a" * 64,
        expected_state="disabled",
        expected_revision=3,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id="server-token-1",
        conversation_id=conversation_id,
    )
    approval = {
        "status": "approved",
        "intent": "plugin.lifecycle.enable",
        "request_payload": {"plugin_lifecycle_scope": scope.to_record()},
    }
    return context, scope, approval_id, approval


def _service(monkeypatch: pytest.MonkeyPatch, approval: dict):
    get_record = AsyncMock(return_value=approval)
    monkeypatch.setattr(
        approval_module, "get_approval_service",
        lambda: SimpleNamespace(get=get_record),
    )
    service = PluginService()
    execute = AsyncMock(return_value={"status": "verified_committed"})
    monkeypatch.setattr(service, "execute_approved_lifecycle", execute)
    return service, get_record, execute


@pytest.mark.asyncio
async def test_resume_uses_only_actor_scoped_sql_and_canonical_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, scope, approval_id, approval = _subject()
    service, read, execute = _service(monkeypatch, approval)
    receipt = await service.resume_lifecycle_approval(
        context=context,
        plugin_id="timezone-clock",
        action="enable",
        approval_id=approval_id,
    )
    assert receipt == {"status": "verified_committed"}
    read.assert_awaited_once_with(approval_id, user=context.authenticated_user)
    execute.assert_awaited_once_with(
        context=context, scope=scope, approval_id=approval_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected", "expired", "consumed", "unknown"])
async def test_approval_not_approved_never_executes(
    monkeypatch: pytest.MonkeyPatch, status: str,
) -> None:
    context, _, approval_id, approval = _subject()
    service, _, execute = _service(
        monkeypatch, {**approval, "status": status},
    )
    with pytest.raises(ApprovalStateError, match="not executable"):
        await service.resume_lifecycle_approval(
            context=context, plugin_id="timezone-clock",
            action="enable", approval_id=approval_id,
        )
    execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("installation_id", "foreign-plugin"),
    ("action", "disable"),
    ("tenant_id", str(uuid.uuid4())),
    ("user_id", str(uuid.uuid4())),
    ("session_id", "another-authenticated-session"),
    ("conversation_id", str(uuid.uuid4())),
    ("manifest_checksum", "not-an-immutable-sha"),
    ("expected_revision", 0),
])
async def test_changed_persisted_lifecycle_scope_is_not_authority(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    context, scope, approval_id, approval = _subject()
    # Intentionally submit a forged but structurally plausible SQL scope.
    payload = {**scope.to_record(), field: value}
    service, _, execute = _service(monkeypatch, {
        **approval,
        "request_payload": {"plugin_lifecycle_scope": payload},
    })
    with pytest.raises((ApprovalScopeError, ValueError, PermissionError)):
        await service.resume_lifecycle_approval(
            context=context, plugin_id="timezone-clock",
            action="enable", approval_id=approval_id,
        )
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_live_session_cannot_resume_original_approved_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, approval_id, approval = _subject()
    service, _, execute = _service(monkeypatch, approval)
    context.session_id = "another-verified-token"
    with pytest.raises(ApprovalScopeError, match="session"):
        await service.resume_lifecycle_approval(
            context=context, plugin_id="timezone-clock",
            action="enable", approval_id=approval_id,
        )
    execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("target,verb,approval_id", [
    ("wrong-plugin", "enable", None),
    ("timezone-clock", "disable", None),
    ("timezone-clock", "enable", "not-a-uuid"),
])
async def test_request_target_and_receipt_id_never_override_saved_consent(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    verb: str,
    approval_id: str | None,
) -> None:
    context, _, valid_id, approval = _subject()
    service, _, execute = _service(monkeypatch, approval)
    with pytest.raises((ApprovalScopeError, ValueError)):
        await service.resume_lifecycle_approval(
            context=context, plugin_id=target, action=verb,
            approval_id=approval_id if approval_id is not None else valid_id,
        )
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_persisted_scope_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _, approval_id, approval = _subject()
    service, _, execute = _service(monkeypatch, {
        **approval, "request_payload": {},
    })
    with pytest.raises(ApprovalScopeError):
        await service.resume_lifecycle_approval(
            context=context, plugin_id="timezone-clock",
            action="enable", approval_id=approval_id,
        )
    execute.assert_not_awaited()

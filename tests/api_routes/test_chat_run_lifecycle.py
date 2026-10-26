"""CK-07A: durable run admission, lease fencing and terminal event truth."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_run_lifecycle import (
    ChatRunConflict,
    ChatRunCoordinator,
    ChatRunLeaseLost,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatStreamChunk,
    ChatStreamEventType,
)
from ai_karen_engine.persistence.repositories.chat_run_repository import ChatRunLease

@pytest.fixture(autouse=True)
def owned_runtime_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reuse canonical ownership check, without a test-only DB substitute in production."""
    from ai_karen_engine.core.runtime import chat_run_lifecycle

    class ScopedGateway:
        async def require_owned_conversation(self, execution_context: ChatExecutionContext):
            assert execution_context.conversation_id == THREAD
            return {"id": THREAD}

    monkeypatch.setattr(
        chat_run_lifecycle,
        "get_conversation_runtime_gateway",
        lambda: ScopedGateway(),
    )


USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "22222222-2222-2222-2222-222222222222"
TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
THREAD = "4f6dc890-2644-4ff8-8f15-888888888888"


def context(*, user: str = USER_A, tenant: str = TENANT_A) -> ChatExecutionContext:
    return ChatExecutionContext(
        user_id=user,
        tenant_id=tenant,
        session_id="canonical-session",
        conversation_id=THREAD,
        request_id="request-1",
        correlation_id="correlation-1",
        authenticated_user=UserData(
            user_id=user, tenant_id=tenant, is_active=True, is_verified=True
        ),
    )


class MemoryLedger:
    """Contract fake only; no fake model, provider or runtime in production."""

    def __init__(self) -> None:
        self.keys: set[tuple[str, str, str, str]] = set()
        self.finalized: list[tuple[str, str, str | None]] = []
        self.heartbeat_count = 0
        self.allow_renew = True
        self.allow_finish = True

    async def admit(self, **kwargs: Any) -> ChatRunLease | None:
        key = (
            kwargs["tenant_id"],
            kwargs["user_id"],
            kwargs["conversation_id"],
            kwargs["transport_run_id"],
        )
        if key in self.keys:
            return None
        self.keys.add(key)
        return ChatRunLease(
            execution_id="33333333-3333-4333-8333-333333333333",
            lease_token="44444444-4444-4444-8444-444444444444",
            **kwargs,
        )

    async def renew(self, lease: ChatRunLease) -> bool:
        self.heartbeat_count += 1
        return self.allow_renew

    async def finish(
        self, lease: ChatRunLease, *, status: str, error_code: str | None = None
    ) -> bool:
        if self.allow_finish:
            self.finalized.append((lease.transport_run_id, status, error_code))
        return self.allow_finish


def content(text: str = "token") -> ChatStreamChunk:
    return ChatStreamChunk(type=ChatStreamEventType.CONTENT, content=text)


def completed() -> ChatStreamChunk:
    return ChatStreamChunk(type=ChatStreamEventType.COMPLETE, content="")


@pytest.mark.asyncio
async def test_duplicate_sdk_run_rejected_without_cross_tenant_collision() -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    a = await coordinator.admit(context(), "run-1")
    assert a.user_id == USER_A
    assert a.tenant_id == TENANT_A

    with pytest.raises(ChatRunConflict):
        await coordinator.admit(context(), "run-1")

    # The SDK runId alone has NO global authority.
    assert (await coordinator.admit(context(user=USER_B), "run-1")).user_id == USER_B
    assert (await coordinator.admit(context(tenant=TENANT_B), "run-1")).tenant_id == TENANT_B


@pytest.mark.asyncio
async def test_forged_principal_cannot_admit_run() -> None:
    repo = MemoryLedger()
    invalid = context()
    invalid.authenticated_user = UserData(
        user_id=USER_B, tenant_id=TENANT_A
    )
    with pytest.raises(PermissionError, match="scope_mismatch"):
        await ChatRunCoordinator(repo).admit(invalid, "run-1")
    assert not repo.keys


@pytest.mark.asyncio
async def test_repository_owner_denial_precedes_ledger_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.runtime import chat_run_lifecycle

    class ForeignGateway:
        async def require_owned_conversation(self, _context: ChatExecutionContext):
            raise PermissionError("conversation_user_mismatch")

    monkeypatch.setattr(
        chat_run_lifecycle, "get_conversation_runtime_gateway",
        lambda: ForeignGateway(),
    )
    repo = MemoryLedger()
    with pytest.raises(PermissionError):
        await ChatRunCoordinator(repo).admit(context(), "run-foreign")
    assert not repo.keys


@pytest.mark.asyncio
async def test_runtime_terminal_persists_before_success_chunk() -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-2")

    async def upstream():
        yield content()
        yield completed()

    events = []
    async for chunk in coordinator.stream(upstream(), lease=lease):
        if chunk.type == ChatStreamEventType.COMPLETE:
            assert repo.finalized == [("run-2", "completed", None)]
        events.append(chunk.type)

    assert events == [ChatStreamEventType.CONTENT, ChatStreamEventType.COMPLETE]


@pytest.mark.asyncio
async def test_failed_terminal_commit_cannot_claim_success() -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-3")
    repo.allow_finish = False

    async def upstream():
        yield completed()

    with pytest.raises(ChatRunLeaseLost, match="lease_lost"):
        await anext(coordinator.stream(upstream(), lease=lease))
    assert repo.finalized == []


@pytest.mark.asyncio
async def test_missing_terminal_is_failed_not_completed() -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-4")

    async def upstream():
        yield content()

    with pytest.raises(ChatRunLeaseLost, match="missing_terminal"):
        async for _ in coordinator.stream(upstream(), lease=lease):
            pass
    assert repo.finalized == [
        ("run-4", "failed", "CHAT_SSE_MISSING_TERMINAL")
    ]


@pytest.mark.asyncio
async def test_heartbeat_continues_during_blocked_upstream_and_can_fence_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.runtime import chat_run_lifecycle

    monkeypatch.setattr(chat_run_lifecycle, "_heartbeat_seconds", lambda: 0.001)
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-5")

    async def slow_upstream():
        await asyncio.sleep(0.02)
        yield completed()

    emitted = [chunk async for chunk in coordinator.stream(slow_upstream(), lease=lease)]
    assert emitted[-1].type == ChatStreamEventType.COMPLETE
    assert repo.heartbeat_count >= 1

    repo.allow_renew = False
    closed = asyncio.Event()

    async def blocked_upstream():
        try:
            await asyncio.sleep(1)
            yield completed()
        finally:
            closed.set()

    with pytest.raises(ChatRunLeaseLost):
        async for _ in coordinator.stream(blocked_upstream(), lease=lease):
            pass
    assert closed.is_set()
    assert repo.finalized[-1] == ("run-5", "failed", "CHAT_RUN_LEASE_LOST")


@pytest.mark.asyncio
async def test_closed_transport_marks_owned_run_cancelled() -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-6")

    async def upstream():
        yield content()
        await asyncio.sleep(1)
        yield completed()

    stream = coordinator.stream(upstream(), lease=lease)
    assert (await anext(stream)).content == "token"
    await stream.aclose()
    assert repo.finalized == [
        ("run-6", "cancelled", "CHAT_STREAM_CANCELLED")
    ]

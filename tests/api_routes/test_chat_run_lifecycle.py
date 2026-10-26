"""CK-07A: durable run admission, lease fencing and terminal event truth."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_run_lifecycle import (
    ChatRunConflict,
    ChatRunCancellationRequested,
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
        self.cancel_intent = False
        self.stop_requests: list[tuple[str, str, str, str]] = []

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
        return self.allow_renew and not self.cancel_intent

    async def cancel_requested(self, lease: ChatRunLease) -> bool:
        return self.cancel_intent

    async def request_cancel(self, *, tenant_id: str, user_id: str,
                             conversation_id: str, transport_run_id: str) -> str | None:
        scope = (tenant_id, user_id, conversation_id, transport_run_id)
        self.stop_requests.append(scope)
        if scope not in self.keys:
            return None
        self.cancel_intent = True
        return "cancelling"

    async def finish(
        self, lease: ChatRunLease, *, status: str, error_code: str | None = None
    ) -> bool:
        if self.allow_finish:
            self.finalized.append((lease.transport_run_id, status, error_code))
        return self.allow_finish


def content(text: str = "token") -> ChatStreamChunk:
    return ChatStreamChunk(type=ChatStreamEventType.CONTENT, content=text)


def completed() -> ChatStreamChunk:
    return ChatStreamChunk(
        type=ChatStreamEventType.COMPLETE,
        content="",
        metadata={"transcript_persistence_status": "persisted"},
    )


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
@pytest.mark.parametrize("persistence_status", [None, "failed", "rejected", "skipped"])
async def test_unverified_transcript_never_emits_run_completion(
    persistence_status: str | None,
) -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-unverified")

    async def upstream():
        yield content()
        metadata = (
            {"transcript_persistence_status": persistence_status}
            if persistence_status is not None else {}
        )
        yield ChatStreamChunk(
            type=ChatStreamEventType.COMPLETE,
            content="",
            metadata=metadata,
        )

    events = [part async for part in coordinator.stream(upstream(), lease=lease)]
    assert [part.type for part in events] == [
        ChatStreamEventType.CONTENT, ChatStreamEventType.ERROR,
    ]
    assert events[-1].metadata["error_code"] == "CHAT_TRANSCRIPT_NOT_PERSISTED"
    assert repo.finalized == [
        ("run-unverified", "failed", "CHAT_TRANSCRIPT_NOT_PERSISTED")
    ]


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

@pytest.mark.asyncio
async def test_only_owned_run_can_be_cancelled() -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    await coordinator.admit(context(), "run-a")
    assert await coordinator.request_cancel(context(user=USER_B), run_id="run-a") is None
    assert await coordinator.request_cancel(context(tenant=TENANT_B), run_id="run-a") is None
    assert repo.cancel_intent is False
    assert await coordinator.request_cancel(context(), run_id="run-a") == "cancelling"
    assert repo.stop_requests[-1] == (TENANT_A, USER_A, THREAD, "run-a")


@pytest.mark.asyncio
async def test_worker_actually_cancels_blocked_provider_after_foreign_worker_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.runtime import chat_run_lifecycle

    monkeypatch.setattr(chat_run_lifecycle, "_heartbeat_seconds", lambda: 0.002)
    repo = MemoryLedger()
    coordinator1 = ChatRunCoordinator(repo)
    coordinator2 = ChatRunCoordinator(repo)
    lease = await coordinator1.admit(context(), "run-blocked")
    aborted = asyncio.Event()

    async def blocked_provider():
        try:
            yield content("first-token")
            await asyncio.sleep(1)
            yield completed()
        finally:
            aborted.set()

    stream = coordinator1.stream(blocked_provider(), lease=lease)
    assert (await anext(stream)).content == "first-token"

    # This coordinator is a different process-equivalent instance sharing
    # only the canonical PostgreSQL-like repository contract.
    assert await coordinator2.request_cancel(context(), run_id="run-blocked") == "cancelling"
    with pytest.raises(ChatRunCancellationRequested):
        async for _chunk in stream:
            pass
    assert aborted.is_set()
    assert repo.finalized == [
        ("run-blocked", "cancelled", "CHAT_STREAM_CANCELLED"),
    ]


@pytest.mark.asyncio
async def test_stop_winning_terminal_race_never_emits_success() -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-terminal")
    repo.cancel_intent = True

    async def almost_complete():
        yield completed()

    with pytest.raises(ChatRunCancellationRequested):
        async for chunk in coordinator.stream(almost_complete(), lease=lease):
            assert chunk.type != ChatStreamEventType.COMPLETE
    assert repo.finalized == [
        ("run-terminal", "cancelled", "CHAT_STREAM_CANCELLED"),
    ]

@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_kind", ["error", "missing"])
async def test_concurrent_stop_wins_error_or_missing_terminal_race(
    terminal_kind: str,
) -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-fail-race")

    # Inject cancellation exactly as an ordinary terminal write attempts to
    # commit. The run must finalize 'cancelled', never stick at 'cancelling'.
    original_finish = repo.finish
    first = True

    async def racing_finish(lease, *, status, error_code=None):
        nonlocal first
        if first and status == "failed":
            first = False
            repo.cancel_intent = True
            return False
        return await original_finish(lease, status=status, error_code=error_code)

    repo.finish = racing_finish  # type: ignore[method-assign]

    async def failed_upstream():
        if terminal_kind == "error":
            yield ChatStreamChunk(
                type=ChatStreamEventType.ERROR,
                content="Provider reported an error",
            )
        else:
            yield content("partial")

    with pytest.raises(ChatRunCancellationRequested):
        async for _chunk in coordinator.stream(failed_upstream(), lease=lease):
            pass
    assert repo.finalized == [
        ("run-fail-race", "cancelled", "CHAT_STREAM_CANCELLED"),
    ]


@pytest.mark.asyncio
async def test_upstream_shutdown_failure_never_confirms_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_karen_engine.core.runtime import chat_run_lifecycle

    monkeypatch.setattr(chat_run_lifecycle, "_heartbeat_seconds", lambda: 0.002)
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-cleanup-fails")

    async def uncooperative_upstream():
        try:
            yield content("partial")
            await asyncio.sleep(1)
        finally:
            raise RuntimeError("upstream_cleanup_failed")

    stream = coordinator.stream(uncooperative_upstream(), lease=lease)
    assert (await anext(stream)).content == "partial"
    repo.cancel_intent = True
    with pytest.raises(RuntimeError, match="upstream_cleanup_failed"):
        async for _ in stream:
            pass
    assert repo.finalized == []

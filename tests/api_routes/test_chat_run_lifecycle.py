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
CORRELATION_ID = "correlation-1"


def context(*, user: str = USER_A, tenant: str = TENANT_A) -> ChatExecutionContext:
    return ChatExecutionContext(
        user_id=user,
        tenant_id=tenant,
        session_id="canonical-session",
        conversation_id=THREAD,
        request_id="request-1",
        correlation_id=CORRELATION_ID,
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

    async def completed(self, lease: ChatRunLease) -> bool:
        return any(
            run_id == lease.transport_run_id and status == "completed"
            for run_id, status, _ in self.finalized
        )

    async def committed_turn(
        self, lease: ChatRunLease, *,
        user_message_id: str, assistant_message_id: str,
    ) -> bool:
        if not self.allow_finish or self.cancel_intent:
            return False
        self.finalized.append((lease.transport_run_id, "completed", None))
        return True

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
    return ChatStreamChunk(
        type=ChatStreamEventType.CONTENT, content=text,
        correlation_id=CORRELATION_ID,
    )


def completed() -> ChatStreamChunk:
    return ChatStreamChunk(
        type=ChatStreamEventType.COMPLETE,
        content="",
        correlation_id=CORRELATION_ID,
        metadata={
            "transcript_persistence_status": "persisted",
            "user_message_id": "11111111-1111-5111-8111-111111111111",
            "assistant_message_id": "22222222-2222-5222-8222-222222222222",
        },
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
@pytest.mark.parametrize("persistence_status", ["persisted", "already_persisted"])
async def test_runtime_terminal_persists_before_success_chunk(
    persistence_status: str,
) -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-2")

    async def upstream():
        yield content()
        final = completed()
        final.metadata["transcript_persistence_status"] = persistence_status
        yield final

    events = []
    async for chunk in coordinator.stream(upstream(), lease=lease):
        if chunk.type == ChatStreamEventType.COMPLETE:
            assert repo.finalized == [("run-2", "completed", None)]
        events.append(chunk.type)

    assert events == [ChatStreamEventType.CONTENT, ChatStreamEventType.COMPLETE]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "persistence_status",
    [
        None, "failed", "rejected", "skipped", "PERSISTED",
        [], {}, ["persisted"], {"status": "persisted"}, 0, True,
    ],
)
async def test_unverified_transcript_never_emits_run_completion(
    persistence_status: object,
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
            correlation_id=CORRELATION_ID,
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
@pytest.mark.parametrize(
    "foreign_event",
    ["content", "error", "complete", "after_content"],
)
async def test_foreign_correlation_chunk_is_fenced_before_any_unowned_terminal(
    foreign_event: str,
) -> None:
    """A well-formed foreign trace ID is never an owned execution receipt."""
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), f"foreign-{foreign_event}")
    closed = asyncio.Event()

    async def upstream():
        try:
            if foreign_event == "after_content":
                yield content("owned-prefix")
                foreign = completed()
            elif foreign_event == "complete":
                foreign = completed()
            elif foreign_event == "error":
                foreign = ChatStreamChunk(
                    type=ChatStreamEventType.ERROR,
                    content="Unowned provider error",
                    correlation_id="forged-foreign-correlation",
                )
            else:
                foreign = ChatStreamChunk(
                    type=ChatStreamEventType.CONTENT,
                    content="Unowned provider text",
                    correlation_id="forged-foreign-correlation",
                )
            foreign.correlation_id = "forged-foreign-correlation"
            yield foreign
            yield completed()  # A valid later completion cannot revive this run.
        finally:
            closed.set()

    received = []
    with pytest.raises(ChatRunLeaseLost, match="chat_run_correlation_mismatch"):
        async for chunk in coordinator.stream(upstream(), lease=lease):
            received.append(chunk)

    assert [chunk.type for chunk in received] == (
        [ChatStreamEventType.CONTENT] if foreign_event == "after_content" else []
    )
    assert all(chunk.correlation_id == lease.correlation_id for chunk in received)
    assert all(chunk.type != ChatStreamEventType.COMPLETE for chunk in received)
    assert closed.is_set()
    assert repo.finalized == [
        (f"foreign-{foreign_event}", "failed", "CHAT_RUN_LEASE_LOST")
    ]


@pytest.mark.asyncio
async def test_failed_terminal_commit_cannot_claim_success() -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-3")
    repo.allow_finish = False

    async def upstream():
        yield completed()

    with pytest.raises(ChatRunLeaseLost, match="chat_run_atomic_commit_not_verified"):
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

    # A second worker run must not inherit the first run's committed state.
    blocked_lease = await coordinator.admit(context(), "run-5-blocked")
    repo.allow_renew = False
    closed = asyncio.Event()

    async def blocked_upstream():
        try:
            await asyncio.sleep(1)
            yield completed()
        finally:
            closed.set()

    with pytest.raises(ChatRunLeaseLost):
        async for _ in coordinator.stream(blocked_upstream(), lease=blocked_lease):
            pass
    assert closed.is_set()
    assert repo.finalized[-1] == ("run-5-blocked", "failed", "CHAT_RUN_LEASE_LOST")


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
                correlation_id=CORRELATION_ID,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("loss_kind", ["stop", "stolen_lease"])
async def test_fast_revocable_presentation_is_fenced_at_delivery(
    monkeypatch: pytest.MonkeyPatch,
    loss_kind: str,
) -> None:
    """No queued source card may escape after a stop or lost worker lease."""
    from ai_karen_engine.core.runtime import chat_run_lifecycle

    # The stream is too fast for the ordinary heartbeat check; this test
    # specifically proves presentation-time reauthorization.
    monkeypatch.setattr(chat_run_lifecycle, "_heartbeat_seconds", lambda: 3600)
    repo = MemoryLedger()
    reader = ChatRunCoordinator(repo)
    stopper = ChatRunCoordinator(repo)
    lease = await reader.admit(context(), f"presentation-{loss_kind}")
    sensitive_code = "print('revocable source never delivered after stop')"

    async def fast_source_stream():
        yield content("authorized prefix")
        yield ChatStreamChunk(
            type=ChatStreamEventType.PRESENTATION,
            content="",
            correlation_id=CORRELATION_ID,
            metadata={
                "presentation_verified": True,
                "presentation": {
                    "schema_version": 1,
                    "component_type": "code.artifact",
                    "data": {"filename": "private.py", "code": sensitive_code},
                },
            },
        )
        yield completed()

    stream = reader.stream(fast_source_stream(), lease=lease)
    delivered = [await anext(stream)]
    assert delivered[0].content == "authorized prefix"
    if loss_kind == "stop":
        assert await stopper.request_cancel(
            context(), run_id=lease.transport_run_id,
        ) == "cancelling"
        expected_error = ChatRunCancellationRequested
        expected_final = "cancelled"
    else:
        repo.allow_renew = False
        expected_error = ChatRunLeaseLost
        expected_final = "failed"

    with pytest.raises(expected_error):
        async for chunk in stream:
            delivered.append(chunk)

    assert [chunk.type for chunk in delivered] == [ChatStreamEventType.CONTENT]
    assert sensitive_code not in repr(delivered)
    assert repo.heartbeat_count == 1
    assert repo.finalized == [(
        lease.transport_run_id,
        expected_final,
        "CHAT_STREAM_CANCELLED" if loss_kind == "stop" else "CHAT_RUN_LEASE_LOST",
    )]


@pytest.mark.asyncio
async def test_active_fast_presentation_retains_authorized_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extra source guard must not suppress an otherwise authorized card."""
    from ai_karen_engine.core.runtime import chat_run_lifecycle

    monkeypatch.setattr(chat_run_lifecycle, "_heartbeat_seconds", lambda: 3600)
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "presentation-active")

    async def allowed_source():
        yield ChatStreamChunk(
            type=ChatStreamEventType.PRESENTATION,
            content="",
            correlation_id=CORRELATION_ID,
            metadata={"presentation_verified": True, "presentation": {
                "component_type": "code.artifact",
                "data": {"filename": "authorized.py", "code": "print('ok')"},
            }},
        )
        yield completed()

    observed = [chunk async for chunk in coordinator.stream(
        allowed_source(), lease=lease,
    )]
    assert [c.type for c in observed] == [
        ChatStreamEventType.PRESENTATION, ChatStreamEventType.COMPLETE,
    ]
    assert observed[0].metadata["presentation"]["data"]["code"] == "print('ok')"
    assert repo.heartbeat_count == 1
    assert repo.finalized == [("presentation-active", "completed", None)]


@pytest.mark.asyncio
async def test_legacy_journal_replay_withholds_code_in_extra_top_level_fields() -> None:
    """Historical event JSON cannot move source outside value to defeat replay scrub."""
    sensitive_source = "print('legacy top-level source must stay private')"
    legacy_event = {
        "type": "CUSTOM",
        "name": "karen.presentation.v1",
        "value": {"component_type": "data.table", "data": {"rows": []}},
        "extension": {
            "metadata": {
                "component_type": "code.artifact",
                "data": {"code": sensitive_source},
            },
        },
    }

    class LegacyJournal:
        def __init__(self) -> None:
            self.calls = []

        async def read_projected_events(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return {
                "threadId": THREAD,
                "runId": "legacy-owned",
                "owner_user_id": USER_A,
                "owner_tenant_id": TENANT_A,
                "events": [
                    {"seq": 1, "event": {"type": "RUN_STARTED",
                                         "threadId": THREAD, "runId": "legacy-owned"}},
                    {"seq": 2, "event": legacy_event},
                    {"seq": 3, "event": {"type": "RUN_ERROR", "message": "cancelled"}},
                ],
                "nextCursor": 3,
                "hasMore": False,
                "runStatus": "cancelled",
                "terminalConfirmed": True,
                "journalTerminalObserved": True,
                "continuationAvailable": False,
                "responseSource": "observed_event_journal",
            }

    journal = LegacyJournal()
    observed = await ChatRunCoordinator(journal).read_observed_events(
        context(), run_id="legacy-owned", after=0, limit=50,
    )
    assert observed is not None
    assert [entry["seq"] for entry in observed["events"]] == [1, 2, 3]
    assert observed["events"][1]["event"] == {
        "type": "CUSTOM",
        "name": "karen.presentation.withheld.v1",
        "value": {"reason": "revocable_code_not_replayable"},
    }
    assert observed["events"][2]["event"]["type"] == "RUN_ERROR"
    assert observed["nextCursor"] == 3
    assert observed["runStatus"] == "cancelled"
    assert observed["terminalConfirmed"] is True
    assert sensitive_source not in repr(observed)
    assert journal.calls == [{
        "tenant_id": TENANT_A,
        "user_id": USER_A,
        "conversation_id": THREAD,
        "transport_run_id": "legacy-owned",
        "after": 0,
        "limit": 50,
    }]


def test_whole_event_source_scrub_preserves_benign_presentation() -> None:
    event = {
        "type": "CUSTOM",
        "name": "karen.presentation.v1",
        "value": {
            "component_type": "data.table",
            "data": {"rows": [{"name": "harmless"}]},
        },
    }
    assert ChatRunCoordinator._journal_safe_event(event) == event


@pytest.mark.asyncio
async def test_uncertain_commit_leaves_durable_finality_unchanged() -> None:
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-uncertain")

    async def upstream():
        yield content()
        final = completed()
        final.metadata["transcript_persistence_status"] = "unverified"
        yield final

    events = [chunk async for chunk in coordinator.stream(upstream(), lease=lease)]
    assert [chunk.type for chunk in events] == [
        ChatStreamEventType.CONTENT, ChatStreamEventType.ERROR,
    ]
    assert events[-1].metadata["error_code"] == "CHAT_TRANSCRIPT_FINALITY_UNVERIFIED"
    assert events[-1].metadata["requires_retry"] is False
    assert repo.finalized == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["error", "gated", "not_persisted"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_failure_terminal_waits_for_strict_upstream_cleanup(kind, cleanup_fails):
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-cleanup-before-failure")
    observations = []

    async def upstream():
        try:
            if kind == "error":
                yield ChatStreamChunk(
                    type=ChatStreamEventType.ERROR,
                    content="Provider error",
                    correlation_id=CORRELATION_ID,
                )
            else:
                terminal = completed()
                terminal.metadata["transcript_persistence_status"] = "not_persisted"
                if kind == "gated":
                    terminal.metadata["status"] = "gate"
                yield terminal
        finally:
            observations.append(list(repo.finalized))
            if cleanup_fails:
                raise RuntimeError("upstream_cleanup_failed")

    stream = coordinator.stream(upstream(), lease=lease)
    if cleanup_fails:
        with pytest.raises(RuntimeError, match="upstream_cleanup_failed"):
            await anext(stream)
        assert repo.finalized == []
    else:
        assert (await anext(stream)).type == ChatStreamEventType.ERROR
        assert len(repo.finalized) == 1
        assert repo.finalized[0][1] == "failed"
    await stream.aclose()
    assert observations == [[]]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_native_retirement_failure_never_resolves_chat_admission(monkeypatch, cancelled):
    from ai_karen_engine.core.model_runtime.provider_contracts import NativeRetirementUnverified
    from ai_karen_engine.core.runtime import chat_run_lifecycle

    monkeypatch.setattr(chat_run_lifecycle, "_heartbeat_seconds", lambda: 0.002)
    repo = MemoryLedger()
    coordinator = ChatRunCoordinator(repo)
    lease = await coordinator.admit(context(), "run-native-retirement")

    async def upstream():
        yield content("partial")
        if cancelled:
            try:
                await asyncio.sleep(1)
            finally:
                raise NativeRetirementUnverified()
        raise NativeRetirementUnverified()

    stream = coordinator.stream(upstream(), lease=lease)
    assert (await anext(stream)).content == "partial"
    repo.cancel_intent = cancelled
    with pytest.raises(NativeRetirementUnverified):
        async for _ in stream:
            pytest.fail("unexpected output after unverified retirement")
    assert repo.finalized == []


@pytest.mark.asyncio
async def test_coordinator_passes_exact_attachment_draft_hints_after_ownership():
    from unittest.mock import AsyncMock
    from ai_karen_engine.services.database.repositories.conversation_repository import (
        draft_attachment_selection_digest,
    )

    refs = [{"source_id": THREAD, "revision": "a" * 64}]
    submission = "draft-v2-3-" + draft_attachment_selection_digest(refs)
    lease = ChatRunLease(
        execution_id="33333333-3333-4333-8333-333333333333",
        lease_token="44444444-4444-4444-8444-444444444444",
        tenant_id=TENANT_A, user_id=USER_A, conversation_id=THREAD,
        transport_run_id="attachment-run", request_id="request-1",
        correlation_id=CORRELATION_ID, submission_id=submission,
    )
    repo = AsyncMock()
    repo.admit.return_value = lease
    assert await ChatRunCoordinator(repo).admit(
        context(), "attachment-run", submission_id=submission,
        submitted_text="Read attachment", submitted_attachment_references=refs,
    ) is lease
    repo.admit.assert_awaited_once_with(
        tenant_id=TENANT_A, user_id=USER_A, conversation_id=THREAD,
        transport_run_id="attachment-run", request_id="request-1",
        correlation_id=CORRELATION_ID, submission_id=submission,
        submitted_text="Read attachment", submitted_attachment_references=refs,
    )



@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [False, True])
@pytest.mark.parametrize("foreign", [False, True])
async def test_retry_coordinator_reauthorizes_before_repository(monkeypatch, mutation, foreign):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from ai_karen_engine.core.runtime import chat_run_lifecycle

    ownership = AsyncMock(side_effect=PermissionError("foreign") if foreign else None)
    monkeypatch.setattr(chat_run_lifecycle, "get_conversation_runtime_gateway",
                        lambda: SimpleNamespace(require_owned_conversation=ownership))
    repo = SimpleNamespace(
        read_failed_draft_revision=AsyncMock(return_value={"eligible": True, "prepared_revision": None, "prepared_current": False}),
        advance_failed_draft_revision=AsyncMock(return_value=8),
    )
    coordinator = ChatRunCoordinator(repo)
    ctx = context()
    async def invoke():
        if mutation:
            return await coordinator.advance_failed_draft_revision(
                ctx, submission_id="draft-v1-7", submitted_text="retained", attachment_references=[],
            )
        return await coordinator.read_failed_draft_revision(ctx, submission_id="draft-v1-7")
    if foreign:
        with pytest.raises(PermissionError):
            await invoke()
        repo.read_failed_draft_revision.assert_not_awaited()
        repo.advance_failed_draft_revision.assert_not_awaited()
    else:
        assert await invoke() == (8 if mutation else {
            "eligible": True, "prepared_revision": None, "prepared_current": False,
        })
        operation = repo.advance_failed_draft_revision if mutation else repo.read_failed_draft_revision
        operation.assert_awaited_once_with(
            tenant_id=TENANT_A, user_id=USER_A, conversation_id=THREAD,
            submission_id="draft-v1-7",
            **({"submitted_text": "retained", "attachment_references": []} if mutation else {}),
        )
    ownership.assert_awaited_once_with(ctx)

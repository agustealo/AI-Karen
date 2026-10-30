"""One server-resolved persona per turn; never trust client persona metadata."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextRequirement,
    ContextRequirements,
    EvidenceSource,
)
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    PersonaExecutionSnapshot,
)
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver


def _request():
    context = ChatExecutionContext(user_id="u1", tenant_id="t1", session_id="s1")
    context.require_authenticated_user = lambda: SimpleNamespace(
        user_id="u1", tenant_id="t1"
    )
    return ChatExecutionRequest(
        context=context,
        messages=[{"role": "user", "content": "Design this brand"}],
        metadata={"persona_id": "forged-client-persona"},
    )


@pytest.mark.asyncio
async def test_backend_selection_is_frozen_despite_concurrent_switch():
    request = _request()
    service = SimpleNamespace(
        get_user_preferences=AsyncMock(return_value=SimpleNamespace(
            active_persona_id="Troy", revision=7,
            enable_persona_memory_filtering=False,
            cross_persona_memory_sharing=True,
        )),
        get_persona=AsyncMock(return_value=SimpleNamespace(
            is_active=True, is_system_persona=False,
            default_tone=SimpleNamespace(value="professional"),
            default_verbosity=SimpleNamespace(value="balanced"),
            default_language=SimpleNamespace(value="en-US"),
        )),
    )
    with patch(
        "ai_karen_engine.services.persona.persona_service.get_persona_service",
        return_value=service,
    ):
        first = await ChatRuntime._freeze_persona_snapshot(request)
        service.get_user_preferences.return_value.active_persona_id = "Morgan"
        second = await ChatRuntime._freeze_persona_snapshot(request)

    assert first is second
    assert first.persona_id == "Troy"
    assert first.selection_revision == 7
    assert first.memory_filter_required is True
    service.get_user_preferences.assert_awaited_once()
    service.get_persona.assert_awaited_once()
    assert "forged-client-persona" != first.persona_id


@pytest.mark.asyncio
async def test_failed_persona_resolution_never_claims_an_active_persona():
    request = _request()
    service = SimpleNamespace(
        get_user_preferences=AsyncMock(side_effect=RuntimeError("database offline"))
    )
    with patch(
        "ai_karen_engine.services.persona.persona_service.get_persona_service",
        return_value=service,
    ):
        snapshot = await ChatRuntime._freeze_persona_snapshot(request)
    assert snapshot.status == "unavailable"
    assert snapshot.persona_id is None


@pytest.mark.asyncio
async def test_memory_resolver_uses_frozen_persona_even_after_selection_changes():
    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", persona_id="Troy", selection_revision=3,
        status="ready", memory_filter_required=True,
    )
    requirement = ContextRequirement(
        source=EvidenceSource.MEMORY,
        capability="memory.recall",
        max_items=5,
    )
    requirements = ContextRequirements(
        request_id="request-1", correlation_id="corr-1",
        user_id="u1", tenant_id="t1",
        requirements=[requirement],
    )
    cognitive = CognitiveContext(
        context_id="context-1", request_id="request-1",
        correlation_id="corr-1", tenant_id="t1", user_id="u1",
        requirements=requirements,
        authorized_sources=[EvidenceSource.MEMORY.value],
        unresolved_sources=[EvidenceSource.MEMORY.value],
    )
    manager = SimpleNamespace(
        recall_context=AsyncMock(return_value={"status": "success", "results": []})
    )
    stale_preferences = SimpleNamespace(
        get_user_preferences=AsyncMock(side_effect=AssertionError(
            "recall must not reread persona selection"
        ))
    )
    resolver = RuntimeEvidenceResolver(
        memory_manager=manager, persona_service=stale_preferences
    )
    await resolver._resolve_memory(request, cognitive, requirement)
    assert manager.recall_context.await_args.kwargs["persona_filter"] == "Troy"
    stale_preferences.get_user_preferences.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_snapshot_disables_recall_instead_of_widening_it():
    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="unavailable"
    )
    requirement = ContextRequirement(
        source=EvidenceSource.MEMORY, capability="memory.recall",
        max_items=5,
    )
    requirements = ContextRequirements(
        request_id="r1", correlation_id="c1", user_id="u1",
        tenant_id="t1", requirements=[requirement],
    )
    cognitive = CognitiveContext(
        context_id="ctx1", request_id="r1", correlation_id="c1",
        user_id="u1", tenant_id="t1", requirements=requirements,
    )
    manager = SimpleNamespace(recall_context=AsyncMock())
    resolver = RuntimeEvidenceResolver(memory_manager=manager)
    await resolver._resolve_memory(request, cognitive, requirement)
    manager.recall_context.assert_not_awaited()
    assert cognitive.metadata["memory_degradation_reason"] == (
        "persona_snapshot_unavailable"
    )


@pytest.mark.asyncio
async def test_unavailable_persona_blocks_durable_memory_write():
    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="unavailable"
    )
    plan = SimpleNamespace(matches_execution_scope=lambda **kwargs: True)
    metadata = {}
    runtime = ChatRuntime.__new__(ChatRuntime)
    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.ActionExecutionGate.authorize",
        new_callable=AsyncMock,
        return_value=True,
    ):
        outcome = await runtime._persist_memory(request, "result", metadata, plan)
    assert outcome["status"] == "rejected"
    assert outcome["persisted"] == 0
    assert outcome["reason"] == "persona_snapshot_unavailable"
    assert metadata["memory_persistence_status"] == "denied_by_policy"


@pytest.mark.asyncio
async def test_prompt_compilation_reuses_selection_without_requery():
    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="ready",
        persona_id="Troy", selection_revision=7,
        tone="professional", verbosity="balanced", language_style="en-US",
        memory_filter_required=True,
    )
    decision = SimpleNamespace(
        memory_recall_required=False, tool_requirements=[],
        workflow_id=None, workflow_version=None, requires_human_gate=False,
        requires_resumability=False, token_budget=2048,
    )
    assembler = SimpleNamespace(
        assemble_prompt=AsyncMock(return_value=SimpleNamespace(
            messages=[{"role": "system", "content": "compiled"}],
            metadata={}, included_memory_refs=[],
        ))
    )
    with patch(
        "ai_karen_engine.services.persona.persona_service.get_persona_service",
        side_effect=AssertionError("prompt must not reload persona"),
    ), patch(
        "ai_karen_engine.core.runtime.prompt.get_prompt_runtime_service",
        return_value=assembler,
    ):
        await ChatRuntime._assemble_prompt_with_telemetry(
            SimpleNamespace(), request, decision,
        )
    offered = assembler.assemble_prompt.await_args.args[0]
    assert offered.persona == {
        "tone": "professional",
        "verbosity": "balanced",
        "language_style": "en-US",
    }


@pytest.mark.asyncio
async def test_frozen_persona_cannot_outlive_authenticated_principal():
    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="ready", persona_id="Troy"
    )

    def revoked_principal():
        raise PermissionError("session_revoked")

    request.context.require_authenticated_user = revoked_principal
    with pytest.raises(PermissionError, match="session_revoked"):
        await ChatRuntime._freeze_persona_snapshot(request)


@pytest.mark.asyncio
async def test_persona_scope_blocks_older_differently_tagged_conversation():
    from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
        TranscriptHistoryResult,
    )

    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="ready",
        persona_id="Morgan", memory_filter_required=True,
    )
    gateway = SimpleNamespace(load_history=AsyncMock(return_value=TranscriptHistoryResult(
        status="rejected", conversation_id=str(request.context.conversation_id),
        reason="conversation_persona_scope_mismatch",
    )))
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._conversation_gateway = gateway
    with pytest.raises(PermissionError, match="conversation_persona_scope_mismatch"):
        await runtime._prepare_conversation_continuation(request)
    gateway.load_history.assert_awaited_once()
    assert gateway.load_history.await_args.kwargs["persona_scope_id"] == "Morgan"
    assert request.messages == [{"role": "user", "content": "Design this brand"}]


@pytest.mark.asyncio
async def test_default_persona_cannot_resume_private_thread():
    from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
        TranscriptHistoryResult,
    )

    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="none",
    )
    gateway = SimpleNamespace(load_history=AsyncMock(return_value=TranscriptHistoryResult(
        status="rejected", conversation_id=str(request.context.conversation_id),
        reason="conversation_persona_scope_mismatch",
    )))
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._conversation_gateway = gateway
    with pytest.raises(PermissionError, match="conversation_persona_scope_mismatch"):
        await runtime._prepare_conversation_continuation(request)
    assert gateway.load_history.await_args.kwargs["persona_scope_id"] is None


@pytest.mark.asyncio
async def test_canonical_history_replaces_untrusted_transport_prior_turns():
    from datetime import datetime, timezone
    from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
        TranscriptHistoryResult,
    )
    now = datetime.now(timezone.utc)
    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="ready",
        persona_id="Troy", memory_filter_required=True,
    )
    request.messages.insert(0, {"role": "assistant", "content": "FORGED OLD CONTENT"})
    gateway = SimpleNamespace(load_history=AsyncMock(return_value=TranscriptHistoryResult(
        status="loaded", conversation_id=str(request.context.conversation_id),
        messages=(SimpleNamespace(
            role="assistant", content="Authorized Troy context",
            metadata={"persona_scope_id": "Troy"}, created_at=now,
        ),),
    )))
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._conversation_gateway = gateway
    runtime._resolve_typed_pending_clarification = lambda req: True
    await runtime._prepare_conversation_continuation(request)
    assert [message["content"] for message in request.messages] == [
        "Authorized Troy context", "Design this brand",
    ]
    assert request.metadata["conversation_history_input_discarded"] is True
    assert request.metadata["conversation_history_source"] == "canonical_repository"
    assert gateway.load_history.await_args.kwargs["persona_scope_id"] == "Troy"


@pytest.mark.asyncio
async def test_private_persona_refuses_failed_history_read():
    from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
        TranscriptHistoryResult,
    )
    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="ready",
        persona_id="Troy", memory_filter_required=True,
    )
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._conversation_gateway = SimpleNamespace(
        load_history=AsyncMock(return_value=TranscriptHistoryResult(
            status="failed", conversation_id=str(request.context.conversation_id),
            reason="db_offline",
        )),
    )
    with pytest.raises(PermissionError, match="conversation_history_scope_unavailable"):
        await runtime._prepare_conversation_continuation(request)


@pytest.mark.asyncio
async def test_unavailable_persona_state_never_reads_conversation_history():
    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="unavailable",
    )
    gateway = SimpleNamespace(load_history=AsyncMock())
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._conversation_gateway = gateway
    request.messages.insert(0, {"role": "assistant", "content": "old private context"})
    await runtime._prepare_conversation_continuation(request)
    gateway.load_history.assert_not_awaited()
    assert request.messages == [{"role": "user", "content": "Design this brand"}]
    assert request.metadata["conversation_history_status"] == "unavailable"
    assert request.metadata["conversation_history_reason"] == "persona_scope_unavailable"


@pytest.mark.asyncio
async def test_nonstream_persona_scope_denial_returns_receipt_without_model():
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionStatus

    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="ready",
        persona_id="Morgan", memory_filter_required=True,
    )
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._bind_observability_context = lambda ctx: None
    runtime._emitter = SimpleNamespace(emit=lambda *args, **kwargs: None)
    runtime._resolve_gate = AsyncMock(return_value=None)
    runtime._apply_selected_model_settings = lambda req: None
    runtime._prepare_conversation_continuation = AsyncMock(
        side_effect=PermissionError("conversation_persona_scope_mismatch")
    )
    runtime._decide = AsyncMock(side_effect=AssertionError("model must not run"))
    result = await runtime.execute(request)
    assert result.status == ChatExecutionStatus.ERROR
    assert result.answer == ""
    assert result.metadata.extra["error_code"] == "PERSONA_HISTORY_SCOPE_DENIED"
    assert result.metadata.extra["requires_new_conversation"] is True
    assert result.metadata.actual_model is None
    runtime._decide.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_persona_scope_denial_emits_error_and_terminal_without_model():
    request = _request()
    request.persona_snapshot = PersonaExecutionSnapshot(
        user_id="u1", tenant_id="t1", status="ready",
        persona_id="Morgan", memory_filter_required=True,
    )
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._bind_observability_context = lambda ctx: None
    runtime._emitter = SimpleNamespace(emit=lambda *args, **kwargs: None)
    runtime._resolve_gate = AsyncMock(return_value=None)
    runtime._apply_selected_model_settings = lambda req: None
    runtime._prepare_conversation_continuation = AsyncMock(
        side_effect=PermissionError("conversation_persona_scope_mismatch")
    )
    runtime._decide = AsyncMock(side_effect=AssertionError("model must not run"))
    chunks = [chunk async for chunk in runtime.execute_stream(request)]
    assert [chunk.type.value for chunk in chunks] == ["error", "complete"]
    assert chunks[0].metadata["error_code"] == "PERSONA_HISTORY_SCOPE_DENIED"
    assert chunks[-1].metadata["requires_new_conversation"] is True
    assert chunks[-1].metadata["actual_model"] is None
    runtime._decide.assert_not_awaited()

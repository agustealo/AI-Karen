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

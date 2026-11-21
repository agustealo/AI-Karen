from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextEvidence,
    ContextRequirement,
    ContextRequirements,
    EvidenceProvenance,
    EvidenceScope,
    EvidenceSource,
    EvidenceTemporalContext,
)
from ai_karen_engine.core.cortex.context_stages import finalize_decision_with_context
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


class AvailablePersonaPreferences:
    active_persona_id = "assistant"
    enable_persona_memory_filtering = True
    cross_persona_memory_sharing = False


class RecordingPersonaService:
    async def get_user_preferences(self, *, user_id: str, tenant_id: str):
        assert user_id == "user-1"
        assert bool(tenant_id)
        return AvailablePersonaPreferences()


class RecordingMemoryManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def recall_context(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return {
            "results": [
                {
                    "id": "memory-1",
                    "content": "User prefers local-first execution.",
                    "timestamp": 1_700_000_000.0,
                    "similarity_score": 0.91,
                    "memory_type": "semantic",
                    "metadata": {"confidence": 0.87},
                }
            ],
            "status": "success",
            "source": "neuro_recall",
            "degraded": False,
            "degradation_reason": None,
            "provenance": ["postgres"],
            "latency_ms": 8.5,
        }


class RejectingMemoryManager:
    async def recall_context(self, **kwargs: object) -> dict[str, object]:
        del kwargs
        raise RuntimeError("explicit non-default tenant_id is required for memory recall")


def _request(*, tenant_id: str = "tenant-1") -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "Use what you remember about my runtime."}],
        context=ChatExecutionContext(
            user_id="user-1",
            tenant_id=tenant_id,
            session_id="session-1",
            conversation_id="conversation-1",
            request_id="request-1",
            correlation_id="correlation-1",
        ),
    )


def _authorized_context(request: ChatExecutionRequest) -> CognitiveContext:
    ctx = request.context
    requirements = ContextRequirements(
        request_id=ctx.request_id or "",
        correlation_id=ctx.correlation_id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        conversation_id=ctx.conversation_id,
        requirements=[
            ContextRequirement(
                source=EvidenceSource.MEMORY,
                capability="memory.read",
                scopes=["session"],
                classes=["semantic"],
                max_items=5,
            )
        ],
    )
    return CognitiveContext(
        context_id="context-1",
        request_id=ctx.request_id or "",
        correlation_id=ctx.correlation_id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        requirements=requirements,
        authorized_sources=[EvidenceSource.MEMORY.value],
        unresolved_sources=[EvidenceSource.MEMORY.value],
        policy_decision_id="policy-context-1",
    )


@pytest.mark.asyncio
async def test_runtime_evidence_resolver_calls_memory_authority_once_and_types_result() -> None:
    request = _request()
    cognitive_context = _authorized_context(request)
    memory_manager = RecordingMemoryManager()
    resolver = RuntimeEvidenceResolver(memory_manager=memory_manager, persona_service=RecordingPersonaService())

    resolved = await resolver.resolve(request, cognitive_context)

    assert resolved is cognitive_context
    assert len(memory_manager.calls) == 1
    call = memory_manager.calls[0]
    assert call["tenant_id"] == "tenant-1"
    assert call["user_id"] == "user-1"
    assert call["conversation_id"] == "conversation-1"
    assert call["session_id"] == "session-1"
    assert call["request_id"] == "request-1"
    assert call["top_k"] == 5
    assert call["tiers"] == ("semantic",)

    assert resolved.unresolved_sources == []
    assert len(resolved.evidence) == 1
    evidence = resolved.evidence[0]
    assert evidence.source is EvidenceSource.MEMORY
    assert evidence.evidence_id == "memory-1"
    assert evidence.relevance == pytest.approx(0.91)
    assert evidence.confidence == pytest.approx(0.87)
    assert evidence.provenance.resolver_id == "runtime.evidence.memory"
    assert evidence.provenance.retrieval_method == "neuro_recall"
    assert evidence.scope is not None
    assert evidence.scope.tenant_id == "tenant-1"
    assert evidence.scope.user_id == "user-1"
    assert resolved.metadata["memory_recall_count"] == 1
    assert resolved.metadata["memory_response_source"] == "neuro_recall"


@pytest.mark.asyncio
async def test_failed_memory_scope_remains_unresolved_and_degraded() -> None:
    request = _request(tenant_id="default")
    cognitive_context = _authorized_context(request)
    resolver = RuntimeEvidenceResolver(memory_manager=RejectingMemoryManager(), persona_service=RecordingPersonaService())

    resolved = await resolver.resolve(request, cognitive_context)

    assert resolved.evidence == []
    assert resolved.unresolved_sources == [EvidenceSource.MEMORY.value]
    assert resolved.metadata["memory_recall_status"] == "failed"
    assert resolved.metadata["memory_degraded"] is True
    assert resolved.metadata["memory_degradation_reason"] == "memory_retrieval_unavailable"
    assert "tenant_id" not in str(resolved.metadata["memory_degradation_reason"])


@pytest.mark.asyncio
async def test_memory_recall_exceptions_never_enter_client_metadata_or_logs(caplog) -> None:
    class _SecretFailure:
        async def recall_context(self, **kwargs: object) -> dict[str, object]:
            raise RuntimeError("secret_database_password=never-log-this")

    resolver = RuntimeEvidenceResolver(memory_manager=_SecretFailure(), persona_service=RecordingPersonaService())
    resolved = await resolver.resolve(_request(), _authorized_context(_request()))
    assert resolved.metadata["memory_recall_status"] == "failed"
    assert resolved.metadata["memory_degradation_reason"] == "memory_retrieval_unavailable"
    assert "never-log-this" not in str(resolved.metadata)
    assert "never-log-this" not in caplog.text


def test_cortex_stage_2_carries_same_resolved_context() -> None:
    request = _request()
    cognitive_context = _authorized_context(request)
    now = datetime.now(timezone.utc)
    cognitive_context.evidence.append(
        ContextEvidence(
            evidence_id="memory-1",
            source=EvidenceSource.MEMORY,
            content="User prefers local-first execution.",
            source_ref="memory-1",
            relevance=0.91,
            confidence=0.87,
            provenance=EvidenceProvenance(
                source_ref="memory-1",
                source_record_id="memory-1",
                resolver_id="runtime.evidence.memory",
                resolver_version="1",
                retrieval_method="neuro_recall",
                retrieved_at=now,
            ),
            temporal=EvidenceTemporalContext(observed_at=now, as_of=now),
            scope=EvidenceScope(
                tenant_id="tenant-1",
                user_id="user-1",
                session_id="session-1",
                conversation_id="conversation-1",
            ),
        )
    )
    cognitive_context.unresolved_sources.clear()
    preliminary = ExecutionDecision(
        memory_recall_required=True,
        memory_top_k=5,
        required_capabilities=["memory.read"],
    )

    finalized = finalize_decision_with_context(preliminary, cognitive_context)

    assert finalized.cognitive_context is cognitive_context
    assert "context_memory_resolved" in finalized.reason_codes
    assert "context_memory_evidence_available" in finalized.reason_codes
    assert finalized.policy_constraints["context_memory_evidence_count"] == 1


@pytest.mark.asyncio
async def test_chat_runtime_consumes_typed_evidence_without_retrieving_again() -> None:
    request = _request()
    cognitive_context = _authorized_context(request)
    now = datetime.now(timezone.utc)
    cognitive_context.evidence.append(
        ContextEvidence(
            evidence_id="memory-1",
            source=EvidenceSource.MEMORY,
            content="User prefers local-first execution.",
            source_ref="memory-1",
            relevance=0.91,
            confidence=0.87,
            provenance=EvidenceProvenance(
                resolver_id="runtime.evidence.memory",
                retrieval_method="neuro_recall",
                retrieved_at=now,
            ),
            temporal=EvidenceTemporalContext(observed_at=now, as_of=now),
            scope=EvidenceScope(tenant_id="tenant-1", user_id="user-1"),
        )
    )
    cognitive_context.unresolved_sources.clear()
    cognitive_context.metadata.update(
        {
            "memory_recall_status": "success",
            "memory_recall_count": 1,
            "memory_latency_ms": 8.5,
            "memory_degraded": False,
        }
    )
    decision = ExecutionDecision(
        memory_recall_required=True,
        memory_top_k=5,
        cognitive_context=cognitive_context,
    )

    runtime = object.__new__(ChatRuntime)
    meta = await runtime._consume_resolved_memory(request, decision)

    assert not hasattr(ChatRuntime, "_recall_memory")
    assert meta["memory_recall_count"] == 1
    recall = meta["memory_context"]["recall"]
    assert recall == request.metadata["memory_context"]["recall"]
    assert recall[0]["id"] == "memory-1"
    assert recall[0]["content"] == "User prefers local-first execution."
    assert recall[0]["relevance"] == pytest.approx(0.91)
    assert recall[0]["confidence"] == pytest.approx(0.87)


@pytest.mark.asyncio
async def test_semantic_role_lookup_uses_governed_requirement_not_raw_weather_query() -> None:
    request = _request()
    request.messages[-1]["content"] = "What's the weather?"
    cognitive_context = _authorized_context(request)
    cognitive_context.requirements.requirements[0].metadata.update(
        {"semantic_role": "location.current", "retrieval_query": "Where am I currently?"}
    )
    memory_manager = RecordingMemoryManager()
    resolver = RuntimeEvidenceResolver(memory_manager=memory_manager, persona_service=RecordingPersonaService())

    await resolver.resolve(request, cognitive_context)

    assert len(memory_manager.calls) == 1
    assert memory_manager.calls[0]["query"] == "Where am I currently?"
    assert memory_manager.calls[0]["user_id"] == request.context.user_id
    assert memory_manager.calls[0]["tenant_id"] == request.context.tenant_id


def test_canonical_profile_recall_semantics_survive_typed_runtime_resolution():
    from ai_karen_engine.core.memory.semantic_contract import FactCardinality

    request = _request()
    metadata = {
        "source": "postgres_profile_fact",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "custom": {
            "source_store": "postgres",
            "profile_fact_id": "profile-1",
            "event_id": "event-1",
            "attribute": "favorite_artist",
            "cardinality": "set",
            "semantic_scope": {"domain": "music", "facet": "artist", "project_id": 42, "task_id": 2.5},
        },
    }
    item = {
        "id": "profile-1",
        "content": "favorite_artist: Bob Marley",
        "metadata": metadata,
    }
    resolver = RuntimeEvidenceResolver()
    parsed = resolver._memory_item_to_evidence(
        item, request=request, retrieved_at=datetime.now(timezone.utc),
    )
    assert parsed.fact_semantics is not None
    assert parsed.fact_semantics.attribute == "favorite_artist"
    assert parsed.fact_semantics.cardinality is FactCardinality.SET
    assert parsed.fact_semantics.semantic_scope == (
        ("domain", "music"), ("facet", "artist"),
        ("project_id", "42"), ("task_id", "2.5"),
    )

    # Tenant, principal, row identity and source identity must match before
    # retrieval metadata is permitted to influence belief cardinality.
    from copy import deepcopy

    for mutate in (
        lambda m: m.update({"tenant_id": "foreign-tenant"}),
        lambda m: m.update({"user_id": "foreign-user"}),
        lambda m: m.update({"source": "model_claim"}),
        lambda m: m["custom"].update({"profile_fact_id": "foreign-row"}),
        lambda m: m["custom"].update({"cardinality": "unverified"}),
        lambda m: m["custom"].update({"semantic_scope": {"unexpected": "value"}}),
        lambda m: m["custom"].update({"semantic_scope": {"project_id": True}}),
    ):
        forged = deepcopy(metadata)
        mutate(forged)
        untrusted = resolver._memory_item_to_evidence(
            {**item, "metadata": forged},
            request=request,
            retrieved_at=datetime.now(timezone.utc),
        )
        assert untrusted.fact_semantics is None


@pytest.mark.asyncio
async def test_persona_preference_outage_fails_closed_before_memory_recall() -> None:
    class UnavailablePersonaService:
        async def get_user_preferences(self, *, user_id: str, tenant_id: str):
            raise RuntimeError("secret-preference-backend-details")

    manager = RecordingMemoryManager()
    resolver = RuntimeEvidenceResolver(
        memory_manager=manager, persona_service=UnavailablePersonaService()
    )
    request = _request()
    context = _authorized_context(request)
    resolved = await resolver.resolve(request, context)

    assert manager.calls == []
    assert resolved.metadata["memory_degraded"] is True
    assert resolved.metadata["memory_degradation_reason"] == "persona_scope_unavailable"
    assert EvidenceSource.MEMORY.value in resolved.unresolved_sources


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filtering", "sharing", "active", "expected"),
    [
        (True, False, "expert", "expert"),
        (True, True, "expert", None),
        (False, False, "expert", None),
        (True, False, None, None),
    ],
)
async def test_persona_scope_respects_backend_memory_sharing_preferences(
    filtering: bool, sharing: bool, active: str | None, expected: str | None
) -> None:
    class ScopedPersonaService:
        async def get_user_preferences(self, *, user_id: str, tenant_id: str):
            assert user_id == "user-1"
            assert tenant_id == "tenant-1"
            from types import SimpleNamespace
            return SimpleNamespace(
                active_persona_id=active,
                enable_persona_memory_filtering=filtering,
                cross_persona_memory_sharing=sharing,
            )

    manager = RecordingMemoryManager()
    resolver = RuntimeEvidenceResolver(
        memory_manager=manager, persona_service=ScopedPersonaService()
    )
    request = _request()
    await resolver.resolve(request, _authorized_context(request))
    assert len(manager.calls) == 1
    assert manager.calls[0]["persona_filter"] == expected


@pytest.mark.parametrize(
    ("source", "record_type", "identity_key", "event_key"),
    [
        ("postgres_memory_ledger", "memory_assertion", "assertion_id", "event_id"),
        ("postgres_profile_fact", "profile_fact", "fact_id", "event_id"),
        ("postgres_procedure", "memory_procedure", "procedure_id", "source_event_id"),
        ("postgres_user_goal", "memory_user_goal", "goal_id", "event_id"),
        ("postgres_open_loop", "memory_open_loop", "open_loop_id", "event_id"),
        (
            "postgres_prospective_memory", "memory_prospective_item",
            "prospective_id", "event_id",
        ),
        ("postgres_graph", "memory_event", "event_id", "event_id"),
    ],
)
def test_canonical_event_origin_preserves_event_identity_without_acl_grant(
    source: str, record_type: str, identity_key: str, event_key: str,
) -> None:
    """Derived source rows must not masquerade as canonical event IDs."""
    record_id = "00000000-0000-4000-8000-000000000021"
    event_id = (
        record_id if source == "postgres_graph"
        else "00000000-0000-4000-8000-000000000022"
    )
    item = {
        "id": record_id,
        "content": "Selected memory",
        "metadata": {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "source": source,
            "custom": {
                event_key: event_id,
                "provenance": {
                    "store": "postgres",
                    "record_type": record_type,
                    identity_key: record_id,
                    event_key: event_id,
                    "source_type": "chat",
                },
            },
        },
    }
    request = _request()
    evidence = RuntimeEvidenceResolver._memory_item_to_evidence(
        item, request=request, retrieved_at=datetime.now(timezone.utc),
    )
    origin = evidence.metadata["canonical_event_origin"]
    assert origin == {
        "event_id": event_id,
        "record_id": record_id,
        "record_type": record_type,
        "source": source,
    }
    assert evidence.provenance.source_record_id == record_id

    from copy import deepcopy

    for alter in (
        lambda m: m.update({"tenant_id": "another-tenant"}),
        lambda m: m.update({"user_id": "another-user"}),
        lambda m: m["custom"]["provenance"].update({identity_key: event_id + "-fake"}),
        lambda m: m["custom"]["provenance"].update({event_key: "not-a-uuid"}),
        lambda m: m["custom"]["provenance"].update({"record_type": "other"}),
        lambda m: m["custom"].update({event_key: "different-event"}),
        lambda m: m["custom"]["provenance"].update({"source_type": ""}),
    ):
        forged = deepcopy(item)
        alter(forged["metadata"])
        denied = RuntimeEvidenceResolver._memory_item_to_evidence(
            forged, request=request, retrieved_at=datetime.now(timezone.utc),
        )
        assert denied.metadata["canonical_event_origin"] is None


def test_ephemeral_or_unknown_memory_origin_never_invents_ledger_identity() -> None:
    request = _request()
    for source in ("stm", "unknown", "model_claim", None):
        item = {
            "id": "00000000-0000-4000-8000-000000000099",
            "content": "Unverified source",
            "metadata": {
                "tenant_id": "tenant-1", "user_id": "user-1",
                "source": source,
                "custom": {
                    "event_id": "00000000-0000-4000-8000-000000000022",
                },
            },
        }
        evidence = RuntimeEvidenceResolver._memory_item_to_evidence(
            item, request=request, retrieved_at=datetime.now(timezone.utc),
        )
        assert evidence.metadata["canonical_event_origin"] is None


def test_canonical_event_origin_uses_selected_record_revision_not_custom_claim():
    item = {
        "id": "00000000-0000-4000-8000-000000000021",
        "updated_at": "2026-11-21T07:30:00",
        "metadata": {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "source": "postgres_memory_ledger",
            "custom": {
                "event_id": "00000000-0000-4000-8000-000000000022",
                "updated_at": "1900-01-01T00:00:00",
                "provenance": {
                    "store": "postgres",
                    "record_type": "memory_assertion",
                    "assertion_id": "00000000-0000-4000-8000-000000000021",
                    "event_id": "00000000-0000-4000-8000-000000000022",
                    "source_type": "chat_user",
                },
            },
        },
    }
    origin = RuntimeEvidenceResolver._canonical_memory_event_origin(
        item, tenant_id="tenant-1", user_id="user-1",
    )
    assert origin is not None
    assert origin["record_updated_at"] == "2026-11-21T07:30:00+00:00"
    assert origin["record_updated_at"] != item["metadata"]["custom"]["updated_at"]
    item["updated_at"] = "invalid-revision"
    assert RuntimeEvidenceResolver._canonical_memory_event_origin(
        item, tenant_id="tenant-1", user_id="user-1",
    ) is None

"""Real database burn from chat text to governed NeuroVault to profile recall.

A downstream non-Postgres projection is deliberately inert. Extraction,
worthiness, authorization, ledger writes, SQL projections and recall are real.
"""
import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.core.memory.formation.service import MemoryFormationService
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.derived_projector import PostgresDerivedMemoryProjector
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope, MemoryAssertion, MemoryEpisode, MemoryEvent, ProfileFact, ProjectionStatus,
)
from ai_karen_engine.platform.memory.postgres.profile_retriever import PostgresProfileRecallRetriever
from ai_karen_engine.platform.memory.postgres.vault import PostgresNeuroVault


pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="Only runs against isolated CI PostgreSQL with the opt-in flag",
    ),
]


class _OutsidePostgresProjection:
    async def project_event(self, event_data, assertion_data):
        # Other (Redis / graph) projections are not exercised in this DB burn.
        # The canonical SQL-backed projector above remains fully active.
        return {}


async def test_explicit_name_chat_reaches_fresh_conversation_recall():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    name = "AureliaMemoryProof"
    session_a, session_b = str(uuid.uuid4()), str(uuid.uuid4())
    conversation_a, conversation_b = str(uuid.uuid4()), str(uuid.uuid4())
    factory = lambda: async_transaction_scope(tenant_id=str(tenant))
    formation = MemoryFormationService(
        vault_factory=lambda _tenant: PostgresNeuroVault(session_factory=factory),
        derived_projector=PostgresDerivedMemoryProjector(
            projection_manager=_OutsidePostgresProjection(),
        ),
    )
    retriever = PostgresProfileRecallRetriever()

    try:
        write_result = await formation.process_interaction(
            text=f"My name is {name}.",
            tenant_id=str(tenant),
            user_id=str(user),
            source_type="chat_user",
            source_ref=conversation_a,
            session_id=session_a,
            conversation_id=conversation_a,
            actor_id=str(user),
            request_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            policy_context={
                "memory_write_authorized": True,
                "allowed_capabilities": ["memory.write"],
                "authorized_tenant_id": str(tenant),
                "authorized_user_id": str(user),
                "authorized_session_id": session_a,
            },
        )
        assert write_result["persisted"] > 0, write_result
        assert write_result.get("projection_failures", 0) == 0, write_result

        query = SimpleNamespace(
            text="What's my name?",
            tenant_id=str(tenant),
            user_id=str(user),
            session_id=session_b,
            conversation_id=conversation_b,
            top_k=5,
        )
        found = await retriever.recall(query)
        assert any(f"preferred_name: {name}" == item.content for item in found), [
            item.content for item in found
        ]
        # Exercise the actual Postgres rows through Runtime's existing
        # authorization-aware evidence sufficiency contract, not an LLM mock.
        from ai_karen_engine.core.context.contracts import (
            ContextEvidence, EvidenceScope, EvidenceSource,
        )
        from ai_karen_engine.core.runtime.evidence_sufficiency import (
            EvidenceSufficiencyStatus, evaluate_personal_evidence,
        )
        from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
        from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

        scoped_evidence = [
            ContextEvidence(
                evidence_id=item.id,
                source=EvidenceSource.MEMORY,
                content=item.content,
                scope=EvidenceScope(tenant_id=str(tenant), user_id=str(user)),
            )
            for item in found
        ]
        authorized_context = SimpleNamespace(
            tenant_id=str(tenant),
            user_id=str(user),
            authorized_sources=["memory"],
            denied_sources=[],
            unresolved_sources=[],
            evidence=scoped_evidence,
        )
        decision = ExecutionDecision(
            intent="memory.recall",
            policy_constraints={"personal_evidence_attribute": "preferred_name"},
        )
        decision.cognitive_context = authorized_context
        answer, provenance = ChatRuntime._grounded_personal_response(
            decision, tenant_id=str(tenant), user_id=str(user),
        )
        assert name in answer
        assert provenance["response_source"] == "authorized_memory_evidence"
        assert provenance["actual_provider"] is None
        assert provenance["evidence_sufficiency"] == "supported"
        assert evaluate_personal_evidence(
            authorized_context,
            tenant_id=str(tenant), user_id=str(uuid.uuid4()),
            attribute="preferred_name",
        ).status is EvidenceSufficiencyStatus.MISSING

        assert await retriever.recall(
            SimpleNamespace(
                text=query.text, tenant_id=str(tenant),
                user_id=str(uuid.uuid4()), top_k=5,
                session_id=session_b, conversation_id=conversation_b,
            )
        ) == []
        # Revoke canonical event consent, and the read path must exclude it.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            events = (await session.execute(
                select(MemoryEvent).where(
                    MemoryEvent.tenant_id == tenant,
                    MemoryEvent.user_id == user,
                )
            )).scalars().all()
            assert events
            for event in events:
                event.consent_state = "revoked"
        assert await retriever.recall(query) == []
    finally:
        # UUIDs above are unique to this test; never truncate or delete shared data.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            event_ids = select(MemoryEvent.event_id).where(
                MemoryEvent.tenant_id == tenant,
                MemoryEvent.user_id == user,
            )
            for model in (ProfileFact, MemoryEpisode, ProjectionStatus, MemoryAssertion):
                await session.execute(delete(model).where(model.event_id.in_(event_ids)))
            await session.execute(delete(MemoryEvent).where(
                MemoryEvent.tenant_id == tenant,
                MemoryEvent.user_id == user,
            ))

@pytest.mark.parametrize(
    ("statement", "value", "attribute", "wordings"),
    [
        (
            "No! I just love black, it is my favorite color.",
            "black", "favorite_color",
            ("What's my favorite color?", "what my fav color?", "Whats my fav color?"),
        ),
        (
            "My favorite music genre is reggae.",
            "reggae", "favorite_music_genre",
            ("What's my favorite music genre?", "what my fav music genre?"),
        ),
    ],
)
async def test_explicit_favorite_chat_reaches_fresh_conversation_response(
    statement, value, attribute, wordings,
):
    """Unseen favorite domains persist and recall via real governed PostgreSQL."""
    tenant, user = uuid.uuid4(), uuid.uuid4()
    session_a, session_b = str(uuid.uuid4()), str(uuid.uuid4())
    conversation_a, conversation_b = str(uuid.uuid4()), str(uuid.uuid4())
    factory = lambda: async_transaction_scope(tenant_id=str(tenant))
    formation = MemoryFormationService(
        vault_factory=lambda _tenant: PostgresNeuroVault(session_factory=factory),
        derived_projector=PostgresDerivedMemoryProjector(
            projection_manager=_OutsidePostgresProjection(),
        ),
    )
    retriever = PostgresProfileRecallRetriever()

    try:
        write_result = await formation.process_interaction(
            text=statement,
            tenant_id=str(tenant),
            user_id=str(user),
            source_type="chat_user",
            source_ref=conversation_a,
            session_id=session_a,
            conversation_id=conversation_a,
            actor_id=str(user),
            request_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            policy_context={
                "memory_write_authorized": True,
                "allowed_capabilities": ["memory.write"],
                "authorized_tenant_id": str(tenant),
                "authorized_user_id": str(user),
                "authorized_session_id": session_a,
            },
        )
        assert write_result["persisted"] > 0, write_result
        assert write_result.get("projection_failures", 0) == 0, write_result

        query = SimpleNamespace(
            text=wordings[0],
            tenant_id=str(tenant),
            user_id=str(user),
            session_id=session_b,
            conversation_id=conversation_b,
            top_k=5,
        )
        for wording in wordings:
            query.text = wording
            found = await retriever.recall(query)
            assert any(
                f"{attribute}: {value}" == item.content for item in found
            ), (wording, [item.content for item in found])

        from ai_karen_engine.core.context.contracts import (
            ContextEvidence,
            EvidenceScope,
            EvidenceSource,
        )
        from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
        from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

        scoped_evidence = [
            ContextEvidence(
                evidence_id=item.id,
                source=EvidenceSource.MEMORY,
                content=item.content,
                scope=EvidenceScope(tenant_id=str(tenant), user_id=str(user)),
            )
            for item in found
        ]
        decision = ExecutionDecision(
            intent="memory.recall",
            policy_constraints={"personal_evidence_attribute": attribute},
        )
        decision.cognitive_context = SimpleNamespace(
            tenant_id=str(tenant),
            user_id=str(user),
            authorized_sources=["memory"],
            denied_sources=[],
            unresolved_sources=[],
            evidence=scoped_evidence,
        )

        answer, provenance = ChatRuntime._grounded_personal_response(
            decision,
            tenant_id=str(tenant),
            user_id=str(user),
        )
        assert answer == f"Your {attribute.replace('_', ' ')} is {value}."
        assert provenance["response_source"] == "authorized_memory_evidence"
        assert provenance["actual_provider"] is None
        assert provenance["evidence_sufficiency"] == "supported"

        assert await retriever.recall(
            SimpleNamespace(
                text=query.text,
                tenant_id=str(tenant),
                user_id=str(uuid.uuid4()),
                top_k=5,
                session_id=session_b,
                conversation_id=conversation_b,
            )
        ) == []

        # Revoking the current consent scope must close recall immediately,
        # even if an older event still has consent_state='granted'.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                tenant_id=tenant, user_id=user,
                scope_name="memory.write", is_granted=False,
            ))
        assert await retriever.recall(query) == []
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ConsentScope).where(
                ConsentScope.tenant_id == tenant,
                ConsentScope.user_id == user,
            ))
            event_ids = select(MemoryEvent.event_id).where(
                MemoryEvent.tenant_id == tenant,
                MemoryEvent.user_id == user,
            )
            for model in (
                ProfileFact,
                MemoryEpisode,
                ProjectionStatus,
                MemoryAssertion,
            ):
                await session.execute(delete(model).where(model.event_id.in_(event_ids)))
            await session.execute(
                delete(MemoryEvent).where(
                    MemoryEvent.tenant_id == tenant,
                    MemoryEvent.user_id == user,
                )
            )


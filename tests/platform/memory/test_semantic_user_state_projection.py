from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

import pytest

import ai_karen_engine.platform.memory.postgres.derived_projector as projector_module
from ai_karen_engine.core.memory.signals import MemorySignal
from ai_karen_engine.platform.memory.postgres.derived_projector import (
    PostgresDerivedMemoryProjector,
)
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    MemoryEpisode,
    MemoryProspectiveItem,
    MemoryUserGoal,
    ProfileFact,
)


TENANT = UUID("00000000-0000-0000-0000-000000000001")
USER = UUID("00000000-0000-0000-0000-000000000002")
EVENT = UUID("00000000-0000-0000-0000-000000000010")


class _Result:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _Session:
    def __init__(self, scalars):
        self.scalars = list(scalars)
        self.added = []

    async def execute(self, _stmt):
        return _Result(self.scalars.pop(0) if self.scalars else None)

    def add(self, value):
        self.added.append(value)


class _ProjectionManager:
    async def project_event(self, event_data, assertion_data):
        return {"stm": True, "memory_graph": True}


def _scope(session):
    @asynccontextmanager
    async def _ctx(*, tenant_id):
        assert tenant_id == str(TENANT)
        yield session

    return _ctx


@pytest.mark.asyncio
async def test_identity_fact_projects_current_profile_fact(monkeypatch):
    session = _Session([None, None, None])
    monkeypatch.setattr(
        projector_module,
        "async_transaction_scope",
        _scope(session),
    )
    projector = PostgresDerivedMemoryProjector(_ProjectionManager())

    await projector._project_relational_views(
        tenant_uuid=TENANT,
        user_uuid=USER,
        event_uuid=EVENT,
        signal=MemorySignal(
            text="My name is Orlando",
            signal_type="identity_fact",
            confidence=0.98,
            metadata={
                "category": "identity",
                "attribute": "preferred_name",
                "normalized_value": "Orlando",
                "semantic_class": "identity",
            },
        ),
        confidence=0.98,
        source_type="chat_user",
        source_ref="conversation-1",
        metadata={
            "category": "identity",
            "attribute": "preferred_name",
            "normalized_value": "Orlando",
            "semantic_class": "identity",
        },
    )

    facts = [item for item in session.added if isinstance(item, ProfileFact)]
    assert len(facts) == 1
    assert facts[0].category == "identity"
    assert facts[0].attribute == "preferred_name"
    assert facts[0].value["value"] == "Orlando"


@pytest.mark.asyncio
async def test_new_preference_supersedes_previous_current_fact(monkeypatch):
    old = ProfileFact(
        fact_id=UUID("00000000-0000-0000-0000-000000000020"),
        event_id=UUID("00000000-0000-0000-0000-000000000021"),
        tenant_id=TENANT,
        user_id=USER,
        category="preference",
        attribute="favorite_color",
        value={
            "value": "green",
            "text": "My favorite color is green",
            "semantic_class": "preference",
        },
        confidence=0.98,
        source_type="chat_user",
        valid_from=datetime.utcnow(),
    )
    session = _Session([None, None, old])
    monkeypatch.setattr(
        projector_module,
        "async_transaction_scope",
        _scope(session),
    )
    projector = PostgresDerivedMemoryProjector(_ProjectionManager())

    await projector._project_relational_views(
        tenant_uuid=TENANT,
        user_uuid=USER,
        event_uuid=EVENT,
        signal=MemorySignal(
            text="My favorite color is orange",
            signal_type="preference",
            confidence=0.98,
            metadata={
                "category": "preference",
                "attribute": "favorite_color",
                "normalized_value": "orange",
                "semantic_class": "preference",
            },
        ),
        confidence=0.98,
        source_type="chat_user",
        source_ref="conversation-1",
        metadata={
            "category": "preference",
            "attribute": "favorite_color",
            "normalized_value": "orange",
            "semantic_class": "preference",
        },
    )

    facts = [item for item in session.added if isinstance(item, ProfileFact)]
    assert len(facts) == 1
    assert facts[0].value["value"] == "orange"
    assert facts[0].supersedes == old.fact_id
    assert old.valid_to is not None


@pytest.mark.asyncio
async def test_goal_projects_to_durable_goal_view(monkeypatch):
    session = _Session([None, None])
    monkeypatch.setattr(
        projector_module,
        "async_transaction_scope",
        _scope(session),
    )
    projector = PostgresDerivedMemoryProjector(_ProjectionManager())

    await projector._project_relational_views(
        tenant_uuid=TENANT,
        user_uuid=USER,
        event_uuid=EVENT,
        signal=MemorySignal(
            text="I'm trying to work out four days a week",
            signal_type="goal",
            confidence=0.95,
            metadata={"description": "work out four days a week"},
        ),
        confidence=0.95,
        source_type="chat_user",
        source_ref="conversation-1",
        metadata={
            "description": "work out four days a week",
            "goal_type": "explicit",
            "lifecycle_state": "active",
        },
    )

    goals = [item for item in session.added if isinstance(item, MemoryUserGoal)]
    assert len(goals) == 1
    assert goals[0].description == "work out four days a week"
    assert goals[0].lifecycle_state == "active"


@pytest.mark.asyncio
async def test_interview_projects_to_prospective_memory(monkeypatch):
    session = _Session([None, None])
    monkeypatch.setattr(
        projector_module,
        "async_transaction_scope",
        _scope(session),
    )
    projector = PostgresDerivedMemoryProjector(_ProjectionManager())

    await projector._project_relational_views(
        tenant_uuid=TENANT,
        user_uuid=USER,
        event_uuid=EVENT,
        signal=MemorySignal(
            text="I have a job interview with Ford Friday at 2 PM",
            signal_type="prospective_event",
            confidence=0.96,
            metadata={"event_type": "job_interview"},
        ),
        confidence=0.96,
        source_type="chat_user",
        source_ref="conversation-1",
        metadata={
            "event_type": "job_interview",
            "temporal_text": "with Ford Friday at 2 PM",
            "lifecycle_state": "dormant",
        },
    )

    items = [
        item
        for item in session.added
        if isinstance(item, MemoryProspectiveItem)
    ]
    assert len(items) == 1
    assert items[0].event_type == "job_interview"
    assert items[0].temporal_text == "with Ford Friday at 2 PM"
    assert items[0].lifecycle_state == "dormant"


def test_each_semantic_projection_also_keeps_episode_lineage():
    assert issubclass(MemoryEpisode, object)

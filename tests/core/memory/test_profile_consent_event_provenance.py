"""Profile projections preserve per-event consent and deletion provenance."""

import uuid
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.memory.signals import MemorySignal
from ai_karen_engine.platform.memory.postgres.derived_projector import (
    PostgresDerivedMemoryProjector,
)


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, old_row):
        self.old_row = old_row
        self.statements = []
        self.added = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(None if len(self.statements) == 1 else self.old_row)

    def add(self, value):
        self.added.append(value)


@pytest.mark.asyncio
async def test_repeat_name_creates_new_event_backed_projection():
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    old_event = uuid.uuid4()
    new_event = uuid.uuid4()
    old_fact_id = uuid.uuid4()
    old_row = SimpleNamespace(
        fact_id=old_fact_id,
        event_id=old_event,
        value={"value": "Alex"},
        confidence=0.98,
        updated_at=None,
        valid_to=None,
    )
    session = _Session(old_row)
    projector = PostgresDerivedMemoryProjector(projection_manager=None)
    signal = MemorySignal(
        text="My name is Alex",
        signal_type="identity_fact",
        confidence=0.98,
        scope="user",
        metadata={"attribute": "preferred_name", "normalized_value": "Alex"},
    )

    await projector._project_profile_fact(
        session=session,
        tenant_uuid=tenant_id,
        user_uuid=user_id,
        event_uuid=new_event,
        signal=signal,
        confidence=0.98,
        source_type="user_chat",
        source_ref=None,
        metadata={"category": "identity", "attribute": "preferred_name", "normalized_value": "Alex"},
    )
    assert len(session.added) == 1
    projected = session.added[0]
    assert projected.event_id == new_event
    assert projected.supersedes == old_fact_id
    assert projected.attribute == "preferred_name"
    assert projected.value["value"] == "Alex"
    assert old_row.valid_to is not None


@pytest.mark.asyncio
async def test_replayed_event_remains_idempotent():
    event_id = uuid.uuid4()
    session = _Session(None)
    session.execute_count = 0

    async def execute_existing(_statement):
        return _Result(uuid.uuid4())

    session.execute = execute_existing
    projector = PostgresDerivedMemoryProjector(projection_manager=None)
    await projector._project_profile_fact(
        session=session,
        tenant_uuid=uuid.uuid4(),
        user_uuid=uuid.uuid4(),
        event_uuid=event_id,
        signal=MemorySignal(text="My name is Alex", signal_type="identity_fact", confidence=0.98, scope="user"),
        confidence=0.98,
        source_type="user_chat",
        source_ref=None,
        metadata={"attribute": "preferred_name", "normalized_value": "Alex"},
    )
    assert session.added == []

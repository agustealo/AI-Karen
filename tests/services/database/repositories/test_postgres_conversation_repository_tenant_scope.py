from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from ai_karen_engine.services.database.repositories.conversation_repository import Message
from ai_karen_engine.services.database.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
)


class _Result:
    def __init__(self, *, rowcount: int = 0, rows: list[Any] | None = None) -> None:
        self.rowcount = rowcount
        self._rows = list(rows or [])

    def fetchall(self) -> list[Any]:
        return list(self._rows)

    def fetchone(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, results: list[_Result]) -> None:
        self._results = list(results)
        self.executions: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        self.executions.append((str(statement), dict(params or {})))
        if not self._results:
            raise AssertionError("unexpected execute")
        return self._results.pop(0)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _repository(session: _Session) -> PostgresConversationRepository:
    return PostgresConversationRepository(session_factory=lambda: session)


def _message(*, tenant_id: str = "tenant-a") -> Message:
    return Message(
        id="11111111-1111-1111-1111-111111111111",
        conversation_id="22222222-2222-2222-2222-222222222222",
        tenant_id=tenant_id,
        role="assistant",
        content="durable response",
        created_at=datetime(2026, 9, 27, 12, 0, 0),
        metadata={"request_id": "request-1"},
    )


@pytest.mark.asyncio
async def test_add_message_is_atomically_scoped_to_parent_tenant() -> None:
    session = _Session([_Result(rowcount=1)])
    result = await _repository(session).add_message(_message())

    assert result.success is True
    assert result.data == "11111111-1111-1111-1111-111111111111"
    assert result.metadata["idempotent_replay"] is False
    assert session.commits == 1
    assert session.rollbacks == 0

    sql, params = session.executions[0]
    normalized_sql = " ".join(sql.split())
    assert "INSERT INTO messages" in normalized_sql
    assert "FROM conversations c" in normalized_sql
    assert "c.conversation_id = :conversation_id" in normalized_sql
    assert "c.tenant_id = :tenant_id" in normalized_sql
    assert "ON CONFLICT (message_id) DO NOTHING" in normalized_sql
    assert "updated_at" not in normalized_sql
    assert params["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_add_message_accepts_exact_retry_as_idempotent_replay() -> None:
    existing = SimpleNamespace(role="assistant", content="durable response")
    session = _Session(
        [
            _Result(rowcount=0),
            _Result(rows=[existing]),
        ]
    )

    result = await _repository(session).add_message(_message())

    assert result.success is True
    assert result.data == "11111111-1111-1111-1111-111111111111"
    assert result.metadata["idempotent_replay"] is True
    assert session.commits == 1
    assert session.rollbacks == 0

    replay_sql, replay_params = session.executions[1]
    normalized_sql = " ".join(replay_sql.split())
    assert "JOIN conversations c" in normalized_sql
    assert "m.message_id = :id" in normalized_sql
    assert "m.conversation_id = :conversation_id" in normalized_sql
    assert "c.tenant_id = :tenant_id" in normalized_sql
    assert replay_params["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_add_message_rejects_idempotency_conflict() -> None:
    conflicting = SimpleNamespace(role="assistant", content="different response")
    session = _Session(
        [
            _Result(rowcount=0),
            _Result(rows=[conflicting]),
        ]
    )

    result = await _repository(session).add_message(_message())

    assert result.success is False
    assert result.error == "message_idempotency_conflict"
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_add_message_rejects_cross_tenant_or_missing_conversation() -> None:
    session = _Session(
        [
            _Result(rowcount=0),
            _Result(rows=[]),
        ]
    )
    result = await _repository(session).add_message(_message(tenant_id="tenant-b"))

    assert result.success is False
    assert result.error == "conversation_not_found_or_tenant_mismatch"
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_get_messages_uses_parent_conversation_tenant_scope_and_real_schema() -> None:
    created_at = datetime(2026, 9, 27, 12, 0, 0)
    row = SimpleNamespace(
        message_id="11111111-1111-1111-1111-111111111111",
        conversation_id="22222222-2222-2222-2222-222222222222",
        tenant_id="tenant-a",
        role="user",
        content="hello",
        message_metadata={"request_id": "request-1"},
        created_at=created_at,
    )
    session = _Session([_Result(rows=[row])])

    result = await _repository(session).get_messages(
        conversation_id=row.conversation_id,
        tenant_id="tenant-a",
        limit=20,
    )

    assert result.success is True
    assert result.data is not None
    assert len(result.data) == 1
    message = result.data[0]
    assert message.tenant_id == "tenant-a"
    assert message.created_at == created_at
    assert message.updated_at == created_at

    sql, params = session.executions[0]
    normalized_sql = " ".join(sql.split())
    assert "JOIN conversations c" in normalized_sql
    assert "c.tenant_id = :tenant_id" in normalized_sql
    assert "m.updated_at" not in normalized_sql
    assert params["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_update_message_is_tenant_scoped_and_does_not_write_missing_column() -> None:
    session = _Session([_Result(rowcount=1)])
    result = await _repository(session).update_message(_message())

    assert result.success is True
    assert result.data is True
    assert session.commits == 1

    sql, params = session.executions[0]
    normalized_sql = " ".join(sql.split())
    assert "UPDATE messages m" in normalized_sql
    assert "FROM conversations c" in normalized_sql
    assert "m.conversation_id = c.conversation_id" in normalized_sql
    assert "c.tenant_id = :tenant_id" in normalized_sql
    assert "updated_at" not in normalized_sql
    assert params["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_composed_surface_and_receipt_survive_canonical_repository_roundtrip() -> None:
    """Contract test for stored metadata; live PostgreSQL remains a separate gate."""
    import json
    from ai_karen_engine.core.runtime.presentation_contract import validate_presentation

    clock = {
        "schema_version": 1, "presentation_id": "time-1",
        "component_type": "time.observation", "evidence_ref": "req-1:clock",
        "data": {"formatted": "10:15 AM", "timezone": "America/Detroit"},
    }
    surface = validate_presentation({
        "schema_version": 1, "presentation_id": "surface-1",
        "component_type": "surface.composition", "evidence_ref": "req-1:clock",
        "data": {"layout": "stack", "items": [clock]},
    })
    assert surface is not None
    metadata = {
        "actual_provider": "local-provider",
        "actual_model": "authorized-model",
        "response_source": "grounded_observation_model",
        "presentation_layout_provenance": {"provider": "layout-local", "model": "layout-model", "response_source": "surface_layout_model", "part_ids": ["time-1"]},
        "structured_content": {"presentation": surface},
    }
    message = _message()
    message.metadata = metadata
    created = datetime(2026, 9, 27, 12, 0, 0)
    row = SimpleNamespace(
        message_id=message.id, conversation_id=message.conversation_id,
        tenant_id=message.tenant_id, role=message.role,
        content=message.content, message_metadata=json.dumps(metadata),
        created_at=created,
    )
    session = _Session([_Result(rowcount=1), _Result(rows=[row])])
    repository = _repository(session)
    saved = await repository.add_message(message)
    assert saved.success is True
    write_params = session.executions[0][1]
    assert json.loads(write_params["metadata"]) == metadata
    retrieved = await repository.get_messages(message.conversation_id, message.tenant_id)
    assert retrieved.success is True
    restored = retrieved.data[0].metadata
    assert restored["actual_provider"] == "local-provider"
    assert restored["actual_model"] == "authorized-model"
    assert restored["presentation_layout_provenance"] == metadata["presentation_layout_provenance"]
    assert restored["structured_content"]["presentation"] == surface
    assert validate_presentation(restored["structured_content"]["presentation"]) == surface
    assert session.executions[1][1]["tenant_id"] == message.tenant_id

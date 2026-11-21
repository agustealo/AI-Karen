"""Selected durable memory must be current immediately before model execution."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.context.contracts import (
    CognitiveContext, ContextEvidence, ContextRequirements,
    EvidenceScope, EvidenceSource,
)
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext, ChatExecutionRequest,
)
from ai_karen_engine.platform.memory.postgres.event_source import PostgresEventSource


def _request():
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "Recall my preferences"}],
        context=ChatExecutionContext(
            tenant_id="tenant-1", user_id="user-1", session_id="session-1",
        ),
        metadata={"memory_context": {"recall": [
            {"id": "forged", "content": "forged"}]}},
    )


def _decision(*, source="postgres_memory_ledger", revision=True, top_k=1):
    record = "00000000-0000-4000-8000-000000000010"
    origin = {
        "event_id": "00000000-0000-4000-8000-000000000020",
        "record_id": record,
        "record_type": "memory_assertion",
        "source": "postgres_memory_ledger",
    }
    if revision:
        origin["record_updated_at"] = "2026-11-21T09:00:00+00:00"
    evidence = ContextEvidence(
        evidence_id=record, source=EvidenceSource.MEMORY,
        content="The remembered preference",
        scope=EvidenceScope(tenant_id="tenant-1", user_id="user-1"),
        metadata={
            "memory_metadata": {"source": source},
            "canonical_event_origin": origin if source.startswith("postgres") else None,
        },
    )
    ctx = CognitiveContext(
        context_id="ctx", request_id="req", correlation_id="corr",
        tenant_id="tenant-1", user_id="user-1",
        requirements=ContextRequirements(
            request_id="req", correlation_id="corr",
            tenant_id="tenant-1", user_id="user-1",
        ),
        authorized_sources=["memory"],
        evidence=[evidence],
    )
    return SimpleNamespace(
        memory_top_k=top_k, memory_recall_required=True,
        cognitive_context=ctx,
    )


@pytest.mark.asyncio
async def test_selected_postgres_memory_must_pass_live_authorizer(monkeypatch):
    seen = []

    async def authorize(self, *, tenant_id, user_id, origins):
        seen.append((tenant_id, user_id, origins))
        return True

    monkeypatch.setattr(PostgresEventSource, "authorize_selected_records", authorize)
    await ChatRuntime._authorize_selected_memory_before_generation(
        _request(), _decision(),
    )
    assert len(seen) == 1
    assert seen[0][0:2] == ("tenant-1", "user-1")
    assert seen[0][2][0]["record_type"] == "memory_assertion"
    assert seen[0][2][0]["record_updated_at"] == "2026-11-21T09:00:00+00:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [False, None])
async def test_revocation_or_missing_record_blocks_model_dispatch(monkeypatch, result):
    async def authorize(self, **kwargs):
        return result

    monkeypatch.setattr(PostgresEventSource, "authorize_selected_records", authorize)
    with pytest.raises(RuntimeError, match="memory_source_revoked_or_unverifiable"):
        await ChatRuntime._authorize_selected_memory_before_generation(
            _request(), _decision(),
        )


@pytest.mark.asyncio
async def test_storage_outage_fails_closed_and_does_not_leak_source_data(monkeypatch):
    async def authorize(self, **kwargs):
        raise ConnectionError("sensitive database address and password")

    monkeypatch.setattr(PostgresEventSource, "authorize_selected_records", authorize)
    with pytest.raises(RuntimeError, match="memory_source_revoked_or_unverifiable") as exc:
        await ChatRuntime._authorize_selected_memory_before_generation(
            _request(), _decision(),
        )
    assert "sensitive" not in str(exc.value)


@pytest.mark.asyncio
async def test_missing_revision_denied_before_database_read(monkeypatch):
    async def forbid(self, **kwargs):
        raise AssertionError("unverified selection must not reach storage")

    monkeypatch.setattr(PostgresEventSource, "authorize_selected_records", forbid)
    with pytest.raises(RuntimeError, match="memory_source_revoked_or_unverifiable"):
        await ChatRuntime._authorize_selected_memory_before_generation(
            _request(), _decision(revision=False),
        )


@pytest.mark.asyncio
async def test_ephemeral_memory_does_not_invent_postgres_event_proof(monkeypatch):
    async def forbid(self, **kwargs):
        raise AssertionError("ephemeral memory must not be mapped to PostgreSQL")

    monkeypatch.setattr(PostgresEventSource, "authorize_selected_records", forbid)
    await ChatRuntime._authorize_selected_memory_before_generation(
        _request(), _decision(source="stm"),
    )
    await ChatRuntime._authorize_selected_memory_before_generation(
        _request(), _decision(top_k=0),
    )


def test_direct_and_reasoning_model_dispatch_use_live_guard():
    """Ensure no topology silently bypasses the reauthorization stage."""
    from pathlib import Path
    source = (
        Path(__file__).resolve().parents[3]
        / "src/ai_karen_engine/core/runtime/chat_runtime.py"
    ).read_text(encoding="utf-8")
    direct = source.split("    async def _run_simple(", 1)[1].split(
        "    async def _run_simple_stream(", 1
    )[0]
    reasoning = source.split("    async def _run_reasoning(", 1)[1].split(
        "    async def ", 1
    )[0]
    assert "_authorize_selected_memory_before_generation(" in direct
    assert "_authorize_selected_memory_before_generation(" in reasoning
    assert direct.index("_authorize_selected_memory_before_generation(") < direct.index(
        "task = ExpressionTask("
    )

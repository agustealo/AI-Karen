import pytest

from ai_karen_engine.core.memory.formation.service import MemoryFormationService
from ai_karen_engine.core.memory.protocols import VaultWriteReceipt
from ai_karen_engine.core.memory.signals import ExtractionResult, MemorySignal
from ai_karen_engine.core.memory.types import MemoryType


class _Pipeline:
    def __init__(self, signal):
        self.signal = signal

    async def process_text(self, **kwargs):
        return ExtractionResult(signals=[self.signal], status="success")


class _Scorer:
    async def evaluate(self, text, signal_type):
        return {"is_worthy": True, "score": 0.9, "threshold": 0.6}


class _RejectingVault:
    async def persist(self, entry, *, context):
        raise PermissionError("durable memory operation requires explicit capability: memory.write")


class _Vault:
    def __init__(self):
        self.calls = []

    async def persist(self, entry, *, context):
        self.calls.append((entry, context))
        return VaultWriteReceipt(
            memory_id=entry.id,
            persisted=True,
            version=entry.version,
            metadata={"event_id": "00000000-0000-0000-0000-000000000010"},
        )


class _Projector:
    def __init__(self):
        self.calls = []

    async def project(self, **kwargs):
        self.calls.append(kwargs)
        return {"redis": True, "memory_graph": True}


def _service(vault, projector, signal):
    service = object.__new__(MemoryFormationService)
    service.signal_pipeline = _Pipeline(signal)
    service.worthiness_scorer = _Scorer()
    service._vault_factory = lambda tenant_id: vault
    service._derived_projector = projector
    return service


@pytest.mark.asyncio
async def test_formation_fails_closed_without_memory_write_authority():
    signal = MemorySignal(
        text="Remember that I prefer concise reports",
        signal_type="preference",
        confidence=0.9,
    )
    projector = _Projector()
    service = _service(_RejectingVault(), projector, signal)

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        policy_context={},
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "memory_write_not_authorized"
    assert result["persisted"] == 0
    assert projector.calls == []


@pytest.mark.asyncio
async def test_neurovault_commit_happens_before_derived_projection():
    signal = MemorySignal(
        text="Use the deployment preflight workflow next time",
        signal_type="workflow",
        confidence=0.9,
        keywords=["deployment", "preflight"],
    )
    vault = _Vault()
    projector = _Projector()
    service = _service(vault, projector, signal)

    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        request_id="req-1",
        correlation_id="corr-1",
        session_id="session-1",
        policy_context={"allowed_capabilities": ["memory.write"]},
    )

    assert result["status"] == "success"
    assert result["persisted"] == 1
    assert len(vault.calls) == 1
    entry, context = vault.calls[0]
    assert entry.memory_type is MemoryType.PROCEDURAL
    assert context.request_id == "req-1"
    assert context.correlation_id == "corr-1"
    assert context.policy_context["allowed_capabilities"] == ["memory.write"]
    assert len(projector.calls) == 1
    assert projector.calls[0]["event_id"] == "00000000-0000-0000-0000-000000000010"
    assert projector.calls[0]["memory_id"] == entry.id


@pytest.mark.asyncio
async def test_projection_failure_degrades_but_does_not_deny_committed_truth():
    signal = MemorySignal(
        text="Remember this durable fact",
        signal_type="fact",
        confidence=0.9,
    )
    vault = _Vault()

    class _DegradedProjector(_Projector):
        async def project(self, **kwargs):
            self.calls.append(kwargs)
            return {"redis": True, "memory_graph": False}

    service = _service(vault, _DegradedProjector(), signal)
    result = await service.process_interaction(
        text=signal.text,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        policy_context={"memory_write_authorized": True},
    )

    assert result["persisted"] == 1
    assert result["status"] == "degraded"
    assert result["projection_failures"] == 1

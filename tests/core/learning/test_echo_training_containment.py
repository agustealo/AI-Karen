"""Memory retention must never imply neural training authorization."""

from __future__ import annotations

import pytest

from ai_karen_engine.echocore.contracts import (
    DefaultEchoCoreManager,
    EchoIngestAction,
    EchoPolicyDecision,
    EchoPolicyEngine,
    EchoArtifactType,
    MemoryTier,
    RuntimeMemoryArtifact,
)


def high_importance_memory() -> RuntimeMemoryArtifact:
    return RuntimeMemoryArtifact(
        artifact_id="memory-1",
        artifact_type=EchoArtifactType.LONG_TERM_FACT,
        source_tier=MemoryTier.LTM,
        user_id="user-a",
        tenant_id="tenant-a",
        session_id=None,
        thread_id=None,
        content={"text": "Important but unverified memory"},
        importance_score=1.0,
        retention_score=1.0,
    )


def test_high_importance_memory_does_not_authorize_training() -> None:
    policy = EchoPolicyEngine().evaluate(high_importance_memory())
    assert policy.should_archive
    assert policy.should_queue_training is False


class UnsafeLegacyPolicy:
    def evaluate(self, artifact: RuntimeMemoryArtifact) -> EchoPolicyDecision:
        return EchoPolicyDecision(
            action=EchoIngestAction.QUEUE_TRAINING,
            should_queue_training=True,
            should_archive=False,
            should_collect_metadata=False,
        )


class MustNotQueue:
    def queue_candidate(self, candidate: object) -> None:
        raise AssertionError("Training queue must not be called")


class UnusedVault:
    async def store_archive(self, record: object) -> str:
        raise AssertionError("No archive requested")

    async def store_backup_copy(self, record: object) -> str:
        raise AssertionError("No backup requested")


class UnusedMetadata:
    def collect(self, artifact: object) -> object:
        raise AssertionError("No metadata requested")


class UnusedTracker:
    async def store_shadow(self, record: object) -> None:
        raise AssertionError("No shadow requested")


class NoopTelemetry:
    def emit_ingest(self, result: object) -> None:
        return None


@pytest.mark.asyncio
async def test_legacy_policy_cannot_enqueue_unverified_memory() -> None:
    manager = DefaultEchoCoreManager(
        policy_engine=UnsafeLegacyPolicy(),
        echo_vault=UnusedVault(),
        metadata_collector=UnusedMetadata(),
        fine_tuner=MustNotQueue(),
        dark_tracker=UnusedTracker(),
        telemetry_manager=NoopTelemetry(),
    )
    result = await manager.ingest(high_importance_memory())
    assert result.training_queued is False
    assert result.diagnostics["training_request_blocked"] == "independent_admission_required"

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Mapping, Optional

import pytest

from ai_karen_engine.config.model_download import ModelDownloadWorkerSettings
from ai_karen_engine.core.model_runtime.model_download_control_service import (
    ModelDownloadControlService,
)
from ai_karen_engine.core.model_runtime.model_download_publication_recovery import (
    ModelDownloadPublicationRecoveryRequired,
)


class _RecoveryPublication:
    def __init__(self) -> None:
        self.abort_calls = 0
        self.complete_calls = 0

    async def abort_for_retry(
        self,
        *,
        error: str,
        retry_base_seconds: int,
    ) -> dict[str, Any]:
        del error, retry_base_seconds
        self.abort_calls += 1
        return {"status": "queued"}

    async def complete(self, result_payload: Mapping[str, Any]) -> dict[str, Any]:
        del result_payload
        self.complete_calls += 1
        return {"status": "completed"}


class _RecoveryRepository:
    def __init__(self) -> None:
        self.guard_calls = 0
        self.publication = _RecoveryPublication()

    @asynccontextmanager
    async def publication_guard(
        self,
        *,
        job_id: str,
        lease_token: str,
        install_path: str,
    ) -> AsyncIterator[Optional[_RecoveryPublication]]:
        del job_id, lease_token, install_path
        self.guard_calls += 1
        yield self.publication


def _settings() -> ModelDownloadWorkerSettings:
    return ModelDownloadWorkerSettings(
        lease_seconds=30,
        heartbeat_seconds=5,
        poll_interval_seconds=0.01,
        max_attempts=3,
        retry_base_seconds=0,
        shutdown_grace_seconds=0,
    ).validate()


def _service(tmp_path: Path, repository: _RecoveryRepository) -> ModelDownloadControlService:
    return ModelDownloadControlService(
        {
            "models_root": str(tmp_path / "models"),
            "runtime_registry_root": str(tmp_path / "runtime-registry"),
            "registry_path": str(tmp_path / "models" / "llm_registry.json"),
            "max_concurrent_downloads": 1,
        },
        repository=repository,  # type: ignore[arg-type]
        worker_settings=_settings(),
    )


def _claim(tmp_path: Path) -> dict[str, str]:
    return {
        "job_id": "mdl-recovery-fail-closed",
        "lease_token": "00000000-0000-0000-0000-000000000011",
        "interrupted_lease_token": "00000000-0000-0000-0000-000000000010",
        "model_id": "test-owner/test-model",
        "install_path": str(
            tmp_path / "models" / "transformers" / "test-owner--test-model" / "main"
        ),
    }


@pytest.mark.asyncio
async def test_missing_recovery_receipt_never_requeues_unknown_publication(tmp_path: Path) -> None:
    repository = _RecoveryRepository()
    service = _service(tmp_path, repository)

    with pytest.raises(ModelDownloadPublicationRecoveryRequired, match="receipt unavailable"):
        await service.recover_interrupted_publication(_claim(tmp_path))

    assert repository.guard_calls == 0
    assert repository.publication.abort_calls == 0
    assert repository.publication.complete_calls == 0


@pytest.mark.asyncio
async def test_mismatched_recovery_receipt_never_requeues_unknown_publication(tmp_path: Path) -> None:
    repository = _RecoveryRepository()
    service = _service(tmp_path, repository)
    claim = _claim(tmp_path)
    source_lease = claim["interrupted_lease_token"]
    stage_root = service._stage_root(claim["job_id"], source_lease)
    staged_path = stage_root / "models" / "transformers" / "test-owner--test-model" / "main"
    staged_path.mkdir(parents=True)
    (staged_path / "weights.bin").write_bytes(b"new-model")

    service._publication_recovery.create_journal(
        stage_root=stage_root,
        staged_path=staged_path,
        final_path=Path(claim["install_path"]),
        job_id="mdl-other-job",
        source_lease_token=source_lease,
        model_id=claim["model_id"],
        result_payload={"status": "success", "install_path": claim["install_path"]},
        prior_registry_entry=None,
        base_registry_entry={
            "model_id": claim["model_id"],
            "install_path": str(staged_path),
        },
    )

    with pytest.raises(ModelDownloadPublicationRecoveryRequired, match="does not match"):
        await service.recover_interrupted_publication(claim)

    assert repository.guard_calls == 0
    assert repository.publication.abort_calls == 0
    assert repository.publication.complete_calls == 0


@pytest.mark.asyncio
async def test_failed_recovery_compensation_keeps_promoting_instead_of_requeueing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _RecoveryRepository()
    service = _service(tmp_path, repository)
    claim = _claim(tmp_path)
    source_lease = claim["interrupted_lease_token"]
    stage_root = service._stage_root(claim["job_id"], source_lease)
    staged_path = stage_root / "models" / "transformers" / "test-owner--test-model" / "main"
    staged_path.mkdir(parents=True)
    (staged_path / "weights.bin").write_bytes(b"new-model")

    service._publication_recovery.create_journal(
        stage_root=stage_root,
        staged_path=staged_path,
        final_path=Path(claim["install_path"]),
        job_id=claim["job_id"],
        source_lease_token=source_lease,
        model_id=claim["model_id"],
        result_payload={"status": "success", "install_path": claim["install_path"]},
        prior_registry_entry=None,
        base_registry_entry={
            "model_id": claim["model_id"],
            "install_path": str(staged_path),
        },
    )

    async def unsafe_compensation(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(service, "_compensate_publication", unsafe_compensation)

    with pytest.raises(ModelDownloadPublicationRecoveryRequired, match="compensation is unsafe"):
        await service.recover_interrupted_publication(claim)

    assert repository.guard_calls == 1
    assert repository.publication.abort_calls == 0
    assert repository.publication.complete_calls == 0

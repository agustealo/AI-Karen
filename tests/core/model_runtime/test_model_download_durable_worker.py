from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pytest

from ai_karen_engine.config.model_download import ModelDownloadWorkerSettings
from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    DownloadResult,
    ModelOrchestratorError,
    ModelOrchestratorService,
)
from ai_karen_engine.core.model_runtime.model_download_control_service import (
    ModelDownloadControlService,
)


class FakeModelDownloadRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.valid_leases: set[tuple[str, str]] = set()
        self.import_calls = 0
        self.complete_calls = 0
        self.promotion_reservations = 0
        self.global_concurrency_limit: Optional[int] = None

    @staticmethod
    def _stamp(payload: Mapping[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        result = dict(payload)
        result.setdefault("created_at", now)
        result["updated_at"] = now
        return result

    async def initialize_global_concurrency_limit(self, default_limit: int) -> int:
        if self.global_concurrency_limit is None:
            self.global_concurrency_limit = default_limit
        return self.global_concurrency_limit

    async def get_global_concurrency_limit(self) -> int:
        if self.global_concurrency_limit is None:
            raise RuntimeError("not initialized")
        return self.global_concurrency_limit

    async def set_global_concurrency_limit(self, value: int) -> int:
        self.global_concurrency_limit = value
        return value

    async def create_job(self, payload: Mapping[str, Any], *, max_attempts: int) -> dict[str, Any]:
        job = self._stamp(payload)
        job["max_attempts"] = max_attempts
        self.jobs[str(job["job_id"])] = job
        return dict(job)

    async def list_jobs(self, *, status: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        rows = list(self.jobs.values())
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return [dict(row) for row in rows[:limit]]

    async def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        row = self.jobs.get(job_id)
        return dict(row) if row else None

    async def cancel_job(self, job_id: str) -> Optional[dict[str, Any]]:
        row = self.jobs.get(job_id)
        if row is None or row.get("status") in {"promoting", "completed", "failed", "cancelled"}:
            return None
        row.update(status="cancelled", cancel_requested=True, message="Cancelled by user")
        return self._stamp(row)

    async def pause_job(self, job_id: str) -> Optional[dict[str, Any]]:
        row = self.jobs.get(job_id)
        if row is None or row.get("status") in {
            "promoting",
            "completed",
            "failed",
            "cancelled",
            "paused",
            "pause_requested",
        }:
            return None
        row.update(
            status="pause_requested" if row.get("status") == "running" else "paused",
            pause_requested=True,
        )
        return self._stamp(row)

    async def resume_job(self, job_id: str) -> Optional[dict[str, Any]]:
        row = self.jobs.get(job_id)
        if row is None or row.get("status") not in {"paused", "pause_requested"}:
            return None
        row.update(status="queued", pause_requested=False)
        return self._stamp(row)

    async def claim_next(self, **_: Any) -> Optional[dict[str, Any]]:
        return None

    async def heartbeat(self, **_: Any) -> bool:
        return True

    async def lease_is_valid(self, *, job_id: str, lease_token: str) -> bool:
        if (job_id, lease_token) not in self.valid_leases:
            return False
        row = self.jobs.get(job_id)
        if row is None or row.get("status") != "running":
            return False
        row.update(status="promoting", message="Promoting staged artifacts")
        self.promotion_reservations += 1
        return True

    async def complete_job(
        self,
        *,
        job_id: str,
        lease_token: str,
        result_payload: Mapping[str, Any],
        install_path: str,
    ) -> Optional[dict[str, Any]]:
        self.complete_calls += 1
        row = self.jobs.get(job_id)
        if (
            (job_id, lease_token) not in self.valid_leases
            or row is None
            or row.get("status") != "promoting"
        ):
            return None
        row.update(
            status="completed",
            progress=1.0,
            result=dict(result_payload),
            install_path=install_path,
        )
        return self._stamp(row)

    async def fail_or_retry(self, **_: Any) -> Optional[dict[str, Any]]:
        return None

    async def release_for_shutdown(self, **_: Any) -> bool:
        return True

    async def cleanup_finished_jobs(self, *, max_age_seconds: int) -> int:
        del max_age_seconds
        return 0

    async def import_legacy_jobs(
        self,
        jobs: Sequence[Mapping[str, Any]],
        *,
        max_attempts: int,
    ) -> int:
        self.import_calls += 1
        inserted = 0
        for source in jobs:
            job_id = str(source["job_id"])
            if job_id in self.jobs:
                continue
            row = dict(source)
            if row.get("status") == "running":
                row["status"] = "queued"
            elif row.get("status") == "pause_requested":
                row["status"] = "paused"
            row["max_attempts"] = max_attempts
            self.jobs[job_id] = self._stamp(row)
            inserted += 1
        return inserted


def _settings() -> ModelDownloadWorkerSettings:
    return ModelDownloadWorkerSettings(
        lease_seconds=30,
        heartbeat_seconds=5,
        poll_interval_seconds=0.01,
        max_attempts=3,
        retry_base_seconds=0,
        shutdown_grace_seconds=0,
    ).validate()


def _service(tmp_path: Path, repository: FakeModelDownloadRepository) -> ModelDownloadControlService:
    return ModelDownloadControlService(
        {
            "models_root": str(tmp_path / "models"),
            "runtime_registry_root": str(tmp_path / "runtime-registry"),
            "registry_path": str(tmp_path / "models" / "llm_registry.json"),
            "max_concurrent_downloads": 1,
        },
        repository=repository,
        worker_settings=_settings(),
    )


@pytest.mark.asyncio
async def test_jobs_are_repository_backed_without_process_local_lifecycle_authority(tmp_path: Path) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)

    job = await service.start_download(
        {
            "model_id": "test-owner/test-model",
            "channel_id": "core_runtime_transformers",
        },
        {"user_id": "test-user"},
    )

    assert "_jobs" not in service.__dict__
    assert "_tasks" not in service.__dict__
    assert repository.jobs[job["job_id"]]["status"] == "queued"
    listed = await service.list_jobs()
    fetched = await service.get_job(job["job_id"])
    assert [item["job_id"] for item in listed] == [job["job_id"]]
    assert fetched is not None and fetched["job_id"] == job["job_id"]


@pytest.mark.asyncio
async def test_global_concurrency_policy_is_repository_backed(tmp_path: Path) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)

    await service.initialize()
    assert await service.get_global_concurrency_limit() == 1

    updated = await service.update_policy({"max_concurrent_downloads": 2})

    assert updated["max_concurrent_downloads"] == 2
    assert repository.global_concurrency_limit == 2
    assert await service.get_policy() == updated


@pytest.mark.asyncio
async def test_legacy_json_cutover_is_imported_then_archived(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime-registry"
    runtime_root.mkdir(parents=True)
    legacy_path = runtime_root / "model_download_control.json"
    legacy_path.write_text(
        json.dumps(
            {
                "policy": {"max_concurrent_downloads": 1},
                "jobs": [
                    {
                        "job_id": "mdl-legacy",
                        "model_id": "test-owner/legacy-model",
                        "channel_id": "core_runtime_transformers",
                        "status": "running",
                        "progress": 0.5,
                        "message": "Downloading",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)

    await service.initialize()
    await service.initialize()

    assert repository.import_calls == 1
    assert repository.jobs["mdl-legacy"]["status"] == "queued"
    assert legacy_path.exists() is False
    assert service.legacy_archive_path.exists() is True
    assert service.policy_path.exists() is True


async def _fake_staged_download(
    orchestrator: ModelOrchestratorService,
    request: Any,
) -> DownloadResult:
    owner, repo = request.model_id.split("/", 1)
    path = (
        orchestrator.models_root
        / (request.storage_key or "transformers")
        / f"{owner}--{repo}"
        / (request.revision or "main")
    )
    path.mkdir(parents=True, exist_ok=True)
    (path / "weights.bin").write_bytes(b"durable-model")
    return DownloadResult(
        model_id=request.model_id,
        install_path=str(path),
        total_size=13,
        files_downloaded=1,
        duration_seconds=0.01,
        status="success",
        error_message=None,
    )


@pytest.mark.asyncio
async def test_stale_lease_cannot_promote_staged_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    monkeypatch.setattr(ModelOrchestratorService, "download_model", _fake_staged_download)
    final_path = tmp_path / "models" / "transformers" / "test-owner--test-model" / "main"

    await service.execute_claimed_job(
        {
            "job_id": "mdl-stale",
            "lease_token": "00000000-0000-0000-0000-000000000001",
            "model_id": "test-owner/test-model",
            "revision": None,
            "channel_id": "core_runtime_transformers",
            "storage_key": "transformers",
            "install_path": str(final_path),
        }
    )

    assert final_path.exists() is False
    assert repository.promotion_reservations == 0
    assert repository.complete_calls == 0


@pytest.mark.asyncio
async def test_promotion_reservation_fences_cancel_and_pause(tmp_path: Path) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    job_id = "mdl-promoting"
    token = "00000000-0000-0000-0000-000000000009"
    repository.jobs[job_id] = {
        "job_id": job_id,
        "model_id": "test-owner/test-model",
        "channel_id": "core_runtime_transformers",
        "status": "running",
    }
    repository.valid_leases.add((job_id, token))

    assert await repository.lease_is_valid(job_id=job_id, lease_token=token) is True
    assert repository.jobs[job_id]["status"] == "promoting"

    with pytest.raises(ModelOrchestratorError, match="cannot be cancelled"):
        await service.cancel_job(job_id)
    with pytest.raises(ModelOrchestratorError, match="cannot be paused"):
        await service.pause_job(job_id)

    assert repository.jobs[job_id]["status"] == "promoting"
    assert repository.jobs[job_id].get("cancel_requested") is not True
    assert repository.jobs[job_id].get("pause_requested") is not True


@pytest.mark.asyncio
async def test_registry_failure_cannot_publish_false_completed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    monkeypatch.setattr(ModelOrchestratorService, "download_model", _fake_staged_download)
    job_id = "mdl-registry-fail"
    token = "00000000-0000-0000-0000-000000000007"
    repository.valid_leases.add((job_id, token))
    repository.jobs[job_id] = {
        "job_id": job_id,
        "model_id": "test-owner/test-model",
        "status": "running",
    }
    final_path = tmp_path / "models" / "transformers" / "test-owner--test-model" / "main"

    async def fail_registry(**_: Any) -> None:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(service, "_register_promoted_model", fail_registry)

    with pytest.raises(RuntimeError, match="registry unavailable"):
        await service.execute_claimed_job(
            {
                "job_id": job_id,
                "lease_token": token,
                "model_id": "test-owner/test-model",
                "revision": None,
                "channel_id": "core_runtime_transformers",
                "storage_key": "transformers",
                "install_path": str(final_path),
            }
        )

    assert final_path.exists() is True
    assert repository.promotion_reservations == 1
    assert repository.complete_calls == 0
    assert repository.jobs[job_id]["status"] == "promoting"


@pytest.mark.asyncio
async def test_valid_lease_promotes_only_complete_staged_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    monkeypatch.setattr(ModelOrchestratorService, "download_model", _fake_staged_download)

    async def no_op_register(**_: Any) -> None:
        return None

    monkeypatch.setattr(service, "_register_promoted_model", no_op_register)
    job_id = "mdl-valid"
    token = "00000000-0000-0000-0000-000000000002"
    repository.valid_leases.add((job_id, token))
    repository.jobs[job_id] = {
        "job_id": job_id,
        "model_id": "test-owner/test-model",
        "status": "running",
    }
    final_path = tmp_path / "models" / "transformers" / "test-owner--test-model" / "main"

    await service.execute_claimed_job(
        {
            "job_id": job_id,
            "lease_token": token,
            "model_id": "test-owner/test-model",
            "revision": None,
            "channel_id": "core_runtime_transformers",
            "storage_key": "transformers",
            "install_path": str(final_path),
        }
    )

    assert (final_path / "weights.bin").read_bytes() == b"durable-model"
    assert repository.promotion_reservations == 1
    assert repository.complete_calls == 1
    assert repository.jobs[job_id]["status"] == "completed"

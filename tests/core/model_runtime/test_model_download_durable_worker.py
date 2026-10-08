from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Mapping, Optional, Sequence
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.config.model_download import ModelDownloadWorkerSettings
from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    DownloadResult,
    ModelInfo,
    ModelOrchestratorError,
    ModelOrchestratorService,
)
from ai_karen_engine.core.model_runtime.model_download_control_service import (
    ModelDownloadControlService,
)


class _FakePublication:
    def __init__(
        self,
        repository: "FakeModelDownloadRepository",
        *,
        job_id: str,
        lease_token: str,
        install_path: str,
    ) -> None:
        self.repository = repository
        self.job_id = job_id
        self.lease_token = lease_token
        self.install_path = install_path

    async def complete(self, result_payload: Mapping[str, Any]) -> dict[str, Any]:
        completed = await self.repository.complete_job(
            job_id=self.job_id,
            lease_token=self.lease_token,
            result_payload=result_payload,
            install_path=self.install_path,
        )
        if completed is None:
            raise RuntimeError("fake publication ownership changed")
        return completed

    async def abort_for_retry(
        self,
        *,
        error: str,
        retry_base_seconds: int,
    ) -> dict[str, Any]:
        aborted = await self.repository.fail_or_retry(
            job_id=self.job_id,
            lease_token=self.lease_token,
            error=error,
            retry_base_seconds=retry_base_seconds,
        )
        if aborted is None:
            raise RuntimeError("fake publication ownership changed during abort")
        return aborted


class FakeModelDownloadRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.valid_leases: set[tuple[str, str]] = set()
        self.import_calls = 0
        self.complete_calls = 0
        self.abort_calls = 0
        self.promotion_reservations = 0
        self.publication_guards = 0
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

    async def claim_expired_promotion_for_recovery(self, **_: Any) -> Optional[dict[str, Any]]:
        return None

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

    @asynccontextmanager
    async def publication_guard(
        self,
        *,
        job_id: str,
        lease_token: str,
        install_path: str,
    ) -> AsyncIterator[Optional[_FakePublication]]:
        self.publication_guards += 1
        row = self.jobs.get(job_id)
        if (
            (job_id, lease_token) not in self.valid_leases
            or row is None
            or row.get("status") != "promoting"
        ):
            yield None
            return
        yield _FakePublication(
            self,
            job_id=job_id,
            lease_token=lease_token,
            install_path=install_path,
        )

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
        self.valid_leases.discard((job_id, lease_token))
        return self._stamp(row)

    async def release_publication_for_recovery(self, **_: Any) -> bool:
        return True

    async def fail_or_retry(
        self,
        *,
        job_id: str,
        lease_token: str,
        error: str,
        retry_base_seconds: int,
    ) -> Optional[dict[str, Any]]:
        del retry_base_seconds
        self.abort_calls += 1
        row = self.jobs.get(job_id)
        if (
            (job_id, lease_token) not in self.valid_leases
            or row is None
            or row.get("status") not in {"running", "promoting", "pause_requested"}
        ):
            return None
        row.update(
            status="queued",
            error=error,
            message="Download failed; queued for retry",
        )
        self.valid_leases.discard((job_id, lease_token))
        return self._stamp(row)

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
    # The lifecycle test is intentionally offline. Supply verified, ungated
    # repository metadata rather than bypassing the production consent gate.
    service._orchestrator.get_model_info = AsyncMock(
        return_value=ModelInfo(
            model_id="test-owner/test-model",
            owner="test-owner",
            repository="test-model",
            storage_key="transformers",
            license=None,
            gated=False,
            revision="test-resolved-sha",
        )
    )

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
    await orchestrator.replace_registry_entry(
        request.model_id,
        {
            "model_id": request.model_id,
            "owner": owner,
            "repository": repo,
            "storage_key": request.storage_key or "transformers",
            "revision": request.revision or "main",
            "install_path": str(path),
            "files": [{"path": "weights.bin", "size": 13}],
            "total_size": 13,
            "pinned": bool(request.pin),
            "last_modified": datetime.now(timezone.utc).isoformat(),
            "downloads": 0,
            "likes": None,
            "tags": [],
            "license": None,
            "description": None,
        },
    )
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
    assert repository.publication_guards == 0
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
async def test_registry_failure_restores_previous_install_and_requeues(
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
    final_path.mkdir(parents=True)
    (final_path / "weights.bin").write_bytes(b"previous-model")
    previous_entry = {
        "model_id": "test-owner/test-model",
        "install_path": str(final_path),
        "revision": "previous",
    }
    await service._orchestrator.replace_registry_entry("test-owner/test-model", previous_entry)

    async def fail_registry(model_id: str, entry: Optional[Mapping[str, Any]]) -> None:
        del model_id, entry
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(service._orchestrator, "replace_registry_entry", fail_registry)

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

    assert (final_path / "weights.bin").read_bytes() == b"previous-model"
    assert not list(final_path.parent.glob("main.previous-*"))
    assert repository.promotion_reservations == 1
    assert repository.publication_guards == 1
    assert repository.complete_calls == 0
    assert repository.abort_calls == 1
    assert repository.jobs[job_id]["status"] == "queued"


@pytest.mark.asyncio
async def test_valid_lease_publishes_and_completes_inside_repository_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    monkeypatch.setattr(ModelOrchestratorService, "download_model", _fake_staged_download)
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
    assert not (final_path / ".karen-publication.json").exists()
    assert not list(final_path.parent.glob("main.previous-*"))
    assert repository.promotion_reservations == 1
    assert repository.publication_guards == 1
    assert repository.complete_calls == 1
    assert repository.jobs[job_id]["status"] == "completed"


@pytest.mark.asyncio
async def test_validation_fails_closed_when_access_metadata_is_unavailable(
    tmp_path: Path,
) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    await service.update_policy({"require_license_acceptance": True})
    service._orchestrator.get_model_info = AsyncMock(
        side_effect=RuntimeError("metadata unavailable")
    )

    validation = await service.validate_download(
        model_id="test-owner/test-model",
        channel_id="core_runtime_transformers",
    )

    assert validation.allowed is False
    assert validation.license_required is False
    assert any(
        "could not be verified" in reason
        for reason in validation.blocking_reasons
    )


@pytest.mark.asyncio
async def test_start_download_pins_reviewed_sha_but_keeps_main_install_slot(
    tmp_path: Path,
) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    service._orchestrator.get_model_info = AsyncMock(
        return_value=ModelInfo(
            model_id="test-owner/test-model",
            owner="test-owner",
            repository="test-model",
            storage_key="transformers",
            license=None,
            gated=False,
            revision="resolved-sha-123",
        )
    )

    job = await service.start_download(
        {
            "model_id": "test-owner/test-model",
            "revision": None,
            "validated_revision": "resolved-sha-123",
            "channel_id": "core_runtime_transformers",
        },
        {"user_id": "test-user"},
    )

    assert job["revision"] == "resolved-sha-123"
    assert Path(job["install_path"]).name == "main"
    service._orchestrator.get_model_info.assert_awaited_once()
    call = service._orchestrator.get_model_info.await_args
    assert call.args[1] == "resolved-sha-123"
    assert call.kwargs["refresh_remote"] is True


@pytest.mark.asyncio
async def test_start_download_rejects_changed_reviewed_revision(
    tmp_path: Path,
) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    service._orchestrator.get_model_info = AsyncMock(
        return_value=ModelInfo(
            model_id="test-owner/test-model",
            owner="test-owner",
            repository="test-model",
            storage_key="transformers",
            license=None,
            gated=False,
            revision="different-sha",
        )
    )

    with pytest.raises(ModelOrchestratorError, match="revision changed"):
        await service.start_download(
            {
                "model_id": "test-owner/test-model",
                "validated_revision": "reviewed-sha",
                "channel_id": "core_runtime_transformers",
            },
            {"user_id": "test-user"},
        )


@pytest.mark.asyncio
async def test_reported_license_requires_acknowledgment_even_when_ungated(
    tmp_path: Path,
) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    service._orchestrator.get_model_info = AsyncMock(
        return_value=ModelInfo(
            model_id="test-owner/test-model",
            owner="test-owner",
            repository="test-model",
            storage_key="transformers",
            license="Apache-2.0",
            gated=False,
            revision="license-sha",
        )
    )

    blocked = await service.validate_download(
        model_id="test-owner/test-model",
        channel_id="core_runtime_transformers",
        accept_license=False,
    )
    allowed = await service.validate_download(
        model_id="test-owner/test-model",
        channel_id="core_runtime_transformers",
        accept_license=True,
    )

    assert blocked.license_required is True
    assert blocked.allowed is False
    assert "License acceptance is required" in blocked.blocking_reasons[0]
    assert allowed.license_required is True
    assert allowed.allowed is True


@pytest.mark.asyncio
async def test_recommendation_verification_failure_does_not_promote_curated_license(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    service._orchestrator.snapshot_registry_entry = AsyncMock(return_value=None)
    service._orchestrator.get_model_info = AsyncMock(
        side_effect=RuntimeError("metadata endpoint offline")
    )
    monkeypatch.setattr(
        "ai_karen_engine.core.model_runtime.model_download_control_service.load_model_download_recommendations",
        lambda: {"recommendations": [{
            "id": "spacy-english-core",
            "model_id": "spacy/en_core_web_sm",
            "label": "spaCy English Core",
            "tier": "essential",
            "channel_id": "core_spacy",
            "license": "MIT",
        }]},
    )

    result = await service.get_recommendations()
    item = result["recommendations"][0]
    assert item["license"] == "MIT"
    assert item["metadata_verified"] is False
    assert item["verification_state"] == "unavailable"
    assert item["resolved_revision"] is None
    assert "connectivity" in item["verification_error"]
    assert result["essential_ready"] is False


@pytest.mark.asyncio
async def test_recommendation_verified_metadata_overrides_curated_license(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeModelDownloadRepository()
    service = _service(tmp_path, repository)
    service._orchestrator.snapshot_registry_entry = AsyncMock(return_value=None)
    service._orchestrator.get_model_info = AsyncMock(return_value=ModelInfo(
        model_id="spacy/en_core_web_sm",
        owner="spacy",
        repository="en_core_web_sm",
        storage_key="spacy",
        license="MIT",
        gated=False,
        revision="0123456789abcdef0123456789abcdef01234567",
    ))
    monkeypatch.setattr(
        "ai_karen_engine.core.model_runtime.model_download_control_service.load_model_download_recommendations",
        lambda: {"recommendations": [{
            "id": "spacy-english-core",
            "model_id": "spacy/en_core_web_sm",
            "label": "spaCy English Core",
            "tier": "essential",
            "channel_id": "core_spacy",
            "license": "unknown",
        }]},
    )

    item = (await service.get_recommendations())["recommendations"][0]
    assert item["metadata_verified"] is True
    assert item["verification_state"] == "verified"
    assert item["verification_error"] is None
    assert item["license"] == "MIT"
    assert item["resolved_revision"] == "0123456789abcdef0123456789abcdef01234567"


def test_model_file_integrity_checks_cover_spacy_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "pipeline"
    root.mkdir()
    files, total_size = ModelOrchestratorService._walk_files(root)
    assert files == []
    assert total_size == 0
    with pytest.raises(ModelOrchestratorError, match="no usable files"):
        ModelOrchestratorService._validate_downloaded_artifacts(
            files, total_size, storage_key="spacy", model_id="spacy/en_core_web_sm"
        )
    for filename in ("config.cfg", "meta.json", "tokenizer"):
        (root / filename).write_text("content", encoding="utf-8")
    files, total_size = ModelOrchestratorService._walk_files(root)
    assert total_size > 0
    assert {"config.cfg", "meta.json", "tokenizer"} <= {
        entry["path"] for entry in files if entry["size"] > 0
    }
    ModelOrchestratorService._validate_downloaded_artifacts(
        files, total_size, storage_key="spacy", model_id="spacy/en_core_web_sm"
    )
    (root / "tokenizer").unlink()
    partial, partial_size = ModelOrchestratorService._walk_files(root)
    with pytest.raises(ModelOrchestratorError, match="incomplete"):
        ModelOrchestratorService._validate_downloaded_artifacts(
            partial, partial_size, storage_key="spacy", model_id="spacy/en_core_web_sm"
        )

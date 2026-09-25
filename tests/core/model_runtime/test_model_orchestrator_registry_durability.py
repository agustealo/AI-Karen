from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

from ai_karen_engine.core.model_runtime.management import model_orchestrator_service as module
from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    E_DISK,
    ModelOrchestratorError,
    ModelOrchestratorService,
)


def _service(tmp_path: Path) -> ModelOrchestratorService:
    return ModelOrchestratorService(
        {
            "models_root": str(tmp_path / "models"),
            "registry_path": str(tmp_path / "models" / "llm_registry.json"),
        }
    )


def _entry(revision: str) -> dict[str, object]:
    return {
        "model_id": "test-owner/test-model",
        "storage_key": "transformers",
        "revision": revision,
        "install_path": f"/models/test-owner--test-model/{revision}",
    }


@pytest.mark.asyncio
async def test_registry_candidate_is_fsynced_before_memory_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    fsync_calls: list[int] = []

    monkeypatch.setattr(module.os, "fsync", lambda fd: fsync_calls.append(fd))

    await service.replace_registry_entry("test-owner/test-model", _entry("v1"))

    persisted = json.loads(service.registry_path.read_text(encoding="utf-8"))
    assert persisted["test-owner/test-model"]["revision"] == "v1"
    assert (await service.snapshot_registry_entry("test-owner/test-model"))["revision"] == "v1"
    expected_fsyncs = 1 if os.name == "nt" else 2
    assert len(fsync_calls) == expected_fsyncs
    assert not list(service.registry_path.parent.glob(f".{service.registry_path.name}.*.tmp"))


@pytest.mark.asyncio
async def test_pre_replace_fsync_failure_preserves_previous_disk_and_memory_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    await service.replace_registry_entry("test-owner/test-model", _entry("old"))
    previous_disk = service.registry_path.read_text(encoding="utf-8")

    def fail_file_fsync(_: int) -> None:
        raise OSError("file fsync failed")

    monkeypatch.setattr(module.os, "fsync", fail_file_fsync)

    with pytest.raises(ModelOrchestratorError) as error:
        await service.replace_registry_entry("test-owner/test-model", _entry("new"))

    assert error.value.code == E_DISK
    assert error.value.details["canonical_replaced"] is False
    assert service.registry_path.read_text(encoding="utf-8") == previous_disk
    assert (await service.snapshot_registry_entry("test-owner/test-model"))["revision"] == "old"
    assert not list(service.registry_path.parent.glob(f".{service.registry_path.name}.*.tmp"))


@pytest.mark.asyncio
async def test_post_replace_directory_fsync_failure_aligns_memory_with_canonical_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    await service.replace_registry_entry("test-owner/test-model", _entry("old"))

    def fail_directory_fsync() -> None:
        raise OSError("directory fsync failed")

    monkeypatch.setattr(service, "_fsync_registry_directory", fail_directory_fsync)

    with pytest.raises(ModelOrchestratorError) as error:
        await service.replace_registry_entry("test-owner/test-model", _entry("new"))

    assert error.value.code == E_DISK
    assert error.value.details["canonical_replaced"] is True
    persisted = json.loads(service.registry_path.read_text(encoding="utf-8"))
    assert persisted["test-owner/test-model"]["revision"] == "new"
    assert (await service.snapshot_registry_entry("test-owner/test-model"))["revision"] == "new"


def test_registry_writer_contract_is_candidate_first_and_crash_durable() -> None:
    writer = inspect.getsource(ModelOrchestratorService._write_registry_unlocked)
    replace = inspect.getsource(ModelOrchestratorService.replace_registry_entry)

    flush = writer.index("handle.flush()")
    file_fsync = writer.index("os.fsync(handle.fileno())")
    atomic_replace = writer.index("os.replace(tmp, self.registry_path)")
    directory_fsync = writer.index("self._fsync_registry_directory()")
    assert flush < file_fsync < atomic_replace < directory_fsync
    assert "os.getpid()" in writer
    assert "time.time_ns()" in writer
    assert '"canonical_replaced": canonical_replaced' in writer

    candidate = replace.index("candidate = copy.deepcopy(self._registry)")
    persist = replace.index("self._write_registry_unlocked(candidate)", candidate)
    publish = replace.rindex("self._registry = candidate")
    assert candidate < persist < publish
    assert 'exc.details.get("canonical_replaced")' in replace

"""PluginKernel is the sole source of post-transition lifecycle observations.

These are real local filesystem/registry tests, not a replacement for the
dedicated PostgreSQL terminal CAS proof or whole-deployment fencing.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
    PluginLifecycleKernelObservation,
)
from ai_karen_engine.services.plugin_service import PluginService


def _create_plugin(
    root: Path,
    *,
    plugin_id: str = "kernel-terminal",
    explicit_disabled: bool = True,
    voice_modality: bool = False,
) -> None:
    plugin_dir = root / plugin_id
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "handler.py").write_text(
        "class MainExtension:\n    pass\n", encoding="utf-8"
    )
    descriptor: dict[str, object] = {
        "name": plugin_id,
        "version": "1.0.0",
        "display_name": "Kernel Terminal Fixture",
        "description": "Disposable kernel lifecycle evidence proof",
        "author": "KAREN",
        "license": "MIT",
        "category": "test",
        "entrypoint": "handler:MainExtension",
        "rbac": {"default_enabled": False},
    }
    if voice_modality:
        descriptor["capabilities"] = {
            "voice_modality": {
                "version": "1.0.0",
                "modalities": ["tts"],
                "languages": ["en"],
                "streaming": False,
                "voice_cloning": False,
            }
        }
    (plugin_dir / "plugin_manifest.json").write_text(
        json.dumps(descriptor), encoding="utf-8"
    )
    if explicit_disabled:
        (plugin_dir / ".karen-manual-disabled").write_text(
            "Plugin disabled explicitly; requires enable\n", encoding="utf-8"
        )


@pytest.mark.asyncio
async def test_kernel_observation_requires_actual_marker_and_runtime_state(
    tmp_path: Path,
) -> None:
    _create_plugin(tmp_path)
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    op_id = str(uuid.uuid4())

    initial = await kernel.observe_lifecycle_for_finalization(
        "kernel-terminal", operation_id=op_id
    )
    assert isinstance(initial, PluginLifecycleKernelObservation)
    assert initial.operation_id == op_id
    assert initial.observed_state == "disabled"
    assert len(initial.manifest_checksum) == 64

    assert await service.enable_plugin("kernel-terminal")
    active = await kernel.observe_lifecycle_for_finalization(
        "kernel-terminal", operation_id=op_id
    )
    assert active.observed_state == "enabled"
    assert active.manifest_checksum == initial.manifest_checksum

    kernel._active["test-running"] = "kernel-terminal"
    with pytest.raises(RuntimeError, match="active executions"):
        await kernel.observe_lifecycle_for_finalization(
            "kernel-terminal", operation_id=op_id
        )
    del kernel._active["test-running"]

    assert await service.disable_plugin("kernel-terminal")
    inactive = await kernel.observe_lifecycle_for_finalization(
        "kernel-terminal", operation_id=op_id
    )
    assert inactive.observed_state == "disabled"
    assert inactive.manifest_checksum == initial.manifest_checksum


@pytest.mark.asyncio
async def test_kernel_does_not_attest_derived_disabled_or_untrusted_state(
    tmp_path: Path,
) -> None:
    _create_plugin(tmp_path, explicit_disabled=False)
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    op_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError, match="Explicit disable marker"):
        await kernel.observe_lifecycle_for_finalization(
            "kernel-terminal", operation_id=op_id
        )

    package = tmp_path / "kernel-terminal"
    (package / ".karen-manual-disabled").symlink_to(tmp_path / "outside")
    with pytest.raises(RuntimeError, match="Untrusted"):
        await kernel.observe_lifecycle_for_finalization(
            "kernel-terminal", operation_id=op_id
        )
    (package / ".karen-manual-disabled").unlink()
    (package / ".karen-upload-origin").write_text("manual upload", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unavailable"):
        await kernel.observe_lifecycle_for_finalization(
            "kernel-terminal", operation_id=op_id
        )


@pytest.mark.asyncio
async def test_kernel_refuses_manifest_drift_without_refresh(tmp_path: Path) -> None:
    _create_plugin(tmp_path)
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    manifest_path = tmp_path / "kernel-terminal" / "plugin_manifest.json"
    altered = json.loads(manifest_path.read_text(encoding="utf-8"))
    altered["description"] = "changed after registry validation"
    manifest_path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(RuntimeError, match="manifest drifted"):
        await kernel.observe_lifecycle_for_finalization(
            "kernel-terminal", operation_id=str(uuid.uuid4())
        )


@pytest.mark.asyncio
async def test_voice_modality_cannot_be_finalized_as_generic_plugin(
    tmp_path: Path,
) -> None:
    _create_plugin(tmp_path, plugin_id="voice-terminal", voice_modality=True)
    service = PluginService(tmp_path, tmp_path)
    await service.initialize()
    kernel = service.kernel
    assert kernel is not None
    with pytest.raises(RuntimeError, match="Specialized plugin lifecycle authority"):
        await kernel.observe_lifecycle_for_finalization(
            "voice-terminal", operation_id=str(uuid.uuid4())
        )


def test_kernel_observation_rejects_bogus_identifiers() -> None:
    with pytest.raises(ValueError):
        PluginLifecycleKernelObservation(
            operation_id="not-a-canonical-uuid",
            installation_id="kernel-terminal",
            manifest_checksum="a" * 64,
            observed_state="enabled",
        )

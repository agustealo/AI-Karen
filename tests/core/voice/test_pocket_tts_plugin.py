"""Pocket v4.0.1 plugin: governed local-only model admission and voice contracts."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import io
import json
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.extensions.platform.core.registry.validator import ExtensionValidator

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "src" / "ai_karen_engine" / "extensions" / "plugins" / "pocket-tts"
TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def module():
    loader = importlib.util.spec_from_file_location(
        "test_pocket_tts_engine", PACKAGE / "handler.py"
    )
    assert loader and loader.loader
    instance = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(instance)
    return instance


def _manifest():
    data = json.loads((PACKAGE / "plugin_manifest.json").read_text(encoding="utf-8"))
    return ExtensionManifest.from_dict(data)


def _engine(module):
    return module.MainExtension(_manifest(), SimpleNamespace(tenant_id=TENANT))


def _wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\x00\x00\xff\x00")
    return output.getvalue()


def _job(spec, root: Path, *, tenant: str = TENANT, licensed: bool = True):
    return {
        "job_id": "completed-test-job",
        "channel_id": "plugin_audio",
        "model_id": spec["model_id"],
        "revision": spec["revision"],
        "status": "completed",
        "tenant_id": tenant,
        "license_accepted": licensed,
        "trust_remote_code": False,
        "install_path": str(root),
    }


def _snapshot(module, tmp_path):
    spec = module._read_spec()
    model_dir = tmp_path / "audio" / "kyutai--pocket-tts" / spec["revision"]
    subdir = model_dir / spec["model_subdirectory"]
    folder = subdir / "embeddings"
    folder.mkdir(parents=True)
    (subdir / "model.safetensors").write_bytes(b"test-only, not model weights")
    (subdir / "tokenizer.model").write_bytes(b"test-tokenizer")
    (folder / "alba.safetensors").write_bytes(b"test-voice")
    return model_dir, spec


def test_manifest_is_versioned_closed_and_default_disabled():
    manifest = _manifest()
    valid, errors, _ = ExtensionValidator().validate_manifest(manifest)
    assert valid, errors
    declaration = manifest.capabilities.voice_modality
    assert declaration and declaration.modalities == ["tts"]
    assert not declaration.voice_cloning and not declaration.streaming
    assert manifest.rbac.default_enabled is False
    assert not manifest.permissions.network_access
    assert manifest.execution_input_schema is not None
    assert manifest.execution_input_schema.additional_properties is False
    assert "config_schema" not in json.loads((PACKAGE / "plugin_manifest.json").read_text())


@pytest.mark.parametrize("field", ["modalities", "languages", "streaming", "voice_cloning"])
def test_voice_manifest_rejects_bad_declarations(field):
    from pydantic import ValidationError

    data = json.loads((PACKAGE / "plugin_manifest.json").read_text())
    decl = data["capabilities"]["voice_modality"]
    decl[field] = (
        ["unknown"] if field == "modalities"
        else ["invalid_language_code!"] if field == "languages"
        else "not-bool"
    )
    with pytest.raises(ValidationError):
        ExtensionManifest.from_dict(data)


@pytest.mark.asyncio
async def test_missing_model_is_not_healthy_tts(module, monkeypatch):
    from ai_karen_engine.core.model_runtime import model_download_control_service as control
    monkeypatch.setattr(
        control, "get_model_download_control_service",
        lambda: SimpleNamespace(
            models_root=Path("/nonexistent"),
            list_completed_model_installations=AsyncMock(return_value=[]),
        ),
    )
    engine = _engine(module)
    await engine.initialize()
    assert engine.get_status()["status"] == "healthy"
    catalog = await engine.run({"operation": "catalog"}, SimpleNamespace(tenant_id=TENANT))
    assert catalog["status"] == "unavailable"
    assert not catalog["voices"]
    with pytest.raises(RuntimeError, match="pocket_local_synthesis_unavailable"):
        await engine.run(
            {"operation": "synthesize", "text": "No fake sound"}, SimpleNamespace(tenant_id=TENANT)
        )


@pytest.mark.asyncio
async def test_installed_licensed_model_can_generate_real_wav_contract(module, monkeypatch, tmp_path):
    from ai_karen_engine.core.model_runtime import model_download_control_service as control
    snapshot, spec = _snapshot(module, tmp_path)
    service = SimpleNamespace(
        models_root=tmp_path,
        list_completed_model_installations=AsyncMock(return_value=[_job(spec, snapshot)]),
    )
    monkeypatch.setattr(control, "get_model_download_control_service", lambda: service)
    loaded = []
    def fake_load(path, package_spec):
        loaded.append((path, package_spec["runtime_version"]))
        return SimpleNamespace(sample_rate=24_000), {"alba": object()}
    monkeypatch.setattr(module, "_load_offline_model", fake_load)
    monkeypatch.setattr(module, "_pcm16_wav", lambda model, state, text: _wav())

    engine = _engine(module)
    await engine.initialize()
    caller = SimpleNamespace(tenant_id=TENANT)
    catalog = await engine.run({"operation": "catalog"}, caller)
    assert catalog["status"] == "ready"
    assert catalog["features"]["streaming"] is False
    assert catalog["features"]["voice_cloning"] is False
    assert catalog["voices"] == [{"id": "alba", "name": "Alba", "language": "en"}]
    output = await engine.run(
        {"operation": "synthesize", "text": "Hello Karen", "voice_id": "alba"}, caller
    )
    assert output["engine"] == "pocket-tts"
    assert base64.b64decode(output["audio_base64"]) == _wav()
    assert loaded == [(snapshot.resolve(), "4.0.1")]
    assert service.list_completed_model_installations.await_count == 2
    assert service.list_completed_model_installations.await_args.kwargs == {
        "tenant_id": TENANT,
        "model_id": spec["model_id"],
        "revision": spec["revision"],
        "channel_id": spec["channel_id"],
    }
    await engine.shutdown()
    assert engine.get_status()["model_loaded"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", [
    "other_tenant", "legacy_unowned", "legacy_blank",
    "license_missing", "wrong_revision",
])
async def test_unapproved_model_job_never_loads(module, monkeypatch, tmp_path, variant):
    from ai_karen_engine.core.model_runtime import model_download_control_service as control
    snapshot, spec = _snapshot(module, tmp_path)
    job = _job(spec, snapshot)
    if variant == "other_tenant":
        job["tenant_id"] = OTHER
    elif variant == "legacy_unowned":
        job["tenant_id"] = None
    elif variant == "legacy_blank":
        job["tenant_id"] = ""
    elif variant == "license_missing":
        job["license_accepted"] = False
    else:
        job["revision"] = "deadbeef" * 5
    monkeypatch.setattr(control, "get_model_download_control_service", lambda: SimpleNamespace(
        models_root=tmp_path,
        list_completed_model_installations=AsyncMock(return_value=[job]),
    ))
    monkeypatch.setattr(module, "_load_offline_model", lambda *a: pytest.fail("unapproved model was loaded"))
    engine = _engine(module)
    await engine.initialize()
    result = await engine.run({"operation": "catalog"}, SimpleNamespace(tenant_id=TENANT))
    assert result["status"] == "unavailable"


@pytest.mark.asyncio
async def test_symlinked_model_voice_is_not_admitted(module, monkeypatch, tmp_path):
    from ai_karen_engine.core.model_runtime import model_download_control_service as control
    snapshot, spec = _snapshot(module, tmp_path)
    voice = snapshot / spec["model_subdirectory"] / "embeddings" / "alba.safetensors"
    voice.unlink()
    target = tmp_path / "outside.safetensors"
    target.write_bytes(b"test outside")
    voice.symlink_to(target)
    monkeypatch.setattr(control, "get_model_download_control_service", lambda: SimpleNamespace(
        models_root=tmp_path,
        list_completed_model_installations=AsyncMock(return_value=[_job(spec, snapshot)]),
    ))
    engine = _engine(module)
    await engine.initialize()
    assert (await engine.run({"operation": "catalog"}, SimpleNamespace(tenant_id=TENANT)))["voices"] == []


def test_external_model_reference_is_never_allowed(module):
    with pytest.raises(RuntimeError, match="external_asset_forbidden"):
        module._requires_no_network({"model": "hf://kyutai/pocket-tts/weight"})
    with pytest.raises(RuntimeError, match="external_asset_forbidden"):
        module._requires_no_network({"model": "https://example.org/weight"})


@pytest.mark.asyncio
async def test_invalid_tenant_and_operations_fail_before_model_lookup(module):
    engine = _engine(module)
    await engine.initialize()
    with pytest.raises(RuntimeError, match="tenant_scope"):
        await engine.run({"operation": "catalog"}, SimpleNamespace(tenant_id="tenant-a"))
    with pytest.raises(ValueError, match="operation"):
        await engine.run({"operation": "unknown"}, SimpleNamespace(tenant_id=TENANT))


@pytest.mark.asyncio
async def test_concurrent_calls_are_serialized_through_native_worker(module, monkeypatch):
    engine = _engine(module)
    await engine.initialize()
    first_entered = asyncio.Event()
    release = asyncio.Event()
    active = 0
    peak = 0

    async def fake_ready(_tenant):
        return True

    async def worker():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        first_entered.set()
        await release.wait()
        active -= 1
        return True

    monkeypatch.setattr(engine, "_ensure_ready", fake_ready)
    original = engine._exclusively
    monkeypatch.setattr(engine, "_exclusively", lambda _func: original(worker))
    first = asyncio.create_task(engine.run({"operation": "catalog"}, SimpleNamespace(tenant_id=TENANT)))
    await asyncio.wait_for(first_entered.wait(), 1)
    second = asyncio.create_task(engine.run({"operation": "catalog"}, SimpleNamespace(tenant_id=TENANT)))
    await asyncio.sleep(0)
    assert peak == 1
    release.set()
    await asyncio.gather(first, second)
    assert peak == 1



@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["catalog", "synthesize"])
async def test_queued_request_is_denied_after_plugin_shutdown(module, monkeypatch, operation):
    """Shutdown wins the lock: no older admission may revive inference afterward."""
    engine = _engine(module)
    await engine.initialize()

    async def unexpected_model_lookup(_tenant):
        pytest.fail("disabled Pocket plugin must not query or load a model")

    monkeypatch.setattr(engine, "_ensure_ready", unexpected_model_lookup)
    params = {"operation": operation}
    if operation == "synthesize":
        params.update({"text": "Must not synthesize", "voice_id": "alba"})

    # Both requests enter while the engine is still active; shutdown is
    # first in the lock queue. The subsequent request must recheck the active
    # flag only once the shutdown has retired the model and released the lock.
    async with engine._lock:
        shutdown = asyncio.create_task(engine.shutdown())
        await asyncio.sleep(0)
        queued = asyncio.create_task(
            engine.run(params, SimpleNamespace(tenant_id=TENANT))
        )
        await asyncio.sleep(0)
        assert not shutdown.done()
        assert not queued.done()

    await asyncio.wait_for(shutdown, timeout=2)
    with pytest.raises(RuntimeError, match="pocket_plugin_disabled"):
        await asyncio.wait_for(queued, timeout=2)
    assert engine.get_status()["status"] == "unavailable"
    assert engine.get_status()["model_loaded"] is False

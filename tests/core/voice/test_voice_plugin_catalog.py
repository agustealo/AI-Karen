"""Engine-neutral VoiceRuntime plugin admission and bounded audio proof."""

from __future__ import annotations

import asyncio
import base64
import io
import uuid
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.voice.contracts import SynthesisInput, VoiceContractError
from ai_karen_engine.services.voice_runtime import VoiceRuntime

TENANT = str(uuid.UUID("11111111-1111-1111-1111-111111111111"))
USER = {"user_id": "consumer-1", "tenant_id": TENANT, "roles": ["user"], "permissions": []}


def wav() -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24_000)
        writer.writeframes(b"\x00\x00\x01\x00")
    return out.getvalue()


def catalog_payload():
    return {
        "engine_id": "pocket-tts",
        "status": "ready",
        "model_id": "kyutai/pocket-tts",
        "model_revision": "pinned",
        "features": {"synthesis": True, "streaming": False, "voice_cloning": False},
        "voices": [{"id": "alba", "name": "Alba", "language": "en"}],
    }


def service(monkeypatch, *, enabled=True, ready=True):
    from ai_karen_engine.services import plugin_service as module

    manifest = SimpleNamespace(
        name="pocket-tts",
        display_name="Pocket TTS",
        version="1.0.0",
        capabilities=SimpleNamespace(
            voice_modality=SimpleNamespace(
                version="1.0.0", modalities=["tts"], streaming=False, voice_cloning=False
            )
        ),
    )
    records = [{"manifest": manifest, "status": "enabled"}] if enabled else []
    result = SimpleNamespace(
        status=module.ExecutionStatus.COMPLETED if ready else module.ExecutionStatus.FAILED,
        result=catalog_payload() if ready else None,
    )
    fake = SimpleNamespace(
        list_plugins=AsyncMock(return_value=records),
        execute_plugin=AsyncMock(return_value=result),
    )
    monkeypatch.setattr(module, "get_plugin_service", lambda: fake)
    from ai_karen_engine.auth import rbac_middleware
    monkeypatch.setattr(
        rbac_middleware, "get_rbac_manager",
        lambda: SimpleNamespace(get_user_permissions=lambda principal: []),
    )
    return fake


@pytest.mark.asyncio
async def test_catalog_requires_enabled_verified_healthy_engine(monkeypatch):
    runtime = VoiceRuntime()
    plugin_service = service(monkeypatch, enabled=False)
    assert (await runtime.engine_catalog(USER))["engines"] == []
    plugin_service.execute_plugin.assert_not_awaited()

    plugin_service = service(monkeypatch, ready=False)
    assert (await runtime.engine_catalog(USER))["engines"] == []
    plugin_service.execute_plugin.assert_awaited_once()
    plugin_service.execute_plugin.assert_awaited_with(
        plugin_name="pocket-tts", parameters={"operation": "catalog"},
        user_id=USER["user_id"], tenant_id=TENANT, correlation_id=None,
        roles=["user"], permissions=[], timeout_seconds=120,
    )


@pytest.mark.asyncio
async def test_valid_catalog_is_projected_from_governed_execution(monkeypatch):
    plugin_service = service(monkeypatch)
    result = await VoiceRuntime().engine_catalog(USER)
    assert result["contract_version"] == "1.0.0"
    assert result["engines"][0]["engine_id"] == "pocket-tts"
    assert result["engines"][0]["voices"][0]["id"] == "alba"
    assert result["engines"][0]["features"]["streaming"] is False
    plugin_service.execute_plugin.assert_awaited_once()


@pytest.mark.asyncio
async def test_plugin_synthesis_has_verified_audio_and_engine_identity(monkeypatch):
    plugin_service = service(monkeypatch)
    calls = []

    async def execute_plugin(**kwargs):
        calls.append(kwargs)
        result = catalog_payload() if kwargs["parameters"]["operation"] == "catalog" else {
            "engine": "pocket-tts",
            "voice_id": "alba",
            "content_type": "audio/wav",
            "audio_base64": base64.b64encode(wav()).decode("ascii"),
        }
        return SimpleNamespace(
            status=__import__("ai_karen_engine.services.plugin_service", fromlist=["ExecutionStatus"]).ExecutionStatus.COMPLETED,
            result=result,
        )

    plugin_service.execute_plugin = AsyncMock(side_effect=execute_plugin)
    output = await VoiceRuntime().synthesize_with_plugin(
        SynthesisInput(text="Hello offline", voice_id="alba"),
        engine_id="pocket-tts", principal=USER,
    )
    assert output.audio == wav()
    assert output.engine == "pocket-tts"
    assert len(calls) == 2
    assert calls[1]["parameters"]["text"] == "Hello offline"


@pytest.mark.asyncio
async def test_caller_does_not_select_unregistered_voice(monkeypatch):
    fake = service(monkeypatch)
    with pytest.raises(VoiceContractError, match="local_synthesis_voice_unavailable"):
        await VoiceRuntime().synthesize_with_plugin(
            SynthesisInput(text="Hello offline", voice_id="invented"),
            engine_id="pocket-tts", principal=USER,
        )
    assert fake.execute_plugin.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_audio", ["", "not-base64", base64.b64encode(b"wrong").decode("ascii")])
async def test_unverified_audio_never_reaches_browser(monkeypatch, bad_audio):
    plugin_service = service(monkeypatch)

    async def execute_plugin(**kwargs):
        payload = catalog_payload() if kwargs["parameters"]["operation"] == "catalog" else {
            "engine": "pocket-tts",
            "voice_id": "alba",
            "content_type": "audio/wav",
            "audio_base64": bad_audio,
        }
        from ai_karen_engine.services.plugin_service import ExecutionStatus
        return SimpleNamespace(status=ExecutionStatus.COMPLETED, result=payload)

    plugin_service.execute_plugin = AsyncMock(side_effect=execute_plugin)
    with pytest.raises(RuntimeError, match="local_synthesis_failed"):
        await VoiceRuntime().synthesize_with_plugin(
            SynthesisInput(text="Hello offline"), engine_id="pocket-tts", principal=USER
        )


@pytest.mark.asyncio
async def test_missing_user_or_tenant_fails_before_plugin_discovery(monkeypatch):
    fake = service(monkeypatch)
    for user in ({**USER, "tenant_id": "not-uuid"}, {**USER, "user_id": ""}):
        with pytest.raises(VoiceContractError):
            await VoiceRuntime().engine_catalog(user)
    fake.list_plugins.assert_not_awaited()
    fake.execute_plugin.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_catalog_and_targeted_synthesis_share_governance_without_extra_probes(monkeypatch):
    """A targeted synthesis cannot load unrelated plugins or repeat RBAC lookup."""
    fake = service(monkeypatch)
    pocket_manifest = fake.list_plugins.return_value[0]["manifest"]
    unrelated = SimpleNamespace(
        name="unrelated-tts",
        display_name="Unrelated TTS",
        version="1.0.0",
        capabilities=pocket_manifest.capabilities,
    )
    fake.list_plugins.return_value.insert(
        0, {"manifest": unrelated, "status": "enabled"}
    )

    from ai_karen_engine.auth import rbac_middleware
    from ai_karen_engine.services.plugin_service import ExecutionStatus

    authorized_principals = []

    def permissions(principal):
        authorized_principals.append(dict(principal))
        return []

    monkeypatch.setattr(
        rbac_middleware, "get_rbac_manager",
        lambda: SimpleNamespace(get_user_permissions=permissions),
    )

    probed_plugins = []

    async def execute_plugin(**kwargs):
        probed_plugins.append(kwargs["plugin_name"])
        if kwargs["parameters"]["operation"] == "catalog":
            payload = {**catalog_payload(), "engine_id": kwargs["plugin_name"]}
        else:
            payload = {
                "engine": kwargs["plugin_name"],
                "voice_id": "alba",
                "content_type": "audio/wav",
                "audio_base64": base64.b64encode(wav()).decode("ascii"),
            }
        return SimpleNamespace(status=ExecutionStatus.COMPLETED, result=payload)

    fake.execute_plugin = AsyncMock(side_effect=execute_plugin)
    runtime = VoiceRuntime()

    # Discovery must still inspect every enabled, governed voice candidate.
    full_catalog = await runtime.engine_catalog(USER)
    assert [entry["engine_id"] for entry in full_catalog["engines"]] == [
        "unrelated-tts", "pocket-tts"
    ]
    assert probed_plugins == ["unrelated-tts", "pocket-tts"]

    probed_plugins.clear()
    authorized_principals.clear()
    result = await runtime.synthesize_with_plugin(
        SynthesisInput(text="Local synthesis", voice_id="alba"),
        engine_id="pocket-tts", principal=USER,
    )
    assert result.audio == wav()
    assert probed_plugins == ["pocket-tts", "pocket-tts"]
    assert len(authorized_principals) == 1
    assert authorized_principals[0]["tenant_id"] == TENANT

    # An unknown engine must not trigger another installed model's catalog.
    probed_plugins.clear()
    with pytest.raises(RuntimeError, match="local_synthesis_unavailable"):
        await runtime.synthesize_with_plugin(
            SynthesisInput(text="No unrelated model probing"),
            engine_id="missing-tts", principal=USER,
        )
    assert probed_plugins == []

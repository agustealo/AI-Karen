"""Governed, CPU-first Pocket TTS v4.0.1 extension.

The canonical executor authorizes every invocation. This implementation
never downloads weights or voice states and never chooses a cloud fallback.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import tempfile
import uuid
import wave
from importlib import metadata, resources
from pathlib import Path
from typing import Any, Mapping

from ai_karen_engine.core.voice.contracts import MAX_AUDIO_BYTES, SynthesisInput
from ai_karen_engine.extensions.platform.core.host.base import (
    ExtensionBase,
    ExtensionContext,
    HookContext,
    HookPoint,
)

logger = logging.getLogger(__name__)
_SPEC_PATH = Path(__file__).with_name("model_spec.json")
_SAFE_VOICE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,95}$")
_MAX_VOICES = 32


def _read_spec() -> dict[str, Any]:
    """Only reviewed first-party package metadata is a model selection input."""
    data = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    if (
        data.get("schema_version") != 1
        or data.get("plugin_id") != "pocket-tts"
        or data.get("model_id") != "kyutai/pocket-tts-without-voice-cloning"
        or not re.fullmatch(r"[0-9a-f]{40}", str(data.get("revision", "")))
        or data.get("channel_id") != "plugin_audio"
        or data.get("runtime_version") != "4.0.1"
        or not re.fullmatch(r"english_[a-z0-9_-]+", str(data.get("language", "")))
    ):
        raise RuntimeError("pocket_model_spec_invalid")
    return data


def _safe_asset(root: Path, relative: str) -> Path:
    """Deny symlinks, absolute traversal and missing files under model root."""
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise RuntimeError("pocket_model_asset_unverified")
    parts = Path(relative).parts
    if ".." in parts or "." in parts or any(not part for part in parts):
        raise RuntimeError("pocket_model_asset_unverified")
    candidate = root.joinpath(*parts)
    if not candidate.is_file() or candidate.is_symlink():
        raise RuntimeError("pocket_model_asset_missing")
    for parent in (candidate, *candidate.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise RuntimeError("pocket_model_asset_unverified")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("pocket_model_asset_unverified")
    return candidate


def _voice_files(snapshot: Path, spec: Mapping[str, Any]) -> dict[str, Path]:
    """Only precomputed first-party model states, never user-controlled paths."""
    folder = snapshot / str(spec["model_subdirectory"]) / str(spec["voice_dir"])
    if folder.is_symlink() or not folder.is_dir() or not folder.resolve().is_relative_to(snapshot.resolve()):
        return {}
    available: dict[str, Path] = {}
    for candidate in sorted(folder.glob("*.safetensors"))[: _MAX_VOICES + 1]:
        if len(available) >= _MAX_VOICES:
            break
        if not _SAFE_VOICE_ID.fullmatch(candidate.stem):
            continue
        try:
            asset = _safe_asset(snapshot, str(candidate.relative_to(snapshot)))
        except (RuntimeError, ValueError):
            continue
        available[candidate.stem] = asset
    return available


def _requires_no_network(config: Any) -> None:
    """Ensure every model configuration URI resolves to a local artifact."""
    if isinstance(config, dict):
        for value in config.values():
            _requires_no_network(value)
    elif isinstance(config, list):
        for value in config:
            _requires_no_network(value)
    elif isinstance(config, str) and (
        "://" in config or config.startswith(("~", "$"))
    ):
        raise RuntimeError("pocket_model_external_asset_forbidden")


def _load_offline_model(
    snapshot: Path,
    spec: Mapping[str, Any],
) -> tuple[Any, dict[str, Any]]:
    """Load audited local data through Pocket's real public v4.0.1 Python API."""
    if metadata.version(str(spec["runtime_package"])) != spec["runtime_version"]:
        raise RuntimeError("pocket_runtime_version_mismatch")

    import yaml
    from pocket_tts import TTSModel

    base = str(spec["model_subdirectory"])
    weights = _safe_asset(snapshot, f"{base}/{spec['weights']}")
    tokenizer = _safe_asset(snapshot, f"{base}/{spec['tokenizer']}")
    voices = _voice_files(snapshot, spec)
    if not voices:
        raise RuntimeError("pocket_no_approved_local_voices")

    template = resources.files("pocket_tts").joinpath(
        "config", f"{spec['language']}.yaml"
    ).read_text(encoding="utf-8")
    config = yaml.safe_load(template)
    if not isinstance(config, dict) or not isinstance(config.get("flow_lm"), dict):
        raise RuntimeError("pocket_model_config_invalid")
    config["weights_path"] = str(weights)
    config["weights_path_without_voice_cloning"] = str(weights)
    config["flow_lm"]["lookup_table"]["tokenizer_path"] = str(tokenizer)
    _requires_no_network(config)

    # Pocket TTS requires a YAML filename. Generate it only within the
    # trusted host's short-lived temporary directory, never the model store.
    with tempfile.TemporaryDirectory(prefix="karen-pocket-") as temp_dir:
        config_path = Path(temp_dir) / "local.yaml"
        config_path.write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        model = TTSModel.load_model(config=str(config_path), quantize=False)

    voice_states: dict[str, Any] = {}
    for voice_id, file in voices.items():
        try:
            voice_states[voice_id] = model.get_state_for_audio_prompt(str(file))
        except Exception as exc:
            logger.warning(
                "Pocket voice state unavailable",
                extra={"voice_id": voice_id, "error_type": type(exc).__name__},
            )
    if not voice_states:
        raise RuntimeError("pocket_voice_states_invalid")
    if not isinstance(model.sample_rate, int) or model.sample_rate <= 0:
        raise RuntimeError("pocket_sample_rate_invalid")
    return model, voice_states


def _pcm16_wav(model: Any, state: Any, text: str) -> bytes:
    """Generate real model output and encode portable bounded mono PCM16 WAV."""
    audio = model.generate_audio(state, text)
    samples = audio.detach().cpu().flatten()
    if not 0 < samples.numel() <= (MAX_AUDIO_BYTES - 44) // 2:
        raise RuntimeError("pocket_speech_size_out_of_bounds")
    # Torch converts finite float waveforms without a separate audio library.
    if not bool(samples.isfinite().all()):
        raise RuntimeError("pocket_speech_nonfinite_samples")
    pcm = (samples.clamp(-1.0, 1.0) * 32767).short()
    # Keep the sample-rate and channel format stable for browser playback.
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(model.sample_rate)
        stream.writeframes(pcm.numpy().tobytes())
    encoded = output.getvalue()
    if not 44 <= len(encoded) <= MAX_AUDIO_BYTES:
        raise RuntimeError("pocket_speech_size_out_of_bounds")
    return encoded


class MainExtension(ExtensionBase):
    """Authorized, revision-pinned engine with tenant-safe model eligibility."""

    def __init__(self, manifest: Any, context: ExtensionContext) -> None:
        super().__init__(manifest, context)
        self._spec = _read_spec()
        self._active = False
        self._lock = asyncio.Lock()
        self._model: Any = None
        self._voices: dict[str, Any] = {}
        self._loaded_key: tuple[str, str, str] | None = None

    async def initialize(self) -> None:
        # Initialization and retirement share the native inference lock.
        async with self._lock:
            self._active = True

    async def shutdown(self) -> None:
        # Retire only after the kernel fences new work and active inference.
        async with self._lock:
            self._active = False
            self._model = None
            self._voices = {}
            self._loaded_key = None

    def get_status(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self._active else "unavailable",
            "initialized": self._active,
            "version": self.manifest.version,
            "model_loaded": self._model is not None,
        }

    async def execute_hook(self, hook_point: HookPoint, context: HookContext) -> dict[str, Any]:
        raise ValueError("pocket_unsupported_hook")

    async def _approved_snapshot(self, tenant_id: str) -> tuple[str, Path] | None:
        """Resolve only completed licensed jobs through Karen's model authority."""
        from ai_karen_engine.core.model_runtime.model_download_control_service import (
            get_model_download_control_service,
        )

        service = get_model_download_control_service()
        # The canonical PostgreSQL owner filters tenant/model/revision,
        # completed status, license and safe-code policy before pagination.
        # A global last-500 scan can hide a valid older install; accepting
        # NULL/unowned legacy jobs would cross the explicit tenant boundary.
        jobs = await service.list_completed_model_installations(
            tenant_id=tenant_id,
            model_id=self._spec["model_id"],
            revision=self._spec["revision"],
            channel_id=self._spec["channel_id"],
        )
        root = Path(service.models_root)
        if root.is_symlink() or not root.is_dir():
            return None
        root = root.resolve()
        for job in jobs:
            if (
                job.get("status") != "completed"
                or job.get("channel_id") != self._spec["channel_id"]
                or job.get("model_id") != self._spec["model_id"]
                or job.get("revision") != self._spec["revision"]
                or job.get("license_accepted") is not True
                or job.get("trust_remote_code") is True
                or str(job.get("tenant_id") or "") != tenant_id
            ):
                continue
            path = str(job.get("install_path") or "")
            if not path:
                continue
            snapshot = Path(path)
            if snapshot.is_symlink() or not snapshot.is_dir():
                continue
            try:
                resolved = snapshot.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    continue
                current = snapshot
                while current != root and current != current.parent:
                    if current.is_symlink():
                        raise RuntimeError("pocket_untrusted_snapshot_path")
                    current = current.parent
                if current != root:
                    continue
                base = str(self._spec["model_subdirectory"])
                _safe_asset(resolved, f"{base}/{self._spec['weights']}")
                _safe_asset(resolved, f"{base}/{self._spec['tokenizer']}")
                if not _voice_files(resolved, self._spec):
                    continue
            except (OSError, RuntimeError, ValueError):
                continue
            return str(job["job_id"]), resolved
        return None

    async def _ensure_ready(self, tenant_id: str) -> bool:
        try:
            authorized = await self._approved_snapshot(tenant_id)
        except Exception as exc:
            logger.warning(
                "Pocket model readiness could not be verified",
                extra={"engine_id": "pocket-tts", "error_type": type(exc).__name__},
            )
            self._model = None
            self._voices = {}
            self._loaded_key = None
            return False
        if authorized is None:
            self._model = None
            self._voices = {}
            self._loaded_key = None
            return False
        job_id, snapshot = authorized
        cache_key = (tenant_id, job_id, str(snapshot))
        if self._loaded_key == cache_key and self._model is not None and self._voices:
            return True
        self._model = None
        self._voices = {}
        self._loaded_key = None
        try:
            model, voices = await asyncio.to_thread(_load_offline_model, snapshot, self._spec)
        except Exception as exc:
            logger.warning(
                "Pocket local model unavailable",
                extra={"engine_id": "pocket-tts", "error_type": type(exc).__name__},
            )
            return False
        self._model = model
        self._voices = voices
        self._loaded_key = cache_key
        return True

    async def _exclusively(self, callback: Any) -> Any:
        task = asyncio.create_task(callback())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Do not release the model lock until native inference is finished.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            raise

    async def run(self, params: dict[str, Any], context: Any) -> dict[str, Any]:
        tenant_id = str(getattr(context, "tenant_id", "") or "")
        try:
            uuid.UUID(tenant_id)
        except (ValueError, AttributeError, TypeError):
            raise RuntimeError("pocket_tenant_scope_required") from None
        if not isinstance(params, dict) or params.get("operation") not in ("catalog", "synthesize"):
            raise ValueError("pocket_operation_unsupported")
        async with self._lock:
            # Recheck admission after waiting. Shutdown can retire the plugin
            # while an already-validated call is queued on this same lock.
            if not self._active:
                raise RuntimeError("pocket_plugin_disabled")
            ready = await self._exclusively(lambda: self._ensure_ready(tenant_id))
            if params["operation"] == "catalog":
                return {
                    "engine_id": self.manifest.name,
                    "status": "ready" if ready else "unavailable",
                    "model_id": self._spec["model_id"] if ready else None,
                    "model_revision": self._spec["revision"] if ready else None,
                    "language": "en",
                    "features": {
                        "synthesis": ready,
                        "streaming": False,
                        "voice_cloning": False,
                        "transcription": False,
                    },
                    "voices": [
                        {"id": voice_id, "name": voice_id.replace("_", " ").title(), "language": "en"}
                        for voice_id in sorted(self._voices)
                    ] if ready else [],
                }
            if not ready:
                raise RuntimeError("pocket_local_synthesis_unavailable")
            if set(params) - {"operation", "text", "voice_id"}:
                raise ValueError("pocket_invalid_input")
            request = SynthesisInput(text=params.get("text"), voice_id=params.get("voice_id"))
            voice_id = request.voice_id or sorted(self._voices)[0]
            state = self._voices.get(voice_id)
            if state is None:
                raise ValueError("pocket_voice_unavailable")
            model = self._model
            try:
                audio = await self._exclusively(
                    lambda: asyncio.to_thread(_pcm16_wav, model, state, request.text)
                )
            except Exception as exc:
                logger.error(
                    "Pocket native synthesis failed",
                    extra={"engine_id": self.manifest.name, "error_type": type(exc).__name__},
                )
                raise RuntimeError("pocket_synthesis_failed") from None
            return {
                "engine": self.manifest.name,
                "voice_id": voice_id,
                "content_type": "audio/wav",
                "audio_base64": base64.b64encode(audio).decode("ascii"),
            }

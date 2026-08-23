from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ai_karen_engine.config.config_asset_loaders import (
    load_model_runtime_discovery_config,
)
from ai_karen_engine.core.model_runtime.model_discovery_service import (
    get_model_discovery_service,
)
from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    DownloadRequest,
    E_INVALID,
    E_LICENSE,
    E_PERM,
    ModelOrchestratorError,
    ModelOrchestratorService,
)

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unserializable value: {type(value)!r}")


def _load_orchestrator_settings() -> dict[str, Any]:
    settings_path = Path("config_assets/settings.json")
    if not settings_path.exists():
        return {}

    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - config load is best effort
        logger.warning("Failed to load model settings config: %s", exc)
        return {}

    plugins = raw.get("plugins") or {}
    return dict(plugins.get("model_orchestrator") or {})


@dataclass(frozen=True)
class ModelDownloadPolicy:
    master_enabled: bool = True
    core_runtime_enabled: bool = True
    plugin_channels_enabled: bool = True
    image_channels_enabled: bool = True
    audio_channels_enabled: bool = True
    vision_channels_enabled: bool = True
    gguf_external_enabled: bool = True
    trust_remote_code: bool = False
    block_new_downloads: bool = False
    pause_active_downloads: bool = False
    quarantine_failed_models: bool = True
    require_license_acceptance: bool = True
    max_concurrent_downloads: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelDownloadChannel:
    id: str
    label: str
    group: str
    storage_key: str
    enabled: bool = True
    description: str = ""
    model_families: tuple[str, ...] = field(default_factory=tuple)
    modalities: tuple[str, ...] = field(default_factory=tuple)
    admin_only: bool = False

    def to_dict(self, *, locked_by_master: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        payload["model_families"] = list(self.model_families)
        payload["modalities"] = list(self.modalities)
        payload["locked_by_master"] = locked_by_master
        payload["effective_enabled"] = bool(self.enabled and not locked_by_master)
        return payload


@dataclass
class ModelDownloadJob:
    job_id: str
    model_id: str
    revision: Optional[str] = None
    channel_id: str = "core_runtime_transformers"
    storage_key: Optional[str] = None
    status: str = "queued"
    progress: float = 0.0
    message: str = "Queued"
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    requested_by: Optional[str] = None
    trust_remote_code: bool = False
    license_accepted: bool = False
    include_patterns: Optional[list[str]] = None
    exclude_patterns: Optional[list[str]] = None
    pin: bool = False
    force_redownload: bool = False
    pause_requested: bool = False
    cancel_requested: bool = False
    warnings: list[str] = field(default_factory=list)
    detected_runtime: Optional[str] = None
    detected_modality: Optional[str] = None
    install_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


@dataclass(frozen=True)
class ModelDownloadValidation:
    allowed: bool
    channel_id: str
    model_id: str
    revision: Optional[str] = None
    storage_key: Optional[str] = None
    install_path: Optional[str] = None
    detected_runtime: Optional[str] = None
    detected_modality: Optional[str] = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    blocking_reasons: tuple[str, ...] = field(default_factory=tuple)
    license_required: bool = False
    trust_remote_code_allowed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        payload["blocking_reasons"] = list(self.blocking_reasons)
        return payload


class ModelDownloadControlService:
    """Core model-download policy, queue, and discovery authority."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        base_config = dict(config or {})
        discovery_config = dict(load_model_runtime_discovery_config() or {})
        orchestrator_config = _load_orchestrator_settings()

        self.models_root = self._resolve_root(
            base_config.get("models_root")
            or orchestrator_config.get("models_root")
            or os.getenv("KAREN_MODELS_ROOT")
            or "models"
        )
        self.runtime_registry_root = self._resolve_root(
            base_config.get("runtime_registry_root")
            or orchestrator_config.get("runtime_registry_root")
            or self.models_root / ".runtime_registry"
        )
        self.state_path = self.runtime_registry_root / "model_download_control.json"

        self._discovery_config = discovery_config
        self._discovery_service = get_model_discovery_service()
        self._orchestrator = ModelOrchestratorService(
            {
                "models_root": str(self.models_root),
                "registry_path": str(
                    base_config.get("registry_path")
                    or orchestrator_config.get("registry_path")
                    or (self.models_root / "llm_registry.json")
                ),
                "max_concurrent_downloads": int(
                    base_config.get("max_concurrent_downloads")
                    or orchestrator_config.get("max_concurrent_downloads")
                    or 2
                ),
                "enable_license_tracking": bool(
                    base_config.get("enable_license_tracking")
                    if "enable_license_tracking" in base_config
                    else orchestrator_config.get("enable_license_tracking", True)
                ),
            }
        )

        self._lock = asyncio.Lock()
        self._jobs: dict[str, ModelDownloadJob] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._policy = ModelDownloadPolicy(
            max_concurrent_downloads=int(
                base_config.get("max_concurrent_downloads")
                or orchestrator_config.get("max_concurrent_downloads")
                or 2
            )
        )
        self._channels = self._build_channels()
        self._load_state()

    @staticmethod
    def _resolve_root(value: Any) -> Path:
        path = Path(str(value or "models"))
        if not path.is_absolute():
            path = Path.cwd() / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _build_channels(self) -> dict[str, ModelDownloadChannel]:
        return {
            "core_runtime_transformers": ModelDownloadChannel(
                id="core_runtime_transformers",
                label="Transformers / vLLM",
                group="core_runtime",
                storage_key="transformers",
                description="General text-generation models, runtime-compatible with Transformers and vLLM.",
                model_families=("transformers", "causal-lm"),
                modalities=("text",),
            ),
            "core_embeddings": ModelDownloadChannel(
                id="core_embeddings",
                label="Embeddings",
                group="core_runtime",
                storage_key="embeddings",
                description="Embedding models and vector encoders.",
                model_families=("sentence-transformers", "embeddings"),
                modalities=("text",),
            ),
            "core_rerankers": ModelDownloadChannel(
                id="core_rerankers",
                label="Rerankers",
                group="core_runtime",
                storage_key="rerankers",
                description="Cross-encoders and ranking models.",
                model_families=("reranker", "cross-encoder"),
                modalities=("text",),
            ),
            "core_onnx": ModelDownloadChannel(
                id="core_onnx",
                label="ONNX",
                group="core_runtime",
                storage_key="onnx",
                description="ONNX-exported models and edge-compatible artifacts.",
                model_families=("onnx",),
                modalities=("text", "vision", "audio"),
            ),
            "core_gguf_external": ModelDownloadChannel(
                id="core_gguf_external",
                label="GGUF External Only",
                group="core_runtime",
                storage_key="local-gguf",
                description="External GGUF snapshots for local inference backends.",
                model_families=("gguf",),
                modalities=("text", "multimodal"),
            ),
            "plugin_image": ModelDownloadChannel(
                id="plugin_image",
                label="Image Generation",
                group="plugin",
                storage_key="diffusers",
                description="Diffusers, SD, FLUX, and other image generation stacks.",
                model_families=("diffusers", "stable-diffusion", "flux"),
                modalities=("image",),
            ),
            "plugin_audio": ModelDownloadChannel(
                id="plugin_audio",
                label="Audio",
                group="plugin",
                storage_key="audio",
                description="Speech-to-text and text-to-speech models.",
                model_families=("audio", "asr", "tts"),
                modalities=("audio",),
            ),
            "plugin_vision": ModelDownloadChannel(
                id="plugin_vision",
                label="Vision / OCR",
                group="plugin",
                storage_key="vision",
                description="Vision encoders, OCR, document understanding, and multimodal helpers.",
                model_families=("vision", "ocr", "vlm"),
                modalities=("vision", "multimodal"),
            ),
            "plugin_private": ModelDownloadChannel(
                id="plugin_private",
                label="Plugin Private Models",
                group="plugin",
                storage_key="plugins/private",
                description="Plugin-owned private artifacts staged under core policy.",
                model_families=("private",),
                modalities=("text", "image", "audio", "vision"),
                admin_only=True,
            ),
        }

    def _load_state(self) -> None:
        if not self.state_path.exists():
            self._persist_state_sync()
            return

        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - best effort recoverability
            logger.warning("Failed to load model download control state: %s", exc)
            self._persist_state_sync()
            return

        policy_payload = raw.get("policy") or {}
        try:
            self._policy = replace(
                self._policy,
                **{k: v for k, v in policy_payload.items() if hasattr(self._policy, k)}
            )
        except Exception as exc:  # pragma: no cover - invalid config fallback
            logger.warning("Invalid model download policy payload ignored: %s", exc)

        self._jobs.clear()
        for job_payload in raw.get("jobs") or []:
            try:
                if "storage_key" not in job_payload and "library_override" in job_payload:
                    job_payload = dict(job_payload)
                    job_payload["storage_key"] = job_payload.pop("library_override")
                job = ModelDownloadJob(**job_payload)
                self._jobs[job.job_id] = job
            except Exception as exc:  # pragma: no cover - ignore corrupt jobs
                logger.debug("Skipping corrupt download job payload: %s", exc)

    def _persist_state_sync(self) -> None:
        self.runtime_registry_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "updated_at": _utc_now(),
            "policy": self._policy.to_dict(),
            "jobs": [job.to_dict() for job in self._jobs.values()],
        }
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")
        tmp.replace(self.state_path)

    async def _persist_state(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._persist_state_sync)

    def _channel_locked(self, channel: ModelDownloadChannel) -> bool:
        if not self._policy.master_enabled:
            return True
        if channel.group == "core_runtime" and not self._policy.core_runtime_enabled:
            return True
        if channel.group == "plugin" and not self._policy.plugin_channels_enabled:
            return True
        if channel.id == "plugin_image" and not self._policy.image_channels_enabled:
            return True
        if channel.id == "plugin_audio" and not self._policy.audio_channels_enabled:
            return True
        if channel.id == "plugin_vision" and not self._policy.vision_channels_enabled:
            return True
        if channel.id == "core_gguf_external" and not self._policy.gguf_external_enabled:
            return True
        return False

    def _channel_payloads(self) -> list[dict[str, Any]]:
        return [
            channel.to_dict(locked_by_master=self._channel_locked(channel))
            for channel in self._channels.values()
        ]

    def _resolve_channel(self, channel_id: Optional[str], metadata: Optional[Mapping[str, Any]] = None) -> ModelDownloadChannel:
        if channel_id and channel_id in self._channels:
            return self._channels[channel_id]
        return self._infer_channel(metadata or {})

    def _infer_channel(self, metadata: Mapping[str, Any]) -> ModelDownloadChannel:
        source_family = str(metadata.get("library") or metadata.get("library_name") or "").lower()
        tags = {str(tag).lower() for tag in (metadata.get("tags") or []) if str(tag).strip()}
        model_format = str(metadata.get("model_format") or "").lower()
        capabilities = {str(cap).lower() for cap in (metadata.get("capabilities") or []) if str(cap).strip()}

        if model_format == "gguf" or "gguf" in tags:
            return self._channels["core_gguf_external"]
        if source_family in {"diffusers", "stable-diffusion", "flux"} or {"image-generation", "text-to-image"} & tags:
            return self._channels["plugin_image"]
        if {"asr", "speech-to-text", "text-to-speech", "tts", "audio"} & tags or "audio" in capabilities:
            return self._channels["plugin_audio"]
        if {"ocr", "vision", "vlm", "image-to-text", "document-question-answering"} & tags or "vlm_helper" in capabilities:
            return self._channels["plugin_vision"]
        if {"reranker", "cross-encoder"} & tags or "reranking" in capabilities:
            return self._channels["core_rerankers"]
        if {"embedding", "sentence-transformer", "sentence-transformers"} & tags or "embedding" in capabilities:
            return self._channels["core_embeddings"]
        if model_format == "onnx" or "onnx" in tags or "classification" in capabilities:
            return self._channels["core_onnx"]
        return self._channels["core_runtime_transformers"]

    def _build_install_path(self, channel: ModelDownloadChannel, model_id: str, revision: Optional[str]) -> Path:
        owner, repo = model_id.split("/", 1)
        revision_name = revision or "main"
        return self.models_root / channel.storage_key / f"{owner}--{repo}" / revision_name

    def _job_payload(self, job: ModelDownloadJob) -> dict[str, Any]:
        payload = job.to_dict()
        payload["channel"] = self._channels.get(job.channel_id).to_dict(
            locked_by_master=self._channel_locked(self._channels[job.channel_id])
        ) if job.channel_id in self._channels else None
        return payload

    def _get_job(self, job_id: str) -> Optional[ModelDownloadJob]:
        return self._jobs.get(job_id)

    async def get_policy(self) -> dict[str, Any]:
        return self._policy.to_dict()

    async def update_policy(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        async with self._lock:
            updates = {
                key: payload[key]
                for key in self._policy.to_dict().keys()
                if key in payload
            }
            self._policy = replace(self._policy, **updates)
            await self._persist_state()
            return self._policy.to_dict()

    async def get_channels(self) -> dict[str, Any]:
        return {
            "policy": self._policy.to_dict(),
            "channels": self._channel_payloads(),
        }

    def list_jobs(self, status: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        jobs = list(self._jobs.values())
        if status:
            jobs = [job for job in jobs if job.status == status]
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return [self._job_payload(job) for job in jobs[:limit]]

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        job = self._get_job(job_id)
        return self._job_payload(job) if job else None

    async def validate_download(
        self,
        *,
        model_id: str,
        revision: Optional[str] = None,
        channel_id: Optional[str] = None,
        trust_remote_code: bool = False,
        accept_license: bool = False,
        include_patterns: Optional[Iterable[str]] = None,
        exclude_patterns: Optional[Iterable[str]] = None,
    ) -> ModelDownloadValidation:
        model_id = str(model_id or "").strip()
        if "/" not in model_id:
            raise ModelOrchestratorError(E_INVALID, "model_id must use owner/repo form", {"model_id": model_id})

        channel = self._channels.get(channel_id or "") if channel_id else None
        metadata: dict[str, Any] = {}
        warnings: list[str] = []
        blocking: list[str] = []

        if channel is None:
            try:
                info = await self._orchestrator.get_model_info(model_id, revision)
                metadata = {
                    "storage_key": info.storage_key,
                    "tags": info.tags,
                    "license": info.license,
                    "description": info.description,
                }
                channel = self._infer_channel(metadata | {"model_id": model_id})
            except Exception as exc:
                warnings.append(f"Remote model metadata unavailable: {exc}")
                channel = self._infer_channel({"model_id": model_id})

        if self._policy.block_new_downloads:
            blocking.append("New downloads are blocked by policy")
        if not self._policy.master_enabled:
            blocking.append("Master downloads switch is off")
        if self._channel_locked(channel):
            blocking.append(f"Channel {channel.label} is disabled by policy")
        if channel.admin_only:
            warnings.append("Channel is admin-only")
        if trust_remote_code and not self._policy.trust_remote_code:
            blocking.append("trust_remote_code is disabled by policy")
        if include_patterns and exclude_patterns:
            warnings.append("Both include and exclude patterns are set; include rules win in the executor")

        license_required = bool(metadata.get("license")) if self._policy.require_license_acceptance else False
        if license_required and not accept_license:
            blocking.append("License acceptance is required for this model")

        install_path = self._build_install_path(channel, model_id, revision)
        detected_runtime = "local_gguf" if channel.id == "core_gguf_external" else (
            "transformers_direct" if channel.id in {"core_embeddings", "core_rerankers", "core_onnx"} else "vllm"
        )
        detected_modality = next(iter(channel.modalities), "text")

        return ModelDownloadValidation(
            allowed=not blocking,
            channel_id=channel.id,
            model_id=model_id,
            revision=revision,
            storage_key=channel.storage_key,
            install_path=str(install_path),
            detected_runtime=detected_runtime,
            detected_modality=detected_modality,
            warnings=tuple(warnings),
            blocking_reasons=tuple(blocking),
            license_required=license_required,
            trust_remote_code_allowed=self._policy.trust_remote_code,
            metadata=metadata,
        )

    async def start_download(self, request: Mapping[str, Any], user: Mapping[str, Any]) -> dict[str, Any]:
        if not self._policy.master_enabled or self._policy.block_new_downloads:
            raise ModelOrchestratorError(
                E_PERM,
                "Downloads are blocked by policy",
                {"master_enabled": self._policy.master_enabled, "block_new_downloads": self._policy.block_new_downloads},
            )

        model_id = str(request.get("model_id") or "").strip()
        revision = request.get("revision")
        channel_id = request.get("channel_id")
        trust_remote_code = bool(request.get("trust_remote_code", False))
        accept_license = bool(request.get("accept_license", False))

        validation = await self.validate_download(
            model_id=model_id,
            revision=revision,
            channel_id=channel_id,
            trust_remote_code=trust_remote_code,
            accept_license=accept_license,
            include_patterns=request.get("include_patterns"),
            exclude_patterns=request.get("exclude_patterns"),
        )
        if validation.blocking_reasons:
            raise ModelOrchestratorError(
                E_LICENSE if validation.license_required else E_PERM,
                "; ".join(validation.blocking_reasons),
                validation.to_dict(),
            )

        job_id = f"mdl-{int(time.time() * 1000)}-{os.getpid()}"
        job = ModelDownloadJob(
            job_id=job_id,
            model_id=model_id,
            revision=revision,
            channel_id=validation.channel_id,
            storage_key=validation.storage_key,
            requested_by=str(user.get("user_id") or user.get("username") or "unknown"),
            trust_remote_code=trust_remote_code,
            license_accepted=accept_license,
            include_patterns=list(request.get("include_patterns") or []) or None,
            exclude_patterns=list(request.get("exclude_patterns") or []) or None,
            pin=bool(request.get("pin", False)),
            force_redownload=bool(request.get("force_redownload", False)),
            detected_runtime=validation.detected_runtime,
            detected_modality=validation.detected_modality,
            install_path=validation.install_path,
            message="Queued for download",
        )

        async with self._lock:
            self._jobs[job_id] = job
            await self._persist_state()

        self._tasks[job_id] = asyncio.create_task(self._run_download_job(job_id))
        return self._job_payload(job)

    async def _run_download_job(self, job_id: str) -> None:
        try:
            while True:
                async with self._lock:
                    job = self._jobs.get(job_id)
                    if job is None:
                        return
                    if job.cancel_requested:
                        job.status = "cancelled"
                        job.message = "Cancelled before execution"
                        job.updated_at = _utc_now()
                        await self._persist_state()
                        return
                    if self._policy.pause_active_downloads:
                        job.status = "paused"
                        job.message = "Paused by policy"
                        job.updated_at = _utc_now()
                        await self._persist_state()
                        return
                    running = len([candidate for candidate in self._jobs.values() if candidate.status == "running"])
                    if running < self._policy.max_concurrent_downloads:
                        job.status = "running"
                        job.message = "Downloading"
                        job.updated_at = _utc_now()
                        await self._persist_state()
                        break
                await asyncio.sleep(0.25)

            async with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                request = DownloadRequest(
                    model_id=job.model_id,
                    revision=job.revision,
                    include_patterns=job.include_patterns,
                    exclude_patterns=job.exclude_patterns,
                    pin=job.pin,
                    force_redownload=job.force_redownload,
                    storage_key=job.storage_key,
                )

            result = await self._orchestrator.download_model(request)

            async with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.message = "Cancelled after executor completed"
                    job.result = None
                    job.updated_at = _utc_now()
                elif result.status == "success":
                    job.status = "completed"
                    job.progress = 1.0
                    job.message = "Download completed"
                    job.result = {
                        "model_id": result.model_id,
                        "install_path": result.install_path,
                        "total_size": result.total_size,
                        "files_downloaded": result.files_downloaded,
                        "duration_seconds": result.duration_seconds,
                        "status": result.status,
                    }
                    job.install_path = result.install_path
                    job.updated_at = _utc_now()
                else:
                    job.status = "failed"
                    job.error = result.error_message or "Download failed"
                    job.message = "Download failed"
                    job.updated_at = _utc_now()
                await self._persist_state()

            try:
                await self._discovery_service.refresh_model_discovery()
            except Exception as exc:  # pragma: no cover - refresh is best-effort
                logger.debug("Model discovery refresh failed after download: %s", exc)
        except ModelOrchestratorError as exc:
            async with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.status = "failed"
                job.error = f"{exc.code}: {exc.message}"
                job.message = "Download failed"
                job.updated_at = _utc_now()
                await self._persist_state()
        except Exception as exc:  # pragma: no cover - unexpected executor failure
            async with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                job.status = "failed"
                job.error = str(exc)
                job.message = "Download failed"
                job.updated_at = _utc_now()
                await self._persist_state()
        finally:
            self._tasks.pop(job_id, None)

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ModelOrchestratorError(E_INVALID, "Job not found", {"job_id": job_id})
            if job.status in {"completed", "failed", "cancelled"}:
                raise ModelOrchestratorError(E_PERM, "Job cannot be cancelled", {"job_id": job_id, "status": job.status})
            job.cancel_requested = True
            job.status = "cancelled"
            job.message = "Cancelled by user"
            job.updated_at = _utc_now()
            await self._persist_state()
            return self._job_payload(job)

    async def pause_job(self, job_id: str) -> dict[str, Any]:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ModelOrchestratorError(E_INVALID, "Job not found", {"job_id": job_id})
            if job.status in {"completed", "failed", "cancelled"}:
                raise ModelOrchestratorError(E_PERM, "Job cannot be paused", {"job_id": job_id, "status": job.status})
            job.pause_requested = True
            if job.status == "queued":
                job.status = "paused"
                job.message = "Paused before execution"
            elif job.status == "running":
                job.status = "pause_requested"
                job.message = "Pause requested; running downloads are best-effort only"
            else:
                job.message = "Pause requested"
            job.updated_at = _utc_now()
            await self._persist_state()
            return self._job_payload(job)

    async def resume_job(self, job_id: str) -> dict[str, Any]:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ModelOrchestratorError(E_INVALID, "Job not found", {"job_id": job_id})
            if job.status not in {"paused", "pause_requested"}:
                raise ModelOrchestratorError(E_PERM, "Job cannot be resumed", {"job_id": job_id, "status": job.status})
            job.pause_requested = False
            job.status = "queued"
            job.message = "Resumed and waiting for execution slot"
            job.updated_at = _utc_now()
            await self._persist_state()
            return self._job_payload(job)

    async def get_installed_models(self, force_refresh: bool = False) -> dict[str, Any]:
        models = await self._discovery_service.discover_all_models(force_refresh=force_refresh)
        return {
            "models": [model.to_dict() for model in models],
            "total": len(models),
            "statistics": self._discovery_service.get_discovery_statistics(),
        }

    async def get_discovery_snapshot(self, force_refresh: bool = False) -> dict[str, Any]:
        if force_refresh:
            await self._discovery_service.refresh_model_discovery()
        return {
            "progress": asdict(self._discovery_service.get_discovery_progress()),
            "statistics": self._discovery_service.get_discovery_statistics(),
        }

    async def cleanup_finished_jobs(self, max_age_seconds: int = 86400) -> int:
        cutoff = time.time() - max_age_seconds
        async with self._lock:
            removable = [
                job_id
                for job_id, job in self._jobs.items()
                if job.status in {"completed", "failed", "cancelled"} and datetime.fromisoformat(job.updated_at).timestamp() < cutoff
            ]
            for job_id in removable:
                self._jobs.pop(job_id, None)
            if removable:
                await self._persist_state()
            return len(removable)


_MODEL_DOWNLOAD_CONTROL_SERVICE: Optional[ModelDownloadControlService] = None


def get_model_download_control_service() -> ModelDownloadControlService:
    global _MODEL_DOWNLOAD_CONTROL_SERVICE
    if _MODEL_DOWNLOAD_CONTROL_SERVICE is None:
        _MODEL_DOWNLOAD_CONTROL_SERVICE = ModelDownloadControlService()
    return _MODEL_DOWNLOAD_CONTROL_SERVICE


def initialize_model_download_control_service(
    config: Optional[Dict[str, Any]] = None,
) -> ModelDownloadControlService:
    global _MODEL_DOWNLOAD_CONTROL_SERVICE
    _MODEL_DOWNLOAD_CONTROL_SERVICE = ModelDownloadControlService(config)
    return _MODEL_DOWNLOAD_CONTROL_SERVICE


__all__ = [
    "ModelDownloadPolicy",
    "ModelDownloadChannel",
    "ModelDownloadJob",
    "ModelDownloadValidation",
    "ModelDownloadControlService",
    "get_model_download_control_service",
    "initialize_model_download_control_service",
]


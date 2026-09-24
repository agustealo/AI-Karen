from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ai_karen_engine.config.config_asset_loaders import load_model_runtime_discovery_config
from ai_karen_engine.config.model_download import (
    ModelDownloadWorkerSettings,
    load_model_download_worker_settings,
)
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    DownloadRequest,
    E_INVALID,
    E_LICENSE,
    E_PERM,
    ModelOrchestratorError,
    ModelOrchestratorService,
)
from ai_karen_engine.core.model_runtime.model_discovery_service import get_model_discovery_service
from ai_karen_engine.persistence.repositories.model_download_repository import (
    ModelDownloadRepository,
)

logger = get_logger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_orchestrator_settings() -> dict[str, Any]:
    settings_path = Path("config_assets/settings.json")
    if not settings_path.exists():
        return {}
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - best effort config recovery
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
    """Public model-download job contract.

    Durable lifecycle metadata such as attempts and leases intentionally stays
    repository-internal so the existing HTTP schema remains stable.
    """

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
        return asdict(self)


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
    """Model-download policy and execution authority over durable job truth."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        repository: Optional[ModelDownloadRepository] = None,
        worker_settings: Optional[ModelDownloadWorkerSettings] = None,
    ):
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
        self.legacy_state_path = self.runtime_registry_root / "model_download_control.json"
        self.policy_path = self.runtime_registry_root / "model_download_policy.json"
        self.legacy_archive_path = self.runtime_registry_root / "model_download_control.json.migrated"

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
        self._repository = repository or ModelDownloadRepository()
        self._worker_settings = worker_settings or load_model_download_worker_settings()
        self._policy_lock = asyncio.Lock()
        self._initialize_lock = asyncio.Lock()
        self._initialized = False
        self._policy = ModelDownloadPolicy(
            max_concurrent_downloads=int(
                base_config.get("max_concurrent_downloads")
                or orchestrator_config.get("max_concurrent_downloads")
                or self._worker_settings.global_concurrency_default
            )
        )
        self._channels = self._build_channels()
        self._load_policy_state()

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

    def _load_policy_state(self) -> None:
        source = self.policy_path if self.policy_path.exists() else self.legacy_state_path
        if not source.exists():
            self._persist_policy_sync()
            return
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
            policy_payload = raw.get("policy") if isinstance(raw.get("policy"), dict) else raw
            updates = {
                key: value
                for key, value in dict(policy_payload or {}).items()
                if key in self._policy.to_dict()
            }
            self._policy = replace(self._policy, **updates)
        except Exception as exc:  # pragma: no cover - recovery path
            logger.warning("Invalid model download policy state ignored: %s", exc)
        if not self.policy_path.exists():
            self._persist_policy_sync()

    def _persist_policy_sync(self, policy: Optional[ModelDownloadPolicy] = None) -> None:
        effective = policy or self._policy
        self.runtime_registry_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 2,
            "updated_at": _utc_now(),
            "policy": effective.to_dict(),
        }
        temp = self.policy_path.with_suffix(self.policy_path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.policy_path)

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            global_limit = await self._repository.initialize_global_concurrency_limit(
                self._policy.max_concurrent_downloads
            )
            if global_limit != self._policy.max_concurrent_downloads:
                self._policy = replace(
                    self._policy,
                    max_concurrent_downloads=global_limit,
                )
                await asyncio.to_thread(self._persist_policy_sync)

            if self.legacy_state_path.exists():
                try:
                    raw = json.loads(self.legacy_state_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise RuntimeError("Legacy model download state is unreadable; refusing silent loss") from exc
                jobs = raw.get("jobs") or []
                if not isinstance(jobs, list):
                    raise RuntimeError("Legacy model download jobs payload is invalid")
                imported = await self._repository.import_legacy_jobs(
                    [item for item in jobs if isinstance(item, Mapping)],
                    max_attempts=self._worker_settings.max_attempts,
                )
                await asyncio.to_thread(self._archive_legacy_state)
                logger.info(
                    "model_download_legacy_cutover_complete imported=%s source_jobs=%s",
                    imported,
                    len(jobs),
                )
            self._initialized = True

    def _archive_legacy_state(self) -> None:
        if not self.legacy_state_path.exists():
            return
        self.runtime_registry_root.mkdir(parents=True, exist_ok=True)
        os.replace(self.legacy_state_path, self.legacy_archive_path)

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
        return self.models_root / channel.storage_key / f"{owner}--{repo}" / (revision or "main")

    def _job_payload(self, row: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        for key in ("created_at", "updated_at"):
            value = payload.get(key)
            if isinstance(value, datetime):
                payload[key] = value.isoformat()
        channel = self._channels.get(str(payload.get("channel_id") or ""))
        payload["channel"] = channel.to_dict(
            locked_by_master=self._channel_locked(channel)
        ) if channel is not None else None
        return payload

    async def get_policy(self) -> dict[str, Any]:
        await self.initialize()
        payload = self._policy.to_dict()
        payload["max_concurrent_downloads"] = await self.get_global_concurrency_limit()
        return payload

    async def get_global_concurrency_limit(self) -> int:
        await self.initialize()
        return await self._repository.get_global_concurrency_limit()

    async def update_policy(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        await self.initialize()
        async with self._policy_lock:
            updates = {key: payload[key] for key in self._policy.to_dict() if key in payload}
            current_limit = await self._repository.get_global_concurrency_limit()
            candidate = replace(
                self._policy,
                **updates,
            )
            if "max_concurrent_downloads" not in updates:
                candidate = replace(candidate, max_concurrent_downloads=current_limit)
            if candidate.max_concurrent_downloads < 1 or candidate.max_concurrent_downloads > 8:
                raise ModelOrchestratorError(E_INVALID, "max_concurrent_downloads must be between 1 and 8")

            limit_changed = candidate.max_concurrent_downloads != current_limit
            if limit_changed:
                await self._repository.set_global_concurrency_limit(
                    candidate.max_concurrent_downloads
                )
            try:
                await asyncio.to_thread(self._persist_policy_sync, candidate)
            except BaseException:
                if limit_changed:
                    try:
                        await self._repository.set_global_concurrency_limit(current_limit)
                    except Exception:
                        logger.exception(
                            "model_download_policy_concurrency_rollback_failed old_limit=%s new_limit=%s",
                            current_limit,
                            candidate.max_concurrent_downloads,
                        )
                raise

            self._policy = candidate
            return self._policy.to_dict()

    async def get_channels(self) -> dict[str, Any]:
        return {
            "policy": await self.get_policy(),
            "channels": self._channel_payloads(),
        }

    async def list_jobs(self, status: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        await self.initialize()
        rows = await self._repository.list_jobs(status=status, limit=limit)
        return [self._job_payload(row) for row in rows]

    async def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        await self.initialize()
        row = await self._repository.get_job(job_id)
        return self._job_payload(row) if row is not None else None

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
        await self.initialize()
        if not self._policy.master_enabled or self._policy.block_new_downloads:
            raise ModelOrchestratorError(
                E_PERM,
                "Downloads are blocked by policy",
                {
                    "master_enabled": self._policy.master_enabled,
                    "block_new_downloads": self._policy.block_new_downloads,
                },
            )
        model_id = str(request.get("model_id") or "").strip()
        revision = request.get("revision")
        validation = await self.validate_download(
            model_id=model_id,
            revision=revision,
            channel_id=request.get("channel_id"),
            trust_remote_code=bool(request.get("trust_remote_code", False)),
            accept_license=bool(request.get("accept_license", False)),
            include_patterns=request.get("include_patterns"),
            exclude_patterns=request.get("exclude_patterns"),
        )
        if validation.blocking_reasons:
            raise ModelOrchestratorError(
                E_LICENSE if validation.license_required else E_PERM,
                "; ".join(validation.blocking_reasons),
                validation.to_dict(),
            )
        job = ModelDownloadJob(
            job_id=f"mdl-{uuid.uuid4()}",
            model_id=model_id,
            revision=revision,
            channel_id=validation.channel_id,
            storage_key=validation.storage_key,
            requested_by=str(user.get("user_id") or user.get("username") or "unknown"),
            trust_remote_code=bool(request.get("trust_remote_code", False)),
            license_accepted=bool(request.get("accept_license", False)),
            include_patterns=list(request.get("include_patterns") or []) or None,
            exclude_patterns=list(request.get("exclude_patterns") or []) or None,
            pin=bool(request.get("pin", False)),
            force_redownload=bool(request.get("force_redownload", False)),
            detected_runtime=validation.detected_runtime,
            detected_modality=validation.detected_modality,
            install_path=validation.install_path,
            message="Queued for download",
        )
        row = await self._repository.create_job(
            job.to_dict(),
            max_attempts=self._worker_settings.max_attempts,
        )
        logger.info("model_download_job_queued job_id=%s model_id=%s", job.job_id, model_id)
        return self._job_payload(row)

    async def _require_mutable_job(self, job_id: str, action: str) -> dict[str, Any]:
        row = await self._repository.get_job(job_id)
        if row is None:
            raise ModelOrchestratorError(E_INVALID, "Job not found", {"job_id": job_id})
        raise ModelOrchestratorError(
            E_PERM,
            f"Job cannot be {action}",
            {"job_id": job_id, "status": row.get("status")},
        )

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        await self.initialize()
        row = await self._repository.cancel_job(job_id)
        return self._job_payload(row) if row is not None else await self._require_mutable_job(job_id, "cancelled")

    async def pause_job(self, job_id: str) -> dict[str, Any]:
        await self.initialize()
        row = await self._repository.pause_job(job_id)
        return self._job_payload(row) if row is not None else await self._require_mutable_job(job_id, "paused")

    async def resume_job(self, job_id: str) -> dict[str, Any]:
        await self.initialize()
        row = await self._repository.resume_job(job_id)
        return self._job_payload(row) if row is not None else await self._require_mutable_job(job_id, "resumed")

    async def claim_next_job(self, worker_id: str) -> Optional[dict[str, Any]]:
        await self.initialize()
        if (
            not self._policy.master_enabled
            or self._policy.block_new_downloads
            or self._policy.pause_active_downloads
        ):
            return None
        return await self._repository.claim_next(
            worker_id=worker_id,
            lease_seconds=self._worker_settings.lease_seconds,
            retry_base_seconds=self._worker_settings.retry_base_seconds,
        )

    async def heartbeat_claim(self, job_id: str, lease_token: str) -> bool:
        return await self._repository.heartbeat(
            job_id=job_id,
            lease_token=lease_token,
            lease_seconds=self._worker_settings.lease_seconds,
        )

    async def release_claim_for_shutdown(self, job_id: str, lease_token: str) -> None:
        await self._repository.release_for_shutdown(
            job_id=job_id,
            lease_token=lease_token,
            retry_delay_seconds=self._worker_settings.retry_base_seconds,
        )

    async def fail_claim(self, job_id: str, lease_token: str, error: BaseException) -> None:
        await self._repository.fail_or_retry(
            job_id=job_id,
            lease_token=lease_token,
            error=f"{type(error).__name__}: {error}",
            retry_base_seconds=self._worker_settings.retry_base_seconds,
        )

    async def execute_claimed_job(self, claim: Mapping[str, Any]) -> None:
        job_id = str(claim["job_id"])
        lease_token = str(claim["lease_token"])
        stage_root = self.models_root / ".staging" / "model-downloads" / job_id / lease_token
        stage_models_root = stage_root / "models"
        stage_registry = stage_root / "llm_registry.json"
        await asyncio.to_thread(stage_models_root.mkdir, parents=True, exist_ok=True)

        staging_orchestrator = ModelOrchestratorService(
            {
                "models_root": str(stage_models_root),
                "registry_path": str(stage_registry),
                "max_concurrent_downloads": 1,
                "enable_license_tracking": True,
            }
        )
        request = DownloadRequest(
            model_id=str(claim["model_id"]),
            revision=claim.get("revision"),
            include_patterns=claim.get("include_patterns"),
            exclude_patterns=claim.get("exclude_patterns"),
            pin=bool(claim.get("pin", False)),
            force_redownload=bool(claim.get("force_redownload", False)),
            storage_key=claim.get("storage_key"),
        )
        started = time.perf_counter()
        try:
            result = await staging_orchestrator.download_model(request)
        except asyncio.CancelledError:
            logger.warning("model_download_execution_cancelled job_id=%s", job_id)
            raise
        except Exception:
            await asyncio.to_thread(self._safe_remove_tree, stage_root)
            raise

        if not await self._repository.lease_is_valid(job_id=job_id, lease_token=lease_token):
            await asyncio.to_thread(self._safe_remove_tree, stage_root)
            logger.warning("model_download_promotion_fenced job_id=%s", job_id)
            return

        staged_path = Path(result.install_path)
        final_path = Path(str(claim.get("install_path") or ""))
        if not str(claim.get("install_path") or "").strip():
            channel = self._channels[str(claim["channel_id"])]
            final_path = self._build_install_path(channel, str(claim["model_id"]), claim.get("revision"))

        await asyncio.to_thread(
            self._promote_staged_directory,
            staged_path,
            final_path,
            lease_token,
        )
        result_payload = {
            "model_id": result.model_id,
            "install_path": str(final_path),
            "total_size": result.total_size,
            "files_downloaded": result.files_downloaded,
            "duration_seconds": max(result.duration_seconds, time.perf_counter() - started),
            "status": result.status,
        }

        await self._register_promoted_model(
            staging_orchestrator=staging_orchestrator,
            model_id=str(claim["model_id"]),
            final_path=final_path,
        )
        completed = await self._repository.complete_job(
            job_id=job_id,
            lease_token=lease_token,
            result_payload=result_payload,
            install_path=str(final_path),
        )
        if completed is None:
            logger.error("model_download_completion_fence_rejected job_id=%s", job_id)
            return

        await asyncio.to_thread(self._safe_remove_tree, stage_root)
        try:
            await self._discovery_service.refresh_model_discovery()
        except Exception as exc:  # pragma: no cover - cache refresh only
            logger.warning("model_download_discovery_refresh_failed job_id=%s error=%s", job_id, exc)
        logger.info("model_download_job_completed job_id=%s install_path=%s", job_id, final_path)

    @staticmethod
    def _safe_remove_tree(path: Path) -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _promote_staged_directory(staged_path: Path, final_path: Path, lease_token: str) -> None:
        if not staged_path.exists():
            raise RuntimeError(f"Staged model artifact is missing: {staged_path}")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if not final_path.exists():
            os.replace(staged_path, final_path)
            return

        backup = final_path.with_name(f"{final_path.name}.previous-{lease_token}")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        os.replace(final_path, backup)
        try:
            os.replace(staged_path, final_path)
        except BaseException:
            if not final_path.exists() and backup.exists():
                os.replace(backup, final_path)
            raise
        shutil.rmtree(backup, ignore_errors=True)

    async def _register_promoted_model(
        self,
        *,
        staging_orchestrator: ModelOrchestratorService,
        model_id: str,
        final_path: Path,
    ) -> None:
        entry = dict(staging_orchestrator._registry.get(model_id) or {})
        if not entry:
            raise RuntimeError(f"Staging registry entry missing for promoted model: {model_id}")
        entry["install_path"] = str(final_path)
        self._orchestrator._registry[model_id] = entry
        await self._orchestrator._persist_registry()

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
        await self.initialize()
        return await self._repository.cleanup_finished_jobs(max_age_seconds=max_age_seconds)


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

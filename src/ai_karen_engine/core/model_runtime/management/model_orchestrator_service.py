"""
Model Orchestrator Service.

Production-oriented model registry + download/remove workflows used by
`ai_karen_engine.api_routes.models.model_orchestrator`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


# Error codes consumed by API routes.
E_NET = "E_NET"
E_DISK = "E_DISK"
E_PERM = "E_PERM"
E_LICENSE = "E_LICENSE"
E_VERIFY = "E_VERIFY"
E_SCHEMA = "E_SCHEMA"
E_COMPAT = "E_COMPAT"
E_QUOTA = "E_QUOTA"
E_NOT_FOUND = "E_NOT_FOUND"
E_INVALID = "E_INVALID"


class ModelOrchestratorError(Exception):
    """Domain error carrying a stable error code and optional details."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")


@dataclass
class ModelSummary:
    model_id: str
    last_modified: Optional[datetime] = None
    likes: Optional[int] = None
    downloads: Optional[int] = None
    storage_key: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    total_size: Optional[int] = None
    description: Optional[str] = None


@dataclass
class ModelInfo:
    model_id: str
    owner: str
    repository: str
    storage_key: str
    files: List[Dict[str, Union[str, int]]] = field(default_factory=list)
    total_size: int = 0
    last_modified: Optional[datetime] = None
    downloads: Optional[int] = None
    likes: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    license: Optional[str] = None
    description: Optional[str] = None
    revision: Optional[str] = None


@dataclass
class DownloadRequest:
    model_id: str
    revision: Optional[str] = None
    include_patterns: Optional[List[str]] = None
    exclude_patterns: Optional[List[str]] = None
    pin: bool = False
    force_redownload: bool = False
    storage_key: Optional[str] = None


@dataclass
class DownloadResult:
    model_id: str
    install_path: str
    total_size: int
    files_downloaded: int
    duration_seconds: float
    status: str
    error_message: Optional[str] = None


@dataclass
class MigrationResult:
    status: str
    migrated_count: int = 0
    errors: List[str] = field(default_factory=list)
    backup_path: Optional[str] = None


@dataclass
class EnsureResult:
    status: str
    model_id: Optional[str] = None
    message: Optional[str] = None


@dataclass
class GCResult:
    status: str
    reclaimed_bytes: int = 0
    removed_models: List[str] = field(default_factory=list)


@dataclass
class RemoveResult:
    model_id: str
    deleted_artifacts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModelOrchestratorService:
    """Model lifecycle orchestration with persisted registry."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config: Dict[str, Any] = config or {}
        self.models_root = self._resolve_models_root(Path(self.config.get("models_root", "models")))
        self.registry_path = self._resolve_registry_path(self.config.get("registry_path"))
        self._registry_lock = asyncio.Lock()
        self._registry: Dict[str, Dict[str, Any]] = self._load_registry()
        logger.info(
            "ModelOrchestratorService initialized",
            extra={
                "models_root": str(self.models_root),
                "registry_path": str(self.registry_path),
                "registry_entries": len(self._registry),
            },
        )

    def initialize(self, config: Dict[str, Any]) -> None:
        """Backwards-compatible sync initializer."""
        self.config.update(config or {})

    def _resolve_models_root(self, configured_root: Path) -> Path:
        root = configured_root if configured_root.is_absolute() else Path.cwd() / configured_root
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _resolve_registry_path(self, configured_path: Optional[str]) -> Path:
        if configured_path:
            registry = Path(configured_path)
        else:
            registry = self.models_root / "orchestrator_registry.json"
        if not registry.is_absolute():
            registry = Path.cwd() / registry
        registry.parent.mkdir(parents=True, exist_ok=True)
        return registry

    def _load_registry(self) -> Dict[str, Dict[str, Any]]:
        if not self.registry_path.exists():
            return {}
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ModelOrchestratorError(
                E_SCHEMA,
                "Failed to parse orchestrator registry",
                {"registry_path": str(self.registry_path), "error": str(exc)},
            ) from exc

        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            converted: Dict[str, Dict[str, Any]] = {}
            for entry in raw:
                model_id = entry.get("model_id") or entry.get("name")
                if model_id:
                    converted[model_id] = dict(entry)
            return converted
        return {}

    async def _persist_registry(self) -> None:
        tmp = self.registry_path.with_suffix(self.registry_path.suffix + ".tmp")
        async with self._registry_lock:
            tmp.write_text(json.dumps(self._registry, indent=2, default=self._json_default), encoding="utf-8")
            tmp.replace(self.registry_path)

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"Unserializable value: {type(value)!r}")

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    @staticmethod
    def _split_model_id(model_id: str) -> Tuple[str, str]:
        if "/" not in model_id:
            raise ModelOrchestratorError(E_INVALID, "model_id must be in owner/repo format", {"model_id": model_id})
        owner, repo = model_id.split("/", 1)
        return owner, repo

    @staticmethod
    def _walk_files(root: Path) -> Tuple[List[Dict[str, Union[str, int]]], int]:
        files: List[Dict[str, Union[str, int]]] = []
        total = 0
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            total += size
            files.append({"path": str(p.relative_to(root)), "size": size})
        return files, total

    @staticmethod
    def _hf_api_available():
        try:
            from huggingface_hub import HfApi  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _get_hf_api():
        try:
            from huggingface_hub import HfApi
        except Exception as exc:
            raise ModelOrchestratorError(
                E_COMPAT,
                "huggingface_hub is required for remote model metadata operations",
                {"missing_dependency": "huggingface_hub", "error": str(exc)},
            ) from exc
        return HfApi()

    async def list_models(
        self,
        owner: str,
        limit: int = 50,
        search: Optional[str] = None,
        sort: str = "downloads",
        direction: int = -1,
        **_: Any,
    ) -> List[ModelSummary]:
        summaries: List[ModelSummary] = []
        owner_prefix = f"{owner}/" if owner else ""

        # Source of truth for browsing is remote registry (HF API) when available.
        # Local registry entries are merged in afterward so downloaded models always appear.
        remote_seen: set[str] = set()
        try:
            api = self._get_hf_api()
            hf_sort = sort if sort in {"downloads", "likes", "last_modified"} else None
            models = await asyncio.to_thread(
                lambda: list(
                    api.list_models(
                        author=owner or None,
                        search=search or None,
                        sort=hf_sort,
                        direction=-1 if direction < 0 else 1,
                        limit=limit,
                    )
                )
            )
            for card in models:
                model_id = getattr(card, "id", None)
                if not model_id:
                    continue
                remote_seen.add(model_id)
                summaries.append(
                    ModelSummary(
                        model_id=model_id,
                        last_modified=getattr(card, "last_modified", None),
                        likes=getattr(card, "likes", None),
                        downloads=getattr(card, "downloads", None),
                        library_name=getattr(card, "library_name", None),
                        tags=list(getattr(card, "tags", []) or []),
                        total_size=None,
                        description=getattr(card, "description", None),
                    )
                )
        except ModelOrchestratorError:
            # No HF dependency: continue with local-only listing.
            logger.warning("Remote model listing unavailable; falling back to local registry")
        except Exception as exc:
            # Network/remote issues should not break local listing.
            logger.warning("Remote model listing failed; falling back to local registry: %s", exc)

        for model_id, entry in self._registry.items():
            if owner_prefix and not model_id.startswith(owner_prefix):
                continue
            if search and search.lower() not in model_id.lower():
                continue
            if model_id in remote_seen:
                continue

            summaries.append(
                ModelSummary(
                    model_id=model_id,
                    last_modified=self._parse_dt(entry.get("last_modified")),
                    likes=entry.get("likes"),
                    downloads=entry.get("downloads"),
                        storage_key=entry.get("storage_key"),
                    tags=list(entry.get("tags") or []),
                    total_size=int(entry.get("total_size") or 0),
                    description=entry.get("description"),
                )
            )

        reverse = direction < 0
        if sort == "likes":
            keyf = lambda m: m.likes or 0
        elif sort == "modified":
            keyf = lambda m: m.last_modified or datetime.min.replace(tzinfo=timezone.utc)
        else:
            keyf = lambda m: m.downloads or 0
        summaries.sort(key=keyf, reverse=reverse)
        return summaries[:limit]

    async def get_model_info(self, model_id: str, revision: Optional[str] = None, **_: Any) -> ModelInfo:
        owner, repo = self._split_model_id(model_id)
        entry = self._registry.get(model_id)
        if entry is not None:
            files = list(entry.get("files") or [])
            total_size = int(entry.get("total_size") or 0)
            return ModelInfo(
                model_id=model_id,
                owner=owner,
                repository=repo,
                storage_key=entry.get("storage_key", "unknown"),
                files=files,
                total_size=total_size,
                last_modified=self._parse_dt(entry.get("last_modified")),
                downloads=entry.get("downloads"),
                likes=entry.get("likes"),
                tags=list(entry.get("tags") or []),
                license=entry.get("license"),
                description=entry.get("description"),
                revision=revision or entry.get("revision"),
            )

        # If not installed locally, query remote model metadata.
        try:
            api = self._get_hf_api()
            remote = await asyncio.to_thread(
                api.model_info,
                repo_id=model_id,
                revision=revision,
            )
        except ModelOrchestratorError:
            raise ModelOrchestratorError(
                E_NOT_FOUND,
                f"Model not found in local registry and remote lookup unavailable: {model_id}",
                {"model_id": model_id},
            )
        except Exception as exc:
            raise ModelOrchestratorError(
                E_NOT_FOUND,
                f"Model not found: {model_id}",
                {"model_id": model_id, "error": str(exc)},
            ) from exc

        siblings = getattr(remote, "siblings", None) or []
        files: List[Dict[str, Union[str, int]]] = []
        total_size = 0
        for sibling in siblings:
            path = getattr(sibling, "rfilename", None)
            size = int(getattr(sibling, "size", 0) or 0)
            if not path:
                continue
            total_size += size
            files.append({"path": path, "size": size})

        return ModelInfo(
            model_id=model_id,
            owner=owner,
            repository=repo,
            storage_key=getattr(remote, "library_name", None) or "unknown",
            files=files,
            total_size=total_size,
            last_modified=getattr(remote, "last_modified", None),
            downloads=getattr(remote, "downloads", None),
            likes=getattr(remote, "likes", None),
            tags=list(getattr(remote, "tags", []) or []),
            license=getattr(remote, "cardData", {}).get("license")
            if isinstance(getattr(remote, "cardData", None), dict)
            else None,
            description=getattr(remote, "cardData", {}).get("model_description")
            if isinstance(getattr(remote, "cardData", None), dict)
            else None,
            revision=revision or getattr(remote, "sha", None),
        )

    async def download_model(self, request: Union[DownloadRequest, str], **kwargs: Any) -> DownloadResult:
        req = DownloadRequest(model_id=request, **kwargs) if isinstance(request, str) else request
        owner, repo = self._split_model_id(req.model_id)

        start = time.perf_counter()
        revision = req.revision or "main"

        storage_key = req.storage_key or "transformers"
        install_root = self.models_root / storage_key
        install_path = install_root / f"{owner}--{repo}" / revision

        try:
            install_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ModelOrchestratorError(E_DISK, "Failed to create model install directory", {"path": str(install_path), "error": str(exc)}) from exc

        try:
            # Real download path: Hugging Face snapshot
            from huggingface_hub import snapshot_download

            await asyncio.to_thread(
                snapshot_download,
                repo_id=req.model_id,
                repo_type="model",
                revision=req.revision,
                local_dir=str(install_path),
                local_dir_use_symlinks=False,
                allow_patterns=req.include_patterns,
                ignore_patterns=req.exclude_patterns,
                force_download=req.force_redownload,
            )
        except ImportError as exc:
            raise ModelOrchestratorError(
                E_COMPAT,
                "huggingface_hub is required for model download operations",
                {"missing_dependency": "huggingface_hub"},
            ) from exc
        except Exception as exc:
            raise ModelOrchestratorError(
                E_NET,
                f"Failed to download model {req.model_id}",
                {"model_id": req.model_id, "revision": req.revision, "error": str(exc)},
            ) from exc

        files, total_size = await asyncio.to_thread(self._walk_files, install_path)
        duration = time.perf_counter() - start

        self._registry[req.model_id] = {
            "model_id": req.model_id,
            "owner": owner,
            "repository": repo,
            "storage_key": storage_key,
            "revision": revision,
            "install_path": str(install_path),
            "files": files,
            "total_size": total_size,
            "pinned": bool(req.pin),
            "last_modified": datetime.now(timezone.utc).isoformat(),
            "downloads": int(self._registry.get(req.model_id, {}).get("downloads") or 0),
            "likes": self._registry.get(req.model_id, {}).get("likes"),
            "tags": list(self._registry.get(req.model_id, {}).get("tags") or []),
            "license": self._registry.get(req.model_id, {}).get("license"),
            "description": self._registry.get(req.model_id, {}).get("description"),
        }
        await self._persist_registry()

        return DownloadResult(
            model_id=req.model_id,
            install_path=str(install_path),
            total_size=total_size,
            files_downloaded=len(files),
            duration_seconds=duration,
            status="success",
            error_message=None,
        )

    async def remove_model(self, model_id: str, delete_files: bool = True, **_: Any) -> RemoveResult:
        entry = self._registry.get(model_id)
        if entry is None:
            raise ModelOrchestratorError(E_NOT_FOUND, f"Model not found in local registry: {model_id}", {"model_id": model_id})

        deleted_artifacts: List[str] = []
        warnings: List[str] = []

        install_path = entry.get("install_path")
        if delete_files and install_path:
            model_dir = Path(install_path)
            if model_dir.exists():
                try:
                    await asyncio.to_thread(shutil.rmtree, model_dir)
                    deleted_artifacts.append(str(model_dir))
                except Exception as exc:
                    warnings.append(f"Failed to delete model files at {model_dir}: {exc}")

        self._registry.pop(model_id, None)
        await self._persist_registry()

        return RemoveResult(
            model_id=model_id,
            deleted_artifacts=deleted_artifacts,
            warnings=warnings,
            metadata={"delete_files": delete_files, "removed_from_registry": True},
        )

    # Backwards compatibility for existing synchronous callers.
    def run_model(
        self,
        model_id: str,
        input_data: Dict[str, Any],
        provider: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        raise ModelOrchestratorError(
            E_COMPAT,
            "run_model is not implemented in ModelOrchestratorService; use the LLM orchestration pipeline",
            {"model_id": model_id, "provider": provider, "stream": stream, "input_keys": list(input_data.keys())},
        )

    def get_available_models(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for model_id, entry in self._registry.items():
            if provider and entry.get("storage_key") != provider:
                continue
            results.append(
                {
                    "id": model_id,
                    "provider": entry.get("storage_key"),
                    "name": model_id,
                    "revision": entry.get("revision"),
                }
            )
        return results


__all__ = [
    "ModelOrchestratorService",
    "ModelOrchestratorError",
    "ModelSummary",
    "ModelInfo",
    "DownloadRequest",
    "DownloadResult",
    "MigrationResult",
    "EnsureResult",
    "GCResult",
    "RemoveResult",
    "E_NET",
    "E_DISK",
    "E_PERM",
    "E_LICENSE",
    "E_VERIFY",
    "E_SCHEMA",
    "E_COMPAT",
    "E_QUOTA",
    "E_NOT_FOUND",
    "E_INVALID",
]

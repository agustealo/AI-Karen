from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


def write_model_registry_cache(
    models: Iterable[Mapping[str, Any]],
    discovery_config: Mapping[str, Any] | None = None,
) -> Path:
    config = discovery_config or {}
    cache_config = config.get("cache", {}) or {}
    cache_path = Path(cache_config.get("path", "models/.runtime_registry/local_models.generated.json"))
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": int(cache_config.get("schema_version", config.get("schema_version", 1))),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_roots": list(config.get("model_roots", []) or []),
        "models": list(models),
    }
    cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return cache_path


def sync_model_registry_cache(
    registry_path: Optional[Path] = None,
    *,
    force_refresh: bool = True,
    emit_events: bool = True,
) -> Path:
    """Discover models via the canonical ``ModelDiscoveryService`` and persist a flat
    model registry at ``KARI_MODEL_REGISTRY`` (default ``model_registry.json``).

    Canonical replacement for the retired integrations model discovery module's
    ``sync_registry``. Preserves the flat-list JSON contract consumed by
    ``services/models/discovery/model_library_service`` while sourcing model state
    exclusively from ``core/model_runtime``. Eager imports inside the body avoid a
    circular import with ``model_discovery_service`` (which imports this module).
    """
    from ai_karen_engine.core.model_runtime.model_discovery_service import (
        get_model_discovery_service,
    )
    from ai_karen_engine.core.model_runtime.model_lifecycle_events import (
        ModelLifecycleEvent,
        emit_model_lifecycle_event,
    )

    path = Path(registry_path or os.getenv("KARI_MODEL_REGISTRY", "model_registry.json"))
    path.parent.mkdir(parents=True, exist_ok=True)

    service = get_model_discovery_service()
    models = service.get_all_models(force_refresh=force_refresh)

    # Flat schema preserved for the existing ModelLibraryService reader (name/path/type/source).
    payload = [
        {
            "name": summary.name,
            "path": summary.path,
            "type": summary.model_format,
            "source": "local",
            "model_id": summary.model_id,
        }
        for summary in models
    ]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if emit_events:
        for summary in models:
            try:
                emit_model_lifecycle_event(
                    ModelLifecycleEvent.MODEL_DISCOVERED,
                    model_id=summary.model_id,
                    provider=summary.model_format,
                    runtime_engine=summary.preferred_runtime,
                )
                emit_model_lifecycle_event(
                    ModelLifecycleEvent.MODEL_AVAILABLE,
                    model_id=summary.model_id,
                    provider=summary.model_format,
                    runtime_engine=summary.preferred_runtime,
                )
            except Exception:  # pragma: no cover - lifecycle emit must never break sync
                pass

    return path


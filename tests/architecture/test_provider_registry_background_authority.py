from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = (
    ROOT / "src/ai_karen_engine/core/model_runtime/provider_registry_service.py"
)


def test_provider_registry_does_not_spawn_shadow_health_thread() -> None:
    source = REGISTRY.read_text(encoding="utf-8")

    assert "_start_health_monitoring" not in source
    assert "threading.Thread(" not in source
    assert "time.sleep(300)" not in source
    assert "get_provider_status(" in source
    assert "_cache_ttl = 60" in source

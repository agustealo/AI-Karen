from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "src" / "ai_karen_engine" / "core"
SERVICES_ROOT = CORE_ROOT / "services"


def test_duplicate_service_registry_stack_does_not_reappear() -> None:
    for filename in (
        "registry.py",
        "service_registry.py",
        "classified_service_registry.py",
        "service_classification.py",
        "service_lifecycle_manager.py",
    ):
        assert not (SERVICES_ROOT / filename).exists()


def test_service_dependencies_use_runtime_resolution_authority() -> None:
    source = (SERVICES_ROOT / "dependencies.py").read_text(encoding="utf-8")

    assert "ai_karen_engine.core.services.service_registry" not in source
    assert "ai_karen_engine.core.runtime.lazy_loading" in source
    assert "_NoopConversationMemoryService" not in source
    assert "ServiceRegistry_Dep" not in source


def test_services_package_does_not_export_registry_or_lifecycle_authority() -> None:
    source = (SERVICES_ROOT / "__init__.py").read_text(encoding="utf-8")

    assert "get_service_registry" not in source
    assert "get_classified_registry" not in source
    assert "ServiceLifecycleManager" not in source
    assert "Runtime owns live service resolution and lifecycle" in source

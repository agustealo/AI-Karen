from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "src" / "ai_karen_engine" / "core"
PLATFORM_OBS_ROOT = REPO_ROOT / "src" / "ai_karen_engine" / "platform" / "observability"


def test_platform_observability_is_canonical_implementation_owner() -> None:
    assert (PLATFORM_OBS_ROOT / "contracts.py").exists()
    assert (PLATFORM_OBS_ROOT / "context.py").exists()
    assert (PLATFORM_OBS_ROOT / "events.py").exists()
    assert (PLATFORM_OBS_ROOT / "metrics.py").exists()
    assert (PLATFORM_OBS_ROOT / "redaction.py").exists()


def test_core_observability_authority_is_retired() -> None:
    assert not (CORE_ROOT / "observability").exists()


def test_adaptive_runtime_uses_platform_observability_context() -> None:
    source = (CORE_ROOT / "adaptive" / "runtime.py").read_text(encoding="utf-8")
    assert "ai_karen_engine.core.observability" not in source
    assert "ai_karen_engine.platform.observability.context" in source


def test_core_readme_records_observability_ownership() -> None:
    readme = (CORE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "`core/observability/` was removed" in readme
    assert "platform/observability/" in readme
    assert "Core must not recreate metrics" in readme


def test_core_readme_does_not_advertise_nonexistent_operations_authority() -> None:
    readme = (CORE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "core/operations/`\nOperational support" not in readme
    assert "`core/operations/` is not a live directory" in readme

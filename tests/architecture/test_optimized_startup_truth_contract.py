from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STARTUP = ROOT / "src/ai_karen_engine/core/runtime/optimized_startup.py"


def test_optimized_startup_has_no_placeholder_initializer() -> None:
    source = STARTUP.read_text(encoding="utf-8")

    assert "Placeholder for lightweight service initialization" not in source
    assert "await asyncio.sleep(0.01)" not in source
    assert "def _init_lightweight_service" not in source


def test_application_owned_services_are_not_reported_initialized() -> None:
    source = STARTUP.read_text(encoding="utf-8")

    assert '"status": "application_owned"' in source
    assert '"status": "lazy_registry_owned"' in source

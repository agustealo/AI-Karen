from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROVIDER_RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/provider_runtime.py"


def test_optional_metrics_use_truthful_null_adapter_name() -> None:
    source = PROVIDER_RUNTIME.read_text(encoding="utf-8")

    assert "_DummyMetric" not in source
    assert "class _NullMetric:" in source


def test_provider_metadata_lookup_failure_is_not_silent() -> None:
    source = PROVIDER_RUNTIME.read_text(encoding="utf-8")

    assert "except Exception as exc:" in source
    assert '"provider model metadata lookup failed"' in source
    assert '"error_type": type(exc).__name__' in source

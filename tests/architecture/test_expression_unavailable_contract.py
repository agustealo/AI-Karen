from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DISABLED = ROOT / "src/ai_karen_engine/core/expression/engines/disabled_engine.py"
CONTRACTS = ROOT / "src/ai_karen_engine/core/expression/contracts.py"
GATEWAY = ROOT / "src/ai_karen_engine/core/expression/gateway.py"


def test_disabled_engine_never_fabricates_assistant_text() -> None:
    source = DISABLED.read_text(encoding="utf-8")

    assert "raise EngineUnavailableError" in source
    assert "text=" not in source
    assert "emergency_static" not in source
    assert 'status="disabled"' in source


def test_expression_result_allows_truthful_missing_provider() -> None:
    source = CONTRACTS.read_text(encoding="utf-8")

    assert "provider: str | None" in source


def test_gateway_has_no_static_failure_output_compatibility() -> None:
    source = GATEWAY.read_text(encoding="utf-8")

    assert '"emergency_static"' not in source
    assert '"system_failure"' not in source
    assert 'result.response_source != "model_unavailable"' in source

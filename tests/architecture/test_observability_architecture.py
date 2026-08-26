from __future__ import annotations

import ast
import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ai_karen_engine"
OBS_PATH = SRC_ROOT / "platform" / "observability"


def _observability_sources() -> list[Path]:
    return [p for p in OBS_PATH.rglob("*.py") if "__pycache__" not in str(p)]


class TestObservabilityArchitecture:
    """OBS-119: permanent architecture invariants for the observability layer."""

    def test_no_print_in_observability_package(self) -> None:
        for path in _observability_sources():
            content = path.read_text(encoding="utf-8")
            assert not re.search(r"\bprint\s*\(", content), (
                f"print() must not be used for runtime telemetry: {path}"
            )

    def test_metrics_collector_guards_high_cardinality_labels(self) -> None:
        metrics_source = (OBS_PATH / "metrics.py").read_text(encoding="utf-8")
        tree = ast.parse(metrics_source)
        names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert "MetricsCollector" in names
        assert "CardinalityError" in names

    def test_taxonomy_covers_provider_lifecycle(self) -> None:
        contracts_source = (OBS_PATH / "contracts.py").read_text(encoding="utf-8")
        for required in (
            "PROVIDER_EXECUTION_STARTED",
            "PROVIDER_EXECUTION_COMPLETED",
            "PROVIDER_EXECUTION_FAILED",
            "PROVIDER_FALLBACK",
        ):
            assert required in contracts_source, f"Missing provider event {required}"

    def test_high_cardinality_labels_defined(self) -> None:
        contracts_source = (OBS_PATH / "contracts.py").read_text(encoding="utf-8")
        for identifier in (
            "user_id",
            "request_id",
            "conversation_id",
            "url",
        ):
            assert identifier in contracts_source

    def test_diagnostics_buffer_is_bounded(self) -> None:
        buffer_source = (OBS_PATH / "diagnostics_buffer.py").read_text(encoding="utf-8")
        tree = ast.parse(buffer_source)
        names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert "BoundedDiagnosticsBuffer" in names

    def test_no_core_imports_in_platform_observability(self) -> None:
        """Platform observability must not depend on Core (CORE-SPLIT-2 ownership)."""
        for path in _observability_sources():
            content = path.read_text(encoding="utf-8")
            assert "core.observability" not in content, (
                f"platform observability must not import core.observability: {path}"
            )

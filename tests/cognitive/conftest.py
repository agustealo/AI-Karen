"""Pytest configuration for the COG-EVAL-1 cognitive benchmark.

Responsibilities:
  * Register the cognitive pytest markers used by the benchmark.
  * Make ``benchmarks.cognitive`` importable from test modules.
  * Install a minimal, test-only compatibility shim for the
    ``ai_karen_engine.core.observability`` package.  That package's
    ``__init__`` currently fails because the deprecated
    ``performance_metrics`` shim no longer exports ``MetricType``.  This is a
    pre-existing defect owned by COG-CLOSE-1; the shim lets the benchmark load
    the real cognitive submodules (salience, memory scoring, learning) without
    modifying any production source.  See DEFECTS.md for details.
"""

from __future__ import annotations

import importlib
import os
import sys
import types

import pytest

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_TESTS_ROOT = os.path.abspath(os.path.dirname(__file__))
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
for _p in (_REPO_ROOT, _TESTS_ROOT, _SRC_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _install_observability_shim() -> None:
    pkg_name = "ai_karen_engine.core.observability"
    existing = sys.modules.get(pkg_name)
    if isinstance(existing, types.ModuleType) and getattr(
        existing, "__cog_eval_shim__", False
    ):
        return

    pkg_path = os.path.join(
        _SRC_DIR, "ai_karen_engine", "core", "observability"
    )
    shim = types.ModuleType(pkg_name)
    shim.__path__ = [pkg_path]
    setattr(shim, "__cog_eval_shim__", True)  # noqa: B010

    sys.modules[pkg_name] = shim

    submodules = [
        "context",
        "contracts",
        "emitter",
        "events",
        "metrics",
        "redaction",
        "regression_detection",
    ]
    for sub in submodules:
        full = f"{pkg_name}.{sub}"
        try:
            mod = importlib.import_module(full)
        except ImportError:
            continue
        for attr in getattr(mod, "__all__", []):
            if not hasattr(shim, attr):
                setattr(shim, attr, getattr(mod, attr))

    _missing = [
        "MetricType",
        "AlertSeverity",
        "PerformanceMetric",
        "SystemMetrics",
        "ServiceMetrics",
        "MetricsCollector",
        "PerformanceDashboard",
        "PerformanceBenchmark",
        "PerformanceMonitoringSystem",
        "PerformanceMetrics",
        "get_performance_monitoring_system",
        "initialize_performance_monitoring",
        "shutdown_performance_monitoring",
    ]
    for name in _missing:
        if not hasattr(shim, name):
            setattr(shim, name, _Sentinel(name))

    setattr(shim, "__all__", list(dict.fromkeys(getattr(shim, "__all__", []) + _missing)))  # noqa: B010


class _Sentinel:
    """Placeholder for deprecated/removed observability symbols."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return f"<{self._name} (cog-eval shim)>"


_install_observability_shim()


def pytest_configure(config: pytest.Config) -> None:
    for marker in (
        "cognitive",
        "continuity",
        "contradiction",
        "behavior",
        "goal",
        "salience",
        "metacognition",
        "meta",
        "policy",
        "memory_security",
        "deletion",
        "learning",
    ):
        config.addinivalue_line(
            "markers",
            f"{marker}: COG-EVAL-1 cognitive benchmark scenario.",
        )


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    for item in items:
        if not item.get_closest_marker("cognitive") and "cognitive" in item.keywords:
            item.add_marker(pytest.mark.cognitive)


@pytest.fixture(scope="session")
def benchmark_root() -> str:
    return _TESTS_ROOT

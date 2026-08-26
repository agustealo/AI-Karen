"""Transitional compatibility package for historical adaptive intelligence.

AdaptiveRuntime is retained only while existing callers are audited and
migrated. New learning, evaluation, performance-profile, calibration, shadow,
and promotion functionality belongs in ``core.intelligence.ml``. Routing and
authorization decisions belong to CORTEX/RuntimePolicy, and execution remains
owned by the canonical runtime.

Do not add new execution or learning authority under this package.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AdaptiveRuntime": (".runtime", "AdaptiveRuntime"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    module = import_module(module_name, package=__name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = ["AdaptiveRuntime"]

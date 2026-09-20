"""Extension platform package.

The platform package is a namespace boundary for catalog, governance, UI, and
compatibility surfaces. Importing it must not eagerly resolve the runtime-facing
core exports: PluginKernel imports platform loader modules during canonical
runtime construction, and an eager ``from .core import *`` both defeats the
core package's lazy design and can create PluginKernel/PluginService cycles.

Explicit historical attribute access such as ``platform.PluginManager`` remains
supported through lazy delegation to ``platform.core``. Star imports intentionally
export nothing, matching the previous ``__all__ = []`` contract.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__: list[str] = []


def __getattr__(name: str) -> Any:
    core = import_module("ai_karen_engine.extensions.platform.core")
    try:
        return getattr(core, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    core = import_module("ai_karen_engine.extensions.platform.core")
    return sorted(set(globals()) | set(dir(core)))

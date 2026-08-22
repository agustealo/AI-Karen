"""Compatibility shim for legacy plugin registry.

Routes/runtime should use unified registry interface.
"""

import importlib
import pkgutil
from types import ModuleType
from typing import Dict

from ai_karen_engine.extensions.platform.core.cortex_execution_registry import (
    CortexExecutionRegistry,
    CortexPluginRecord,
)

PLUGIN_REGISTRY: Dict[str, Dict[str, ModuleType]] = {}
UNIFIED_REGISTRY = CortexExecutionRegistry()


def _discover_plugins(base_pkg: str, type_label: str) -> Dict[str, Dict[str, ModuleType]]:
    plugins: Dict[str, Dict[str, ModuleType]] = {}
    try:
        package = importlib.import_module(base_pkg)
    except ModuleNotFoundError:
        return plugins
    for _, name, ispkg in pkgutil.iter_modules(package.__path__):
        if not ispkg or name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{base_pkg}.{name}.handler")
            plugins[name] = {"handler": mod, "type": type_label}
        except Exception:
            continue
    return plugins


def load_plugins() -> Dict[str, Dict[str, ModuleType]]:
    core_plugins = _discover_plugins("ai_karen_engine.plugins", "core")
    community_plugins = _discover_plugins("ai_karen_engine.community_plugins", "community")

    PLUGIN_REGISTRY.clear()
    PLUGIN_REGISTRY.update(core_plugins)
    PLUGIN_REGISTRY.update(community_plugins)

    UNIFIED_REGISTRY.register_plugins(
        CortexPluginRecord(
            name=name,
            handler=entry["handler"],
            origin=entry.get("type", "unknown"),
            manifest={"entrypoint": "handler", "required_roles": []},
        )
        for name, entry in PLUGIN_REGISTRY.items()
    )
    return PLUGIN_REGISTRY


load_plugins()
plugin_registry = PLUGIN_REGISTRY

__all__ = ["plugin_registry", "load_plugins", "UNIFIED_REGISTRY"]

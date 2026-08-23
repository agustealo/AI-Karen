# mypy: ignore-errors
"""Core runtime components for Kari."""

import importlib


def __getattr__(name):

    if name == "LLMOrchestrator":
        from ai_karen_engine.llm_orchestrator import LLMOrchestrator as _LO

        return _LO
    if name == "NightlyFineTuner":
        from ai_karen_engine.echocore.fine_tuner import NightlyFineTuner as _NT

        return _NT
    if name == "ModelManager":
        from ai_karen_engine.core.model_runtime.model_manager import ModelManager as _MM

        return _MM
    if name == "EchoCore":
        from ai_karen_engine.learning.echo_core import EchoCore as _EC

        return _EC
    if name == "LNMClient":
        from ai_karen_engine.clients.transformers.lnm_client import LNMClient as _LC

        return _LC

    if name == "AutomationManager":
        from ai_karen_engine.automation_manager import AutomationManager as _AM

        return _AM
    if name == "PluginRouter":
        from ai_karen_engine.plugins.router import PluginRouter as _PR

        return _PR
    if name == "PluginManager":
        from ai_karen_engine.plugins.manager import PluginManager as _PM

        return _PM
    if name == "AccessDenied":
        from ai_karen_engine.plugins.router import AccessDenied as _AD

        return _AD
    if name == "DocumentStore":
        from ai_karen_engine.doc_store import DocumentStore as _DS

        return _DS
    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ImportError:
        raise AttributeError(name)


__all__ = [
    "LLMOrchestrator",
    "NightlyFineTuner",
    "AutomationManager",
    "PluginRouter",
    "PluginManager",
    "AccessDenied",
    "ModelManager",
    "EchoCore",
    "LNMClient",
    "DocumentStore",
]

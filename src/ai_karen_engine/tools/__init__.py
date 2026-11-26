"""Production tool catalog with isolated optional dependency loading.

The package exports remain compatible, but importing one tool must not
initialize unrelated interpreter, search, document or analysis dependencies.
The existing ToolService registry remains the authority for availability.
"""

from __future__ import annotations

import logging
from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_karen_engine.services.tooling.tool_service import BaseTool, ToolRegistry

logger = logging.getLogger(__name__)

# One catalog for the built-in factories and compatibility class exports.
_TOOL_EXPORTS = {
    "WebSearchTool": "web_search_tool",
    "HTTPClientTool": "http_client_tool",
    "FileSystemTool": "filesystem_tool",
    "TextProcessingTool": "text_processing_tool",
    "DataAnalysisTool": "data_analysis_tool",
    "SystemResourcesTool": "system_resources_tool",
}
_SUBPACKAGES = {"interpreters", "search", "documents"}


def __getattr__(name: str) -> Any:
    if name in _TOOL_EXPORTS:
        return getattr(import_module(f".{_TOOL_EXPORTS[name]}", __name__), name)
    if name in _SUBPACKAGES:
        return import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_production_tools() -> list[BaseTool]:
    """Load independently available tools without inventing availability."""
    tools = []
    for name in _TOOL_EXPORTS:
        try:
            tools.append(__getattr__(name)())
        except Exception as exc:
            # Optional dependency failures cannot suppress unrelated tools.
            # Never expose exception messages containing credentials.
            logger.warning(
                "tool.production_initialization_failed",
                extra={"tool_class": name, "error_type": type(exc).__name__},
            )
    return tools


def register_production_tools(tool_registry: ToolRegistry) -> int:
    """Register only successfully initialized, non-duplicate implementations."""
    registered = 0
    for tool in get_production_tools():
        try:
            if tool_registry.get_tool(tool.metadata.name) is None:
                registered += int(tool_registry.register_tool(tool))
        except Exception as exc:
            logger.warning(
                "tool.production_registration_failed",
                extra={"tool_class": type(tool).__name__, "error_type": type(exc).__name__},
            )
    return registered


__all__ = [
    "interpreters", "search", "documents",
    *_TOOL_EXPORTS,
    "get_production_tools", "register_production_tools",
]

import logging
from typing import Any, Dict

from ai_karen_engine.services.tooling.internet_capability_service import (
    InternetCapabilityService,
)

from ai_karen_engine.extensions.platform.core.host.base import (
    ExtensionBase,
    ExtensionContext,
    HookContext,
    HookPoint,
)

from .handlers.general_handler import GeneralHandler
from .handlers.news_handler import NewsHandler
from .handlers.docs_handler import DocsHandler
from .handlers.deep_research_handler import DeepResearchHandler
from .handlers.structured_extract_handler import StructuredExtractHandler
from .handlers.weather_handler import WeatherHandler
from .handlers.stock_market_handler import StockMarketHandler

logger = logging.getLogger(__name__)

MODE_HANDLER_MAP = {
    "general": GeneralHandler,
    "news": NewsHandler,
    "docs": DocsHandler,
    "deep_research": DeepResearchHandler,
    "structured_extract": StructuredExtractHandler,
    "weather": WeatherHandler,
    "stock_market": StockMarketHandler,
}


class WebSearchDispatcher(ExtensionBase):
    """
    Main dispatcher for web search plugin.

    Handles mode resolution and delegates to appropriate handler.
    """

    def __init__(self, manifest: Any, context: ExtensionContext):
        super().__init__(manifest, context)
        self._handlers: Dict[str, Any] = {}
        self._default_mode = "general"
        self._internet_service: InternetCapabilityService | None = None

    async def initialize(self) -> None:
        self.logger.info(
            "Initializing web search dispatcher",
            extra={
                "extension_name": getattr(
                    self.manifest, "name", self.__class__.__name__
                ),
                "available_modes": list(MODE_HANDLER_MAP.keys()),
                "default_mode": self._default_mode,
            },
        )

        try:
            self._default_mode = self._read_manifest_setting("default_mode") or "general"
            self._internet_service = InternetCapabilityService()

            # Pre-initialize handlers to set up search clients
            for mode, handler_class in MODE_HANDLER_MAP.items():
                try:
                    handler = handler_class(self.manifest, self.context)
                    await handler.initialize()
                    self._handlers[mode] = handler
                    self.logger.debug(f"Handler for mode '{mode}' initialized")
                except Exception as e:
                    self.logger.error(f"Failed to initialize handler for mode '{mode}': {e}")

            self.logger.info(
                "Web search handlers initialization complete",
                extra={
                    "initialized_handlers": list(self._handlers.keys()),
                    "failed_count": len(MODE_HANDLER_MAP) - len(self._handlers),
                },
            )
        except Exception as e:
            self.logger.error(f"Critical error during web search dispatcher initialization: {e}")

    async def shutdown(self) -> None:
        self.logger.debug(
            "Shutting down web search dispatcher",
            extra={
                "extension_name": getattr(
                    self.manifest, "name", self.__class__.__name__
                ),
                "handler_count": len(self._handlers),
            },
        )

        # Shutdown all handlers
        for mode, handler in self._handlers.items():
            try:
                await handler.shutdown()
            except Exception as e:
                self.logger.warning(
                    f"Error shutting down handler {mode}: {e}",
                    extra={"mode": mode, "error": str(e)},
                )

        self._handlers.clear()

    def get_status(self) -> Dict[str, Any]:
        """Return the current status of the extension."""
        return {
            "status": "healthy",
            "initialized": True,
            "version": getattr(self.manifest, "version", "unknown"),
            "handler_count": len(self._handlers),
        }

    async def execute_hook(
        self,
        hook_point: HookPoint,
        context: HookContext,
    ) -> Dict[str, Any]:
        if not self.supports_hook_point(hook_point):
            return {
                "success": False,
                "can_execute": False,
                "error": f"Unsupported hook point: {hook_point.value}",
                "hook_point": hook_point.value,
                "plugin_id": self._get_manifest_id(),
            }

        payload = self._extract_hook_payload(context)
        result = await self.run(self._extract_params(payload))
        return {
            "success": bool(result.get("can_execute", False) or result.get("sources")),
            "hook_point": hook_point.value,
            "result": result,
            "mode": result.get("mode"),
        }

    async def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        safe_params = params or {}
        query = safe_params.get("query", "") or ""
        context = safe_params.get("context", {}) or {}

        mode = self._resolve_mode(safe_params)
        handler = self._get_handler(mode)

        if not handler:
            return {
                "success": False,
                "can_execute": False,
                "error": f"Unknown mode: {mode}",
                "plugin_id": self._get_manifest_id(),
                "mode": mode,
                "query": query,
            }

        try:
            prepared = await handler.prepare(query, context)

            if self._internet_service:
                try:
                    internet_result = await self._internet_service.execute(
                        query,
                        config_override={
                            **prepared,
                            "mode": mode,
                            "requested_mode": mode,
                        },
                    )
                    if internet_result.get("sources") or internet_result.get("results"):
                        internet_result.setdefault("mode", mode)
                        internet_result["can_execute"] = True
                        internet_result.setdefault("provider", "crawl4ai")
                        internet_result.setdefault("results", [])
                        internet_result.setdefault("sources", [])
                        internet_result.setdefault("extractedData", None)
                        metadata = internet_result.get("metadata")
                        if isinstance(metadata, dict):
                            metadata.setdefault("provider", "crawl4ai")
                        return internet_result

                    self.logger.info(
                        "InternetCapabilityService returned no live results for mode %s",
                        mode,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "InternetCapabilityService failed for mode %s",
                        mode,
                        extra={"error": str(exc), "query": query},
                    )

            result = await handler.execute(prepared, query)
            result.setdefault("mode", mode)
            result["can_execute"] = bool(result.get("sources") or result.get("results"))

        except Exception as exc:
            self.logger.warning(
                "Live internet capability execution failed; returning error response",
                extra={"error": str(exc), "mode": mode, "query": query},
            )
            return {
                "success": False,
                "can_execute": False,
                "error": str(exc),
                "plugin_id": self._get_manifest_id(),
                "mode": mode,
                "query": query,
            }

        return result

    def _resolve_mode(self, params: Dict[str, Any]) -> str:
        mode = params.get("mode")

        if mode:
            normalized = mode.lower().replace("-", "_")
            if normalized in MODE_HANDLER_MAP:
                return normalized

        if "context" in params and isinstance(params["context"], dict):
            context_mode = params["context"].get("mode")
            if context_mode:
                normalized = context_mode.lower().replace("-", "_")
                if normalized in MODE_HANDLER_MAP:
                    return normalized

        manifest_default = self._read_manifest_setting("default_mode")
        if manifest_default:
            normalized = manifest_default.lower().replace("-", "_")
            if normalized in MODE_HANDLER_MAP:
                return normalized

        return self._default_mode

    def _get_handler(self, mode: str):
        # Handlers are pre-initialized in initialize()
        if mode not in MODE_HANDLER_MAP:
            return None

        return self._handlers.get(mode)

    def _extract_hook_payload(self, context: HookContext) -> Dict[str, Any]:
        data = getattr(context, "data", None)
        if isinstance(data, dict):
            return data
        return {}

    def _extract_params(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload or {}

    def _get_manifest_id(self) -> str:
        return (
            getattr(self.manifest, "id", None)
            or getattr(self.manifest, "plugin_id", None)
            or getattr(self.manifest, "name", None)
            or self.__class__.__name__
        )

    def _get_manifest_name(self) -> str:
        return (
            getattr(self.manifest, "name", None)
            or getattr(self.manifest, "id", None)
            or self.__class__.__name__
        )

    def _read_manifest_setting(self, field_name: str) -> Any:
        settings = getattr(self.manifest, "settings", None)
        if isinstance(settings, dict):
            return settings.get(field_name)
        return None


class MainExtension(WebSearchDispatcher):
    """Entry point for ExtensionLoader."""

    pass

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.extensions.platform.core.host.base import (
    ExtensionBase,
    ExtensionContext,
)

logger = logging.getLogger(__name__)


class BaseWebSearchModeHandler(ExtensionBase):
    """
    Base class for web search mode handlers.

    Provides shared helper methods for query normalization, type coercion,
    manifest access, and strategy construction. Mode-specific handlers inherit
    from this class and implement prepare() and execute() methods.

    This base class intentionally does NOT own network clients, provider
    routing, fallbacks, sessions, or HTTP concerns. All execution flows
    through the canonical InternetCapabilityService.
    """

    MODE = "base"

    DEFAULTS: Dict[str, Any] = {}

    def __init__(self, manifest: Any, context: ExtensionContext):
        super().__init__(manifest, context)

    async def initialize(self) -> None:
        """Initialize handler strategy state."""
        logger.debug(
            "Initialized web search mode handler for %s",
            self.__class__.__name__,
            extra={"handler": self.__class__.__name__},
        )

    async def shutdown(self) -> None:
        """Shutdown and cleanup resources."""
        return None

    async def execute_hook(self, hook_point, context):
        payload = self._extract_context_payload(context)
        query = self._normalize_query(payload.get("query", ""))
        prepared = await self.prepare(query, payload.get("context", {}))
        result = await self.execute(prepared, query)
        return {
            "success": not bool(result.get("error")),
            "hook_point": getattr(hook_point, "value", str(hook_point)),
            "result": result,
            "mode": getattr(self, "MODE", "base"),
        }

    async def prepare(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__}.prepare() must be implemented"
        )

    async def execute(self, config: Dict[str, Any], query: str) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__}.execute() must be implemented"
        )

    def _normalize_query(self, query: Any) -> str:
        if not isinstance(query, str):
            return ""
        return " ".join(query.strip().split())

    def _normalize_list(self, value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            normalized = value.strip()
            return [normalized] if normalized else []

        if isinstance(value, (list, tuple, set)):
            output: list[str] = []
            for item in value:
                if isinstance(item, str):
                    normalized = item.strip()
                    if normalized:
                        output.append(normalized)
            return output

        return []

    def _normalize_string(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None

    def _normalize_dict(self, value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _coerce_positive_int(self, *values: Any) -> int:
        for value in values:
            if isinstance(value, bool):
                continue
            try:
                parsed = int(value)
                if parsed > 0:
                    return parsed
            except (TypeError, ValueError):
                continue
        return 1

    def _coerce_float(self, *values: Any) -> float:
        for value in values:
            try:
                parsed = float(value)
                if parsed >= 0:
                    return parsed
            except (TypeError, ValueError):
                continue
        return 0.0

    def _coerce_bool(self, *values: Any) -> bool:
        for value in values:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "on"}:
                    return True
                if normalized in {"false", "0", "no", "off"}:
                    return False
        return False

    def _coerce_float_or_none(self, value: Any) -> Optional[float]:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _extract_context_hints(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "user_id": context.get("user_id"),
            "conversation_id": context.get("conversation_id"),
            "tenant_id": context.get("tenant_id"),
            "requested_mode": context.get("mode"),
        }

    def _extract_context_payload(self, context: Any) -> Dict[str, Any]:
        data = getattr(context, "data", None)
        return data if isinstance(data, dict) else {}

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

    def _can_execute(self, query: str) -> tuple[bool, str]:
        if not query:
            return False, "Missing query"

        if len(query) < 2:
            return False, "Query too short"

        return True, "Ready"

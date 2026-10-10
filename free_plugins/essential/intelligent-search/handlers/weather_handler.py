import logging
from typing import Any, Dict, Optional

from .base import BaseWebSearchModeHandler

logger = logging.getLogger(__name__)


class WeatherHandler(BaseWebSearchModeHandler):
    """
    Weather query intent handler.
    """

    MODE = "weather"

    DEFAULTS: Dict[str, Any] = {
        "units": "auto",
        "query_strategy": "location_first",
        "require_citations": False,
        "include_current": True,
        "include_hourly": False,
        "include_daily": False,
        "include_alerts": True,
        "max_forecast_days": 5,
    }

    async def prepare(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        safe_context = context or {}
        normalized_query = self._normalize_query(query)
        can_execute, reason = self._can_execute(normalized_query, safe_context)

        units = self._normalize_units(
            safe_context.get("units"),
            self._read_manifest_setting("units"),
            self.DEFAULTS["units"],
        )
        include_current = self._coerce_bool(
            safe_context.get("include_current"),
            self._read_manifest_setting("include_current"),
            self.DEFAULTS["include_current"],
        )
        include_hourly = self._coerce_bool(
            safe_context.get("include_hourly"),
            self._read_manifest_setting("include_hourly"),
            self.DEFAULTS["include_hourly"],
        )
        include_daily = self._coerce_bool(
            safe_context.get("include_daily"),
            self._read_manifest_setting("include_daily"),
            self.DEFAULTS["include_daily"],
        )
        include_alerts = self._coerce_bool(
            safe_context.get("include_alerts"),
            self._read_manifest_setting("include_alerts"),
            self.DEFAULTS["include_alerts"],
        )
        max_forecast_days = self._coerce_positive_int(
            safe_context.get("max_forecast_days"),
            self._read_manifest_setting("max_forecast_days"),
            self.DEFAULTS["max_forecast_days"],
        )

        location = self._normalize_string(
            safe_context.get("location")
            or safe_context.get("city")
            or safe_context.get("place")
        )
        latitude = self._coerce_float_or_none(safe_context.get("latitude"))
        longitude = self._coerce_float_or_none(safe_context.get("longitude"))

        response = {
            "extension_id": self._get_manifest_id(),
            "extension_name": self._get_manifest_name(),
            "intent_type": "weather",
            "mode": self.MODE,
            "query": normalized_query,
            "can_execute": can_execute,
            "reason": reason,
            "query_strategy": "location_first",
            "require_citations": False,
            "location": {
                "name": location,
                "latitude": latitude,
                "longitude": longitude,
            },
            "weather_profile": {
                "units": units,
                "include_current": include_current,
                "include_hourly": include_hourly,
                "include_daily": include_daily,
                "include_alerts": include_alerts,
                "max_forecast_days": max_forecast_days,
            },
            "time_policy": {
                "requested_date": self._normalize_string(
                    safe_context.get("requested_date")
                ),
                "requested_time": self._normalize_string(
                    safe_context.get("requested_time")
                ),
                "time_range": self._normalize_string(safe_context.get("time_range")),
            },
            "context_hints": self._extract_context_hints(safe_context),
            "telemetry": {
                "handler": self.__class__.__name__,
                "manifest_id": self._get_manifest_id(),
                "mode": self.MODE,
            },
        }

        self.logger.debug(
            "Prepared weather intent strategy",
            extra={
                "extension_id": response["extension_id"],
                "mode": response["mode"],
                "can_execute": response["can_execute"],
                "location": response["location"]["name"],
            },
        )

        return response

    async def execute(self, config: Dict[str, Any], query: str) -> Dict[str, Any]:
        prepared = dict(config or {})
        normalized_query = self._normalize_query(query or prepared.get("query", ""))

        if not prepared.get("query"):
            prepared["query"] = normalized_query

        if "can_execute" not in prepared or "reason" not in prepared:
            can_execute, reason = self._can_execute(
                normalized_query,
                {"location": prepared.get("location", {}).get("name")},
            )
            prepared["can_execute"] = can_execute
            prepared["reason"] = reason

        prepared.setdefault("extension_id", self._get_manifest_id())
        prepared.setdefault("extension_name", self._get_manifest_name())
        prepared.setdefault("intent_type", "weather")
        prepared.setdefault("mode", self.MODE)
        prepared.setdefault("query_strategy", self.DEFAULTS["query_strategy"])
        prepared.setdefault("require_citations", self.DEFAULTS["require_citations"])
        prepared.setdefault(
            "location",
            {
                "name": None,
                "latitude": None,
                "longitude": None,
            },
        )
        prepared.setdefault(
            "weather_profile",
            {
                "units": self.DEFAULTS["units"],
                "include_current": self.DEFAULTS["include_current"],
                "include_hourly": self.DEFAULTS["include_hourly"],
                "include_daily": self.DEFAULTS["include_daily"],
                "include_alerts": self.DEFAULTS["include_alerts"],
                "max_forecast_days": self.DEFAULTS["max_forecast_days"],
            },
        )
        prepared.setdefault(
            "time_policy",
            {
                "requested_date": None,
                "requested_time": None,
                "time_range": None,
            },
        )

        return prepared

    def _can_execute(self, query: str, context: Dict[str, Any]) -> tuple[bool, str]:
        if not query:
            return False, "Missing query"

        if len(query) < 2:
            return False, "Query too short"

        return True, "Ready"

    def _normalize_units(self, *values: Any) -> str:
        valid = {"auto", "metric", "imperial"}
        for value in values:
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in valid:
                    return normalized
        return "auto"

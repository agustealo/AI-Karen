"""Canonical read-only generative presentation data validation.

Shared by ChatRuntime and transport projections. No provider selection,
network access, persistence, or action execution occurs here.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def validate_presentation(raw: Any) -> dict[str, Any] | None:
    """Allow only bounded, JSON-native, evidence-referenced UI envelopes.

    The canonical runtime verifies tool authorization separately; this contract
    validates and minimizes UI data without granting execution authority.
    """
    import json

    if not isinstance(raw, Mapping):
        return None
    allowed = {
        "schema_version", "presentation_id", "component_type",
        "data", "evidence_ref", "correlation_id",
    }
    if set(raw) - allowed or raw.get("schema_version") != 1 or type(raw.get("schema_version")) is not int:
        return None
    component_type = raw.get("component_type")
    if not isinstance(component_type, str) or component_type not in {"weather.observation", "weather.comparison", "planner.task_list", "time.observation", "surface.composition"}:
        return None
    for key in ("presentation_id", "evidence_ref"):
        value = raw.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= 160:
            return None
    correlation = raw.get("correlation_id")
    if correlation is not None and (not isinstance(correlation, str) or len(correlation) > 160):
        return None
    data = raw.get("data")
    if not isinstance(data, (dict, list)):
        return None
    if component_type == "surface.composition":
        # First compositional slice: arrange existing trusted presentation
        # envelopes without creating another source of data or action authority.
        if not isinstance(data, dict) or set(data) != {"layout", "items"}:
            return None
        if data["layout"] not in ("stack", "grid"):
            return None
        items = data["items"]
        if not isinstance(items, list) or not 1 <= len(items) <= 6:
            return None
        safe_items = []
        for item in items:
            if not isinstance(item, Mapping) or item.get("component_type") == "surface.composition":
                return None
            # Children must share the parent's authorized evidence reference.
            if item.get("evidence_ref") != raw["evidence_ref"]:
                return None
            child = validate_presentation(item)
            if child is None:
                return None
            safe_items.append(child)
        safe = {key: value for key, value in raw.items() if key != "data"}
        safe["data"] = {"layout": data["layout"], "items": safe_items}
        try:
            encoded = json.dumps(safe, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError):
            return None
        return safe if len(encoded.encode("utf-8")) <= 32768 else None
    if component_type == "time.observation":
        if not isinstance(data, dict):
            return None
        # Render only verified, already formatted observation values. Never infer
        # a timezone, convert clocks, or synthesize a live time in the UI.
        value = data.get("formatted") or data.get("value") or data.get("time")
        timezone = data.get("timezone") or data.get("resolved_timezone")
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 160:
            return None
        if timezone is not None and (not isinstance(timezone, str) or len(timezone) > 100):
            return None
        safe = {key: val for key, val in raw.items() if key != "data"}
        safe["data"] = {"formatted": value.strip()}
        if timezone:
            safe["data"]["timezone"] = timezone
        try:
            encoded = json.dumps(safe, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError):
            return None
        return safe if len(encoded.encode("utf-8")) <= 32768 else None
    if component_type == "planner.task_list":
        if not isinstance(data, dict):
            return None
        items = data.get("tasks")
        if not isinstance(items, list) or not 1 <= len(items) <= 20:
            return None
        statuses = {"todo", "in_progress", "completed", "cancelled"}
        safe_tasks = []
        for item in items:
            if not isinstance(item, dict):
                return None
            task_id, title, status = (item.get(key) for key in ("id", "title", "status"))
            if not isinstance(task_id, str) or not 1 <= len(task_id) <= 160:
                return None
            if not isinstance(title, str) or not 1 <= len(title.strip()) <= 240:
                return None
            if not isinstance(status, str) or status not in statuses:
                return None
            safe_tasks.append({"id": task_id, "title": title.strip(), "status": status})
        safe = {key: value for key, value in raw.items() if key != "data"}
        safe["data"] = {"tasks": safe_tasks}
        try:
            encoded = json.dumps(safe, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError):
            return None
        return safe if len(encoded.encode("utf-8")) <= 32768 else None
    if raw["component_type"] == "weather.comparison" and (
        not isinstance(data, list) or not 2 <= len(data) <= 5
    ):
        return None
    if raw["component_type"] == "weather.observation" and not isinstance(data, dict):
        return None
    def weather_observation(item: Any) -> bool:
        if not isinstance(item, Mapping):
            return False
        location = item.get("location")
        if not isinstance(location, str) or not 1 <= len(location.strip()) <= 160:
            return False
        temperatures = [
            item.get(key) for key in ("temperature_f", "temperatureF")
            if key in item
        ]
        # A unitless generic temperature must not be relabeled Fahrenheit.
        if not temperatures:
            generic = item.get("temperature")
            if not (isinstance(generic, str) and generic.strip().lower().endswith("f")):
                return False
            temperatures = [generic]
        import re
        values: list[float] = []
        for temperature in temperatures:
            if type(temperature) in (int, float):
                value = float(temperature)
            elif isinstance(temperature, str) and re.fullmatch(
                r"-?\d+(?:\.\d+)?\s*(?:°\s*F)?", temperature.strip(),
                flags=re.IGNORECASE,
            ):
                value = float(re.match(r"-?\d+(?:\.\d+)?", temperature.strip()).group())
            else:
                return False
            if not -150 <= value <= 150:
                return False
            values.append(value)
        return bool(values) and max(values) - min(values) <= 0.15

    observations = data if isinstance(data, list) else [data]
    if not all(weather_observation(item) for item in observations):
        return None
    # Never expose arbitrary tool payload fields (tokens, debug internals,
    # request arguments, personal data) through a presentation renderer.
    allowed_weather_fields = frozenset({
        "location", "temperature_f", "temperatureF", "temperature",
        "high_f", "low_f", "high", "low", "humidity",
        "wind_speed_mph", "windMph", "precipitation_probability",
        "weather_code", "weatherCode", "observed_at", "timezone",
        "provider", "source_url",
    })
    safe_observations = [
        {key: value for key, value in item.items() if key in allowed_weather_fields}
        for item in observations
    ]
    safe = {
        key: value for key, value in raw.items() if key != "data"
    }
    safe["data"] = (
        safe_observations if component_type == "weather.comparison"
        else safe_observations[0]
    )
    try:
        encoded = json.dumps(safe, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError):
        return None
    if len(encoded.encode("utf-8")) > 32768:
        return None
    return safe



def compose_authorized_surface(
    *,
    presentation_id: str,
    evidence_ref: str,
    authorized_parts: list[dict[str, Any]],
    proposed_layout: Any,
    correlation_id: str | None = None,
) -> dict[str, Any] | None:
    """Admit a presentation plan using only runtime-verified parts.

    An LLM may suggest a layout and ordered part identifiers, but is never
    trusted to supply component props, evidence values, actions, or URLs.
    """
    if not isinstance(proposed_layout, Mapping) or set(proposed_layout) != {"layout", "part_ids"}:
        return None
    layout = proposed_layout["layout"]
    ids = proposed_layout["part_ids"]
    if layout not in ("stack", "grid") or not isinstance(ids, list):
        return None
    if not 1 <= len(ids) <= 6 or any(not isinstance(x, str) for x in ids):
        return None
    if len(set(ids)) != len(ids):
        return None
    parts: dict[str, dict[str, Any]] = {}
    for raw in authorized_parts:
        verified = validate_presentation(raw)
        if verified is None or verified["component_type"] == "surface.composition":
            return None
        if verified["evidence_ref"] != evidence_ref:
            return None
        key = verified["presentation_id"]
        if key in parts:
            return None
        parts[key] = verified
    if any(key not in parts for key in ids):
        return None
    envelope = {
        "schema_version": 1,
        "presentation_id": presentation_id,
        "component_type": "surface.composition",
        "evidence_ref": evidence_ref,
        "data": {"layout": layout, "items": [parts[key] for key in ids]},
    }
    if correlation_id is not None:
        envelope["correlation_id"] = correlation_id
    return validate_presentation(envelope)

"""Structured live weather retrieval for the canonical internet capability service.

Weather data is retrieved from an actual forecast API, never generalized search
snippets. The caller is responsible for authorization and execution metadata.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from ai_karen_engine.config.config_manager import get_config_value


def _location_from_weather_query(query: str) -> str:
    match = re.search(
        r"\b(?:weather(?:\s+like)?|forecast|temperature)"
        r"(?:\s+(?:today|tomorrow|tonight|right\s+now|this\s+(?:morning|afternoon|evening)))?"
        r"\s+(?:in|for|at)\s+"
        r"(?P<city>[A-Za-z][A-Za-z0-9 ,.'-]{0,110})",
        query, re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"\b(?:in|for)\s+(?P<city>[A-Za-z][A-Za-z0-9 ,.'-]{0,110})"
            r"\s+(?:weather|forecast)\b", query, re.IGNORECASE,
        )
    if not match:
        raise ValueError("Explicit location required for live weather")
    location = match.group("city").strip(" ?!. ,")
    if not location or len(location) > 120:
        raise ValueError("Weather location is invalid")
    return location


def _endpoint(setting: str, default: str, expected_host: str) -> str:
    value = str(get_config_value(setting, default) or default)
    parsed = urlsplit(value)
    # Prevent a configuration mistake from forwarding location data over HTTP
    # or to an unexpected origin. Custom provider adapters need their own gate.
    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise ValueError("Weather provider endpoint is not an approved HTTPS origin")
    return value


async def fetch_weather_observation(query: str) -> dict[str, Any]:
    """Return observed/forecast values with explicit source and valid time."""
    location = _location_from_weather_query(query)
    aliases = get_config_value("weather.open_meteo.location_aliases", {"nyc": "New York City"})
    if isinstance(aliases, dict):
        alias = aliases.get(location.lower())
        if isinstance(alias, str) and alias.strip():
            location = alias.strip()
    geocode_url = _endpoint(
        "weather.open_meteo.geocoding_url",
        "https://geocoding-api.open-meteo.com/v1/search",
        "geocoding-api.open-meteo.com",
    )
    forecast_url = _endpoint(
        "weather.open_meteo.forecast_url",
        "https://api.open-meteo.com/v1/forecast",
        "api.open-meteo.com",
    )
    timeout = max(3.0, min(float(get_config_value("weather.open_meteo.timeout_seconds", 12)), 30.0))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        geo = await client.get(geocode_url, params={"name": location, "count": 5, "language": "en", "format": "json"})
        geo.raise_for_status()
        candidates = geo.json().get("results") or []
        if not candidates:
            raise ValueError("No matching weather location found")
        first = candidates[0]
        latitude, longitude = first["latitude"], first["longitude"]
        if not (-90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180):
            raise ValueError("Invalid weather provider coordinates")
        weather = await client.get(
            forecast_url,
            params={
                "latitude": latitude, "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
                "timezone": first.get("timezone") or "auto",
                "forecast_days": 2,
            },
        )
        weather.raise_for_status()
        data = weather.json()
    current = data.get("current") or {}
    daily = data.get("daily") or {}
    observed_at = current.get("time")
    temperature = current.get("temperature_2m")
    if not observed_at or not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
        raise ValueError("Weather provider returned no usable timestamped temperature")
    label = ", ".join(
        str(part) for part in (first.get("name"), first.get("admin1"), first.get("country_code"))
        if part
    )
    result: dict[str, Any] = {
        "location": label, "observed_at": observed_at,
        "timezone": data.get("timezone") or first.get("timezone"),
        "temperature": f"{temperature} °F",
        "temperature_f": temperature,
        "provider": "open_meteo", "source_url": forecast_url,
    }
    if isinstance(current.get("weather_code"), int):
        result["weather_code"] = current["weather_code"]
    for key, output in (("relative_humidity_2m", "humidity"),
                        ("wind_speed_10m", "wind_speed_mph")):
        if isinstance(current.get(key), (int, float)):
            result[output] = current[key]
    for key, output in (("temperature_2m_max", "high_f"),
                        ("temperature_2m_min", "low_f"),
                        ("precipitation_probability_max", "precipitation_probability")):
        values = daily.get(key)
        if isinstance(values, list) and values and isinstance(values[0], (int, float)):
            result[output] = values[0]
    if "high_f" in result:
        result["high"] = f'{result["high_f"]} °F'
    if "low_f" in result:
        result["low"] = f'{result["low_f"]} °F'
    return result

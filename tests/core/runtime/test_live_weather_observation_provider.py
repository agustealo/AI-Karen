"""Weather requests must use meteorological evidence rather than search excerpts."""
from __future__ import annotations

import pytest

from ai_karen_engine.services.search.weather_observation_provider import (
    _location_from_weather_query,
    fetch_weather_observation,
)
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor


@pytest.mark.parametrize(("query", "city"), [
    ("Whats the weather today in detroit", "detroit"),
    ("What's the weather today in Detroit?", "Detroit"),
    ("Whats the weather in NYC", "NYC"),
    ("What's the weather in New York, MI?", "New York, MI"),
])
def test_explicit_weather_location_is_resolved(query: str, city: str) -> None:
    assert _location_from_weather_query(query) == city


def test_no_implicit_weather_location() -> None:
    with pytest.raises(ValueError, match="Explicit location"):
        _location_from_weather_query("What's the weather today?")


@pytest.mark.asyncio
async def test_weather_adapter_returns_timestamped_observation(monkeypatch) -> None:
    import ai_karen_engine.services.search.weather_observation_provider as module

    requests = []

    class Response:
        def __init__(self, body):
            self.body = body
        def raise_for_status(self):
            return None
        def json(self):
            return self.body

    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def get(self, url, params):
            requests.append((url, params))
            if "geocoding" in url:
                return Response({"results": [{"name": "Detroit", "admin1": "Michigan",
                    "country_code": "US", "latitude": 42.33, "longitude": -83.05,
                    "timezone": "America/Detroit"}]})
            return Response({
                "timezone": "America/Detroit",
                "current": {"time": "2026-10-14T14:00", "temperature_2m": 60,
                            "relative_humidity_2m": 75, "wind_speed_10m": 10,
                            "weather_code": 3},
                "daily": {"temperature_2m_max": [66], "temperature_2m_min": [49],
                          "precipitation_probability_max": [25]},
            })

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    monkeypatch.setattr(module, "get_config_value", lambda key, default=None: default)
    observation = await fetch_weather_observation("What's the weather today in Detroit?")
    assert observation["location"] == "Detroit, Michigan, US"
    assert observation["temperature"] == "60 °F"
    assert observation["observed_at"] == "2026-10-14T14:00"
    assert observation["high"] == "66 °F"
    payload = {"status": "ok", "extractedData": observation}
    executor = DirectCapabilityExecutor()
    assert executor._payload_succeeded("search.weather", payload)
    assert "temperature: 60 °F" in executor._render("search.weather", "Detroit", payload)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_weather_adapter_rejects_unmeasured_response(monkeypatch) -> None:
    import ai_karen_engine.services.search.weather_observation_provider as module

    class Response:
        def __init__(self, body):
            self.body = body
        def raise_for_status(self):
            return None
        def json(self):
            return self.body
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def get(self, url, params):
            if "geocoding" in url:
                return Response({"results": [{"name": "Detroit", "latitude": 42.33,
                                               "longitude": -83.05}]})
            return Response({"current": {"time": "2026-10-14T14:00"}})
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    monkeypatch.setattr(module, "get_config_value", lambda key, default=None: default)
    with pytest.raises(ValueError, match="no usable timestamped temperature"):
        await fetch_weather_observation("Weather today in Detroit")

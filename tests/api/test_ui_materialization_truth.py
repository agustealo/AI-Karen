from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.extensions.platform.api_routes import ui_materialization_routes as routes


class _FakeRegistry:
    def __init__(self, metadata=None):
        self._metadata = metadata

    def get_metadata(self, plugin_id: str):
        return self._metadata


class _FakeUIService:
    def __init__(self, *, state=None, installed=None, metadata=None, install_result=None):
        self.registry = _FakeRegistry(metadata)
        self._state = state or {
            "state": "not_installed",
            "status": "not_found",
            "message": "UI not installed",
        }
        self._installed = installed or []
        self._install_result = install_result
        self.install_calls = []

    def get_ui_state(self, plugin_id: str):
        return self._state

    def list_installed_ui(self):
        return self._installed

    def install_ui(self, plugin_id: str, category: str):
        self.install_calls.append((plugin_id, category))
        return self._install_result


def test_installed_ui_contract_does_not_invent_operational_truth(monkeypatch):
    service = _FakeUIService(
        installed=[
            {
                "plugin_id": "weather-query",
                "state": "installed",
                "status": "success",
                "message": "UI installed",
                "details": {"checksum_valid": True},
            }
        ],
        metadata=None,
    )
    monkeypatch.setattr(routes, "get_ui_service", lambda: service)

    result = routes._build_installed_ui_contract(service)
    plugin = result[0]

    assert plugin["plugin_id"] == "weather-query"
    assert plugin["status"] == "installed"
    assert plugin["install_status"] == "success"
    assert plugin["version"] is None
    assert plugin["description"] is None
    assert plugin["category"] is None
    assert plugin["capabilities"] == {}
    assert plugin["rbac"] == {}
    assert plugin["manifest_valid"] is False
    assert plugin["authorized"] is False


def test_installed_ui_contract_uses_registry_metadata_without_overriding_state(monkeypatch):
    metadata = SimpleNamespace(
        name="weather-query",
        display_name="Weather Query",
        version="2.3.0",
        description="Weather extension",
        category="information",
        tags=["weather"],
        capabilities=SimpleNamespace(model_dump=lambda: {"provides_ui": True}),
        is_valid=True,
        validation_errors=[],
    )
    service = _FakeUIService(
        installed=[
            {
                "plugin_id": "weather-query",
                "state": "installed",
                "status": "validation_failed",
                "message": "UI files corrupted",
                "details": {"checksum_valid": False},
            }
        ],
        metadata=metadata,
    )
    monkeypatch.setattr(routes, "get_ui_service", lambda: service)

    plugin = routes._build_installed_ui_contract(service)[0]

    assert plugin["display_name"] == "Weather Query"
    assert plugin["version"] == "2.3.0"
    assert plugin["category"] == "information"
    assert plugin["capabilities"] == {"provides_ui": True}
    assert plugin["manifest_valid"] is True
    assert plugin["status"] == "installed"
    assert plugin["install_status"] == "validation_failed"
    assert plugin["authorized"] is False


def test_install_uses_registry_category_and_never_defaults(monkeypatch):
    metadata = SimpleNamespace(category="information", is_valid=True, validation_errors=[])
    install_result = SimpleNamespace(
        status=SimpleNamespace(value="success"),
        state=SimpleNamespace(value="installed"),
        message="installed",
        details={},
        error_code=None,
    )
    service = _FakeUIService(metadata=metadata, install_result=install_result)
    monkeypatch.setattr(routes, "get_ui_service", lambda: service)

    result = routes._install_plugin_ui_authoritatively("weather-query")

    assert service.install_calls == [("weather-query", "information")]
    assert result["status"] == "success"


def test_install_fails_closed_when_registry_metadata_is_missing(monkeypatch):
    service = _FakeUIService(metadata=None)
    monkeypatch.setattr(routes, "get_ui_service", lambda: service)

    with pytest.raises(routes.HTTPException) as exc_info:
        routes._install_plugin_ui_authoritatively("weather-query")

    assert exc_info.value.status_code == 404
    assert service.install_calls == []

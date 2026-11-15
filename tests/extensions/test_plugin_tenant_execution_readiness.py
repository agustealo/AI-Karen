"""Tenant plugin readiness is a fail-closed admission check, not secret injection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.services import plugin_service as service_module
from ai_karen_engine.services.plugin_service import PluginService


TENANT = "29f650a6-2c7f-4b22-b8ee-9b393ad7618d"


def _manifest(*, include_secret: bool = True) -> ExtensionManifest:
    properties = {
        "region": {"type": "string", "enum": ["east", "west"]},
    }
    required = ["region"]
    if include_secret:
        properties["api_key"] = {"type": "string", "writeOnly": True}
        required.append("api_key")
    return ExtensionManifest.from_dict({
        "name": "tenant-ready",
        "version": "1.0.0",
        "display_name": "Tenant readiness",
        "description": "Configured runtime plugin",
        "author": "Test",
        "license": "MIT",
        "category": "test",
        "entrypoint": "handler:MainExtension",
        "config_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additional_properties": False,
        },
    })


def _service(*, record: dict, saved: dict | None = None) -> PluginService:
    service = PluginService()
    service.kernel = SimpleNamespace(get_record=lambda _: record)
    service._settings_repository = SimpleNamespace(
        get=AsyncMock(return_value=saved or {
            "revision": 1, "settings": {"region": "east"},
        })
    )
    return service


@pytest.mark.asyncio
async def test_configuration_readiness_rejects_unsaved_required_settings():
    service = _service(
        record={"manifest": _manifest(include_secret=False)},
        saved={"revision": 0, "settings": {}},
    )
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) == "plugin_configuration_missing"


@pytest.mark.asyncio
async def test_configuration_readiness_rejects_invalid_persisted_settings():
    service = _service(
        record={"manifest": _manifest(include_secret=False)},
        saved={"revision": 1, "settings": {"region": "invalid"}},
    )
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) == "plugin_configuration_invalid"


@pytest.mark.asyncio
async def test_configuration_readiness_rejects_database_outage():
    service = _service(record={"manifest": _manifest(include_secret=False)})
    service._settings_repository.get.side_effect = RuntimeError("database unavailable")
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) == "plugin_configuration_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "revoked", "unavailable"])
async def test_configuration_readiness_rejects_inactive_vault_credential(
    monkeypatch, state: str
):
    service = _service(record={"manifest": _manifest()})
    vault = SimpleNamespace(list_plugin_credential_status=AsyncMock(
        return_value={"api_key": {
            "status": state, "configured": False, "revision": 2,
        }}
    ))
    monkeypatch.setattr(service_module, "get_credential_vault_service", lambda: vault)
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) == "plugin_credentials_unavailable"
    assert vault.list_plugin_credential_status.await_args.kwargs["field_keys"] == frozenset(
        {"api_key"}
    )


@pytest.mark.asyncio
async def test_configuration_readiness_checks_status_without_reading_secret(
    monkeypatch,
):
    service = _service(record={"manifest": _manifest()})
    vault = SimpleNamespace(list_plugin_credential_status=AsyncMock(
        return_value={"api_key": {
            "status": "active", "configured": True, "revision": 2,
        }}
    ))
    monkeypatch.setattr(service_module, "get_credential_vault_service", lambda: vault)
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) is None
    service._settings_repository.get.assert_awaited_once_with(
        TENANT, "tenant-ready"
    )
    vault.list_plugin_credential_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_configuration_readiness_refuses_untrusted_installation():
    service = _service(record={
        "manifest": _manifest(),
        "activation_blocked_reason": "isolated_runtime_required",
    })
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) == "plugin_origin_untrusted"
    service._settings_repository.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_configuration_readiness_does_not_query_storage_for_legacy_plugin():
    service = _service(record={"manifest": SimpleNamespace(config_schema=None)})
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) is None
    service._settings_repository.get.assert_not_awaited()

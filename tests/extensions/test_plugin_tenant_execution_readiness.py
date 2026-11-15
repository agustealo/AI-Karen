"""Tenant plugin readiness is a fail-closed admission check, not secret injection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.services import plugin_service as service_module
from ai_karen_engine.services.plugin_service import PluginService
from ai_karen_engine.services.identity_vault.credential_vault_service import CredentialVaultService


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


def _service(
    *, tmp_path: Path, record: dict, saved: dict | None = None
) -> PluginService:
    # A configured plugin requires verified canonical package provenance.
    # The temporary installed package is real; settings and Vault status
    # remain independently controllable for these admission tests.
    package = tmp_path / "tenant-ready"
    package.mkdir(exist_ok=True)
    installed_record = {
        "path": package,
        "status": "enabled",
        "dependencies_resolved": True,
        "compatibility_checked": True,
        **record,
    }
    service = PluginService()
    service._resolve_root = lambda: tmp_path
    service.kernel = SimpleNamespace(
        get_record=lambda _: installed_record,
        _is_uploaded_plugin=lambda _: False,
    )
    service._settings_repository = SimpleNamespace(
        get=AsyncMock(return_value=saved if saved is not None else {
            "revision": 1, "settings": {"region": "east"},
        })
    )
    return service


@pytest.mark.asyncio
async def test_configuration_readiness_rejects_unsaved_required_settings(tmp_path: Path):
    service = _service(tmp_path=tmp_path, 
        record={"manifest": _manifest(include_secret=False)},
        saved={"revision": 0, "settings": {}},
    )
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) == "plugin_configuration_missing"


@pytest.mark.asyncio
async def test_configuration_readiness_rejects_invalid_persisted_settings(tmp_path: Path):
    service = _service(tmp_path=tmp_path, 
        record={"manifest": _manifest(include_secret=False)},
        saved={"revision": 1, "settings": {"region": "invalid"}},
    )
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) == "plugin_configuration_invalid"


@pytest.mark.asyncio
async def test_configuration_readiness_rejects_database_outage(tmp_path: Path):
    service = _service(tmp_path=tmp_path, record={"manifest": _manifest(include_secret=False)})
    service._settings_repository.get.side_effect = RuntimeError("database unavailable")
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) == "plugin_configuration_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "revoked", "unavailable"])
async def test_configuration_readiness_rejects_inactive_vault_credential(
    monkeypatch, state: str, tmp_path: Path
):
    service = _service(tmp_path=tmp_path, record={"manifest": _manifest()})
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
    monkeypatch, tmp_path: Path,
):
    service = _service(tmp_path=tmp_path, record={"manifest": _manifest()})
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
async def test_configuration_readiness_refuses_untrusted_installation(tmp_path: Path):
    service = _service(tmp_path=tmp_path, record={
        "manifest": _manifest(),
        "activation_blocked_reason": "isolated_runtime_required",
    })
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) == "plugin_origin_untrusted"
    service._settings_repository.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_configuration_readiness_does_not_query_storage_for_legacy_plugin(tmp_path: Path):
    service = _service(tmp_path=tmp_path, record={"manifest": SimpleNamespace(config_schema=None)})
    assert await service._execution_configuration_readiness(
        "tenant-ready", TENANT
    ) is None
    service._settings_repository.get.assert_not_awaited()


@pytest.mark.parametrize(
    ("status", "expires_at", "secret_count", "expected"),
    [
        ("active", None, 1, "active"),
        ("active", None, 0, "unavailable"),
        ("active", None, 2, "unavailable"),
        ("revoked", None, 1, "revoked"),
        ("active", datetime.now(timezone.utc) - timedelta(days=1), 1, "expired"),
        ("active", datetime.now(timezone.utc), 1, "expired"),
        ("active", datetime.now(timezone.utc) + timedelta(days=1), 1, "active"),
        ("active", datetime.now(timezone.utc).replace(tzinfo=None), 1, "expired"),
    ],
)
def test_plugin_vault_status_never_reports_expired_or_invalid_secret_as_active(
    status, expires_at, secret_count, expected
):
    result = CredentialVaultService._plugin_effective_credential_status(
        status=status, expires_at=expires_at, secret_count=secret_count
    )
    assert result == expected

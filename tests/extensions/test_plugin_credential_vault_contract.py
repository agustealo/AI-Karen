"""Plugin secret fields use governed Identity Vault, never settings JSON."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request
from pydantic import SecretStr

from ai_karen_engine.api_routes.extensions import extensions as routes
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.services import plugin_service as plugin_module
from ai_karen_engine.services.identity_vault.credential_vault_service import (
    CredentialVaultService,
    PluginCredentialConflict,
    PluginCredentialDenied,
)
from ai_karen_engine.services.plugin_service import PluginService


TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _manifest() -> ExtensionManifest:
    return ExtensionManifest(
        name="plugin-secret",
        version="1.0.0",
        display_name="Secret test",
        description="Secret contract regression",
        author="Tests",
        license="MIT",
        category="test",
        entrypoint="handler:MainExtension",
        config_schema={
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "writeOnly": True},
                "webhook_secret": {"type": "string", "format": "password"},
                "region": {"type": "string", "default": "east"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    )


def _user():
    return {"tenant_id": TENANT, "user_id": "plugin-admin", "authenticated": True}


def _request():
    return Request({
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "path": "/api/extensions/plugin-secret/credentials/api_key",
        "headers": [(b"x-request-id", b"req-1"), (b"x-correlation-id", b"corr-1")],
        "query_string": b"",
        "server": ("testserver", 80),
    })


@pytest.mark.asyncio
async def test_manifest_enforces_only_declared_secret_fields():
    service = PluginService()
    service.get_plugin_info = AsyncMock(return_value={
        "manifest": _manifest(), "is_valid": True, "error_message": None
    })
    assert await service._require_plugin_credential_field("plugin-secret") == frozenset({
        "api_key", "webhook_secret",
    })
    with pytest.raises(Exception, match="not declared"):
        await service._require_plugin_credential_field("plugin-secret", "region")
    with pytest.raises(Exception, match="not declared"):
        await service._require_plugin_credential_field("plugin-secret", "unknown")
    service.get_plugin_info.assert_awaited()


@pytest.mark.asyncio
async def test_quarantined_package_rejected_before_vault_call(monkeypatch):
    service = PluginService()
    service.get_plugin_info = AsyncMock(return_value={
        "manifest": _manifest(),
        "is_valid": True,
        "error_message": None,
        "activation_blocked_reason": "isolated_runtime_required",
    })
    vault = SimpleNamespace(write_plugin_credential=AsyncMock(
        side_effect=AssertionError("quarantined package reached Vault")
    ))
    monkeypatch.setattr(plugin_module, "get_credential_vault_service", lambda: vault)
    with pytest.raises(Exception, match="Quarantined"):
        await service.write_plugin_credential(
            plugin_id="plugin-secret",
            field_key="api_key",
            tenant_id=TENANT,
            actor_user_id="plugin-admin",
            secret_value="secret must not be stored",
            revision=0,
            correlation_id="corr-1",
        )
    vault.write_plugin_credential.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_routes_tenant_bound_credential_to_vault_without_readback(monkeypatch):
    service = PluginService()
    service.get_plugin_info = AsyncMock(return_value={
        "manifest": _manifest(), "is_valid": True, "error_message": None
    })
    vault = SimpleNamespace(
        list_plugin_credential_status=AsyncMock(return_value={
            "api_key": {"status": "missing", "configured": False, "revision": 0},
            "webhook_secret": {"status": "active", "configured": True, "revision": 2},
        }),
        write_plugin_credential=AsyncMock(return_value={
            "status": "active", "configured": True, "revision": 3,
        }),
        revoke_plugin_credential=AsyncMock(return_value={
            "status": "revoked", "configured": False, "revision": 4,
        }),
    )
    monkeypatch.setattr(plugin_module, "get_credential_vault_service", lambda: vault)
    inventory = await service.read_plugin_credential_status("plugin-secret", TENANT)
    assert set(inventory["fields"]) == {"api_key", "webhook_secret"}
    assert "secret" not in str(inventory["fields"]["api_key"]).lower()

    stored = await service.write_plugin_credential(
        plugin_id="plugin-secret",
        field_key="webhook_secret",
        tenant_id=TENANT,
        actor_user_id="plugin-admin",
        secret_value="ultra-private-value",
        revision=2,
        correlation_id="corr-1",
    )
    assert stored == {
        "plugin_id": "plugin-secret",
        "field_key": "webhook_secret",
        "configured": True, "status": "active", "revision": 3,
    }
    assert vault.write_plugin_credential.await_args.kwargs["tenant_id"] == uuid.UUID(TENANT)
    assert vault.write_plugin_credential.await_args.kwargs["secret_value"] == "ultra-private-value"
    assert "ultra-private-value" not in str(stored)

    revoked = await service.revoke_plugin_credential(
        plugin_id="plugin-secret",
        field_key="webhook_secret",
        tenant_id=TENANT,
        actor_user_id="plugin-admin",
        revision=3,
        correlation_id="corr-2",
    )
    assert revoked["configured"] is False
    assert revoked["revision"] == 4
    assert "secret_value" not in vault.revoke_plugin_credential.await_args.kwargs


@pytest.mark.parametrize("bad_tenant,bad_plugin,bad_field", [
    ("not-uuid", "plugin-secret", "api_key"),
    (TENANT, "../escape", "api_key"),
    (TENANT, "plugin-secret", "../secret"),
    (TENANT, "plugin-secret", "token="),
])
def test_vault_validates_tenant_and_field_scope_without_sql(
    bad_tenant, bad_plugin, bad_field
):
    with pytest.raises(PluginCredentialDenied):
        CredentialVaultService._plugin_secret_scope(
            bad_tenant, bad_plugin, bad_field
        )


@pytest.mark.asyncio
async def test_vault_denies_invalid_value_and_revision_before_database_access(monkeypatch):
    vault = CredentialVaultService()
    called = []

    async def inaccessible(*_args, **_kwargs):
        called.append("database")
        pytest.fail("invalid plugin secret touched database")

    monkeypatch.setattr(vault, "_check_rate_limit", inaccessible)
    for secret, rev in (("", 0), (" \n", 0), ("x" * 8192, 0), ("ok", -1), ("ok", True)):
        with pytest.raises(PluginCredentialDenied):
            await vault.write_plugin_credential(
                tenant_id=uuid.UUID(TENANT),
                actor_user_id="operator",
                plugin_id="plugin-secret",
                field_key="api_key",
                secret_value=secret,
                expected_revision=rev,
                correlation_id="corr-1",
            )
    assert called == []


@pytest.mark.asyncio
async def test_route_requires_auth_and_does_not_echo_secret():
    saved = []
    class Service:
        async def write_plugin_credential(self, **kwargs):
            saved.append(kwargs)
            return {
                "plugin_id": "plugin-secret",
                "field_key": "api_key",
                "configured": True,
                "status": "active",
                "revision": 1,
            }
    body = routes.PluginCredentialWriteRequest(
        value=SecretStr("not-for-logs"),
        revision=0,
    )
    assert "not-for-logs" not in repr(body)
    response = await routes.write_extension_credential(
        extension_name="plugin-secret",
        field_key="api_key",
        body=body,
        request=_request(),
        user=_user(),
        plugin_service=Service(),
    )
    assert response["revision"] == 1
    assert "not-for-logs" not in str(response)
    assert saved[0]["tenant_id"] == TENANT
    assert saved[0]["correlation_id"] == "corr-1"


def test_plugin_secret_routes_are_admin_only_and_before_dynamic_status_route():
    source = routes.router.routes
    exposed = {
        (route.path, next(iter(route.methods))) : route
        for route in source if getattr(route, "methods", None) and len(route.methods) == 1
    }
    for path, method in (
        ("/{extension_name}/credentials", "GET"),
        ("/{extension_name}/credentials/{field_key}", "POST"),
        ("/{extension_name}/credentials/{field_key}", "DELETE"),
    ):
        route = exposed[path, method]
        assert any(
            dep.call is routes.require_extension_mutation_access
            for dep in route.dependant.dependencies
        )
    all_paths = [route.path for route in source]
    assert all_paths.index("/{extension_name}/credentials") < all_paths.index(
        "/{extension_name}"
    )
    assert routes._settings_error(
        PluginCredentialConflict("stale")
    ).status_code == 409
    assert routes._settings_error(
        PluginCredentialDenied("no")
    ).status_code == 403


def test_plugin_vault_migration_has_scoped_fk_rls_restricted_api_grants():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    migration = (
        root / "supabase/migrations/20261114040000_52_plugin_vault_binding.sql"
    ).read_text(encoding="utf-8")
    assert "FOREIGN KEY (tenant_id, credential_id)" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "ON DELETE RESTRICT" in migration
    assert "ARRAY['anon', 'authenticated']" in migration
    assert "REVOKE ALL ON public.plugin_credential_slots FROM PUBLIC" in migration
    assert "encrypted_value" not in migration
    assert "credential_id uuid NOT NULL" in migration

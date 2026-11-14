"""Authoritative plugin-settings schema, database scope and HTTP receipts."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.api_routes.extensions import extensions as routes
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.services.plugin_service import PluginService
from ai_karen_engine.services.plugin_settings_repository import (
    PluginSettingsNotConfigured,
    PluginSettingsRepository,
    PluginSettingsRevisionConflict,
    PluginSettingsValidationError,
)


TENANT_A = "00000000-0000-4000-8000-000000000001"
TENANT_B = "00000000-0000-4000-8000-000000000002"


def _manifest():
    return ExtensionManifest(
        name="settings-test",
        version="1.0.0",
        display_name="Settings",
        description="Settings contract",
        author="Tests",
        license="MIT",
        category="test",
        entrypoint="handler:MainExtension",
        config_schema={
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "title": "Request timeout",
                },
                "enabled": {"type": "boolean", "default": False},
                "region": {"type": "string", "enum": ["east", "west"]},
                "api_key": {
                    "type": "string",
                    "writeOnly": True,
                    "default": "should-never-be-returned",
                },
                "nested": {"type": "object", "default": {"token": "hidden"}},
            },
            "required": ["region"],
        },
    )


def _request():
    return Request({
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "path": "/api/extensions/settings-test/settings",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"x-request-id", b"request-1"), (b"x-correlation-id", b"corr-1")],
        "server": ("testserver", 80),
    })


def test_manifest_defines_nonsecret_writable_keys_and_default_projection():
    contract = PluginSettingsRepository.contract(_manifest())
    assert contract.required == ("region",)
    assert set(contract.rules) == {"timeout", "enabled", "region"}
    assert contract.defaults == {"timeout": 20, "enabled": False}
    fields = {field["key"]: field for field in contract.fields}
    assert fields["api_key"]["readOnly"] is True
    assert fields["api_key"]["type"] == "password"
    assert "defaultValue" not in fields["api_key"]
    assert fields["nested"]["readOnly"] is True
    assert "defaultValue" not in fields["nested"]
    assert "hidden" not in json.dumps(contract.fields)
    assert "should-never-be-returned" not in json.dumps(contract.fields)
    assert contract.present({"timeout": 30, "api_key": "database-leak", "nested": {}}) == {
        "timeout": 30, "enabled": False,
    }


@pytest.mark.parametrize(
    "values",
    [
        {"region": "east", "api_key": "secret-value"},
        {"region": "west", "password": "secret-value"},
        {"region": "west", "nested": {"token": "secret-value"}},
        {"region": "moon"},
        {"region": "east", "timeout": -1},
        {"region": "east", "timeout": "wrong-type"},
        {"enabled": True},
    ],
)
def test_settings_reject_undeclared_credentials_and_invalid_schema(values):
    contract = PluginSettingsRepository.contract(_manifest())
    with pytest.raises(PluginSettingsValidationError) as exc:
        contract.validate(values)
    assert "secret-value" not in str(exc.value)


def test_only_declared_valid_settings_are_accepted_without_secret_values():
    contract = PluginSettingsRepository.contract(_manifest())
    assert contract.validate({"region": "east", "timeout": 9}) == {
        "region": "east", "timeout": 9,
    }
    with pytest.raises(PluginSettingsNotConfigured):
        PluginSettingsRepository.contract(SimpleNamespace(config_schema=None))


class _Result:
    def __init__(self, *, row=None, rows=None, scalar=1):
        self.row = row
        self.rows = rows or []
        self.scalar = scalar

    def scalar_one_or_none(self):
        return self.scalar

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row

    def all(self):
        return self.rows


class _Session:
    def __init__(self, *, version=1, audit_failure=False):
        self.version = version
        self.audit_failure = audit_failure
        self.calls = []
        self.scope = None

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, dict(params or {})))
        if "set_config(" in sql:
            self.scope = params["tenant_id"]
            return _Result()
        if "SELECT settings, revision" in sql:
            return _Result(row={
                "settings": {"region": "east", "api_key": "injected-private-value"},
                "revision": 3,
            })
        if "SELECT plugin_id, settings, revision" in sql:
            return _Result(rows=[{
                "plugin_id": "settings-test",
                "settings": {"region": "east"},
                "revision": 3,
            }])
        if "INSERT INTO public.extension_plugin_settings_audit" in sql:
            if self.audit_failure:
                raise RuntimeError("audit store unavailable")
            return _Result()
        if "UPDATE public.extension_plugin_settings" in sql:
            return _Result(scalar=self.version)
        if "INSERT INTO public.extension_plugin_settings" in sql:
            return _Result(scalar=self.version)
        raise AssertionError("Unexpected SQL request")


class _Client:
    def __init__(self, session):
        self.session = session
        self.committed = False

    @asynccontextmanager
    async def get_async_session(self):
        yield self.session
        self.committed = True


@pytest.mark.asyncio
async def test_repository_sets_tenant_rls_and_queries_exact_scope():
    session = _Session()
    repository = PluginSettingsRepository(lambda: _Client(session))
    fetched = await repository.get(TENANT_A, "settings-test")
    assert fetched["revision"] == 3
    assert fetched["settings"]["region"] == "east"
    assert session.scope == TENANT_A
    assert "tenant_id = CAST(:tenant_id AS uuid)" in session.calls[1][0]
    assert session.calls[1][1]["tenant_id"] == TENANT_A
    assert "tenant-a" not in str(session.calls[1])

    data = await repository.list_tenant(TENANT_B)
    assert data["settings-test"]["revision"] == 3
    assert session.scope == TENANT_B
    assert session.calls[-1][1]["tenant_id"] == TENANT_B


@pytest.mark.asyncio
async def test_write_is_revision_checked_and_audit_is_value_free_in_transaction():
    session = _Session(version=5)
    client = _Client(session)
    repo = PluginSettingsRepository(lambda: client)
    version = await repo.write(
        tenant_id=TENANT_A,
        plugin_id="settings-test",
        actor_user_id="operator",
        operation="save",
        settings={"region": "east"},
        expected_revision=4,
        request_id="request-1",
        correlation_id="corr-1",
    )
    assert version == 5
    assert client.committed is True
    statements = [sql for sql, _ in session.calls]
    assert "revision = :revision" in statements[1]
    assert "tenant_id = CAST(:tenant_id AS uuid)" in statements[1]
    assert "INSERT INTO public.extension_plugin_settings_audit" in statements[2]
    audit_params = session.calls[2][1]
    assert "settings" not in audit_params
    assert json.dumps({"region": "east"}) not in str(audit_params)
    assert audit_params["new_revision"] == 5


@pytest.mark.asyncio
async def test_audit_failure_cannot_acknowledge_success_or_commit():
    session = _Session(audit_failure=True)
    client = _Client(session)
    repo = PluginSettingsRepository(lambda: client)
    with pytest.raises(RuntimeError, match="audit store unavailable"):
        await repo.write(
            tenant_id=TENANT_A,
            plugin_id="settings-test",
            actor_user_id="operator",
            operation="reset",
            settings={},
            expected_revision=0,
            request_id="request-1",
            correlation_id="corr-1",
        )
    assert client.committed is False


@pytest.mark.asyncio
async def test_stale_revision_rejected_without_audit_or_success():
    session = _Session(version=None)
    client = _Client(session)
    repo = PluginSettingsRepository(lambda: client)
    with pytest.raises(PluginSettingsRevisionConflict):
        await repo.write(
            tenant_id=TENANT_A,
            plugin_id="settings-test",
            actor_user_id="operator",
            operation="save",
            settings={"region": "west"},
            expected_revision=2,
            request_id="request-1",
            correlation_id="corr-1",
        )
    assert not any("settings_audit" in sql for sql, _ in session.calls)
    assert client.committed is False


@pytest.mark.asyncio
async def test_unscoped_or_invalid_tenant_rejected_before_database_access():
    repo = PluginSettingsRepository(lambda: pytest.fail("invalid tenant touched DB"))
    with pytest.raises(PluginSettingsValidationError, match="tenant"):
        await repo.get("another-tenant", "settings-test")


@pytest.mark.asyncio
async def test_service_requires_canonical_manifest_and_confirms_only_persisted_revisions():
    service = PluginService()
    service.get_plugin_info = AsyncMock(return_value={
        "manifest": _manifest(), "is_valid": True, "error_message": None
    })
    service.list_plugins = AsyncMock(return_value=[{
        "manifest": _manifest(), "is_valid": True, "error_message": None
    }])
    store = SimpleNamespace(
        get=AsyncMock(return_value={"settings": {"region": "east"}, "revision": 3}),
        list_tenant=AsyncMock(return_value={
            "settings-test": {"settings": {"region": "west"}, "revision": 4}
        }),
        write=AsyncMock(return_value=5),
    )
    service._settings_repository = store

    result = await service.read_plugin_settings("settings-test", TENANT_A)
    assert result["settings"] == {"region": "east", "timeout": 20, "enabled": False}
    assert result["revision"] == 3
    assert result["stored"] is True
    assert len(await service.list_plugin_settings(TENANT_A)) == 1

    saved = await service.write_plugin_settings(
        plugin_id="settings-test",
        tenant_id=TENANT_A,
        actor_user_id="operator",
        settings={"region": "west"},
        revision=4,
        request_id="request-1",
        correlation_id="corr-1",
    )
    assert saved["success"] is True
    assert saved["saved"] is True
    assert saved["revision"] == 5
    assert saved["settings"]["region"] == "west"
    assert store.write.await_args.kwargs["expected_revision"] == 4

    with pytest.raises(PluginSettingsValidationError):
        await service.write_plugin_settings(
            plugin_id="settings-test", tenant_id=TENANT_A, actor_user_id="operator",
            settings={"region": "east", "api_key": "private"},
            revision=5, request_id="request-1", correlation_id="corr-1",
        )
    assert store.write.await_count == 1


@pytest.mark.asyncio
async def test_route_uses_authenticated_tenant_and_maps_stale_revision():
    saved = []

    class _Service:
        async def write_plugin_settings(self, **kwargs):
            saved.append(kwargs)
            raise PluginSettingsRevisionConflict("Plugin settings changed; refresh before saving")

    with pytest.raises(HTTPException) as exc:
        await routes.save_extension_settings(
            extension_name="settings-test",
            body=routes.PluginSettingsUpdateRequest(
                settings={"region": "east"}, revision=6
            ),
            request=_request(),
            user={"user_id": "operator", "tenant_id": TENANT_A},
            plugin_service=_Service(),
        )
    assert exc.value.status_code == 409
    assert saved[0]["tenant_id"] == TENANT_A
    assert saved[0]["actor_user_id"] == "operator"
    assert saved[0]["revision"] == 6
    assert saved[0]["request_id"] == "request-1"


def test_settings_routes_require_real_plugin_manager_rbac():
    endpoints = {
        (route.path, next(iter(route.methods)) if len(route.methods) == 1 else "MULTI"): route
        for route in routes.router.routes if getattr(route, "methods", None)
    }
    for path, verb in (
        ("/settings", "GET"),
        ("/{extension_name}/settings", "GET"),
        ("/{extension_name}/settings", "POST"),
        ("/{extension_name}/settings", "DELETE"),
    ):
        route = endpoints[(path, verb)]
        assert any(
            dependency.call is routes.require_extension_mutation_access
            for dependency in route.dependant.dependencies
        )


def test_migration_has_forced_rls_tenant_policies_atomic_audit_without_secrets():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    migration = (
        root / "supabase/migrations/20261114030000_51_tenant_plugin_settings.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE public.extension_plugin_settings (" in migration
    assert "CREATE TABLE public.extension_plugin_settings_audit (" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert migration.count("current_setting('app.current_tenant_id', true)") >= 5
    assert "ON DELETE CASCADE" in migration
    assert "encrypted_value" not in migration
    assert "actor_user_id" in migration

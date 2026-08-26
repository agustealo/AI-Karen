"""Tests for canonical extension executor."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from ai_karen_engine.extensions.contracts import (
    ExtensionCapability,
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionHealth,
    ExtensionLifecycleState,
    ExtensionManifest,
    ExtensionRegistration,
    ResponseSource,
)
from ai_karen_engine.extensions.executor import ExtensionExecutionService
from ai_karen_engine.extensions.errors import (
    ExtensionDisabledError,
    ExtensionNotFoundError,
    ExtensionPermissionError,
)


class FakeHandler:
    async def execute(self, payload: Dict[str, Any], context: Any) -> Dict[str, Any]:
        return {"echo": payload.get("message", "")}


def _manifest() -> ExtensionManifest:
    return ExtensionManifest(
        id="echo",
        name="echo",
        version="1.0.0",
        plugin_api_version="1.0",
        description="Test",
        entrypoint="handler:EchoExtension",
        capabilities=[ExtensionCapability(id="echo", version="1.0.0")],
        intents=["echo"],
        required_permissions=[],
        optional_permissions=[],
        required_roles=[],
        tenant_scope="single",
        allowed_tenant_ids=[],
        input_schema={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
        output_schema={"type": "object", "properties": {"echo": {"type": "string"}}, "required": ["echo"]},
        side_effect_level="none",
        timeout_ms=5000,
        max_retries=1,
        enabled_by_default=False,
        trusted_ui=False,
        dependencies=[],
        trust_tier="first_party",
        isolation_mode="subprocess",
    )


@pytest.mark.asyncio
async def test_execute_success():
    registry = type("FakeRegistry", (), {
        "get": lambda self, pid: ExtensionRegistration(
            manifest=_manifest(),
            state=ExtensionLifecycleState.ENABLED,
            instance=FakeHandler(),
        )
    })()
    lifecycle = type("FakeLifecycle", (), {"get_health": lambda self, pid: ExtensionHealth.HEALTHY})()
    service = ExtensionExecutionService(registry=registry, lifecycle=lifecycle)

    request = ExtensionExecutionRequest(
        plugin_id="echo",
        capability="echo",
        payload={"message": "hello"},
        context=ExtensionExecutionContext.for_runtime(
            request_id="req-1",
            correlation_id="corr-1",
            user_id="user-1",
            tenant_id="tenant-1",
            policy_decision_id="policy-1",
            allowed_capabilities=(),
        ),
        authorized_plan={"allowed_plugins": ["echo"], "allowed_capabilities": []},
    )

    result = await service.execute(request)
    assert result.status == "success"
    assert result.source == ResponseSource.PLUGIN
    assert result.payload == {"echo": "hello"}


@pytest.mark.asyncio
async def test_disabled_plugin_denied():
    registry = type("FakeRegistry", (), {
        "get": lambda self, pid: ExtensionRegistration(
            manifest=_manifest(),
            state=ExtensionLifecycleState.DISABLED,
            instance=FakeHandler(),
        )
    })()
    service = ExtensionExecutionService(registry=registry)
    request = ExtensionExecutionRequest(
        plugin_id="echo",
        capability="echo",
        payload={"message": "hello"},
        context=ExtensionExecutionContext.for_runtime(
            request_id="req-1",
            correlation_id="corr-1",
            user_id="user-1",
            tenant_id="tenant-1",
        ),
    )
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "disabled"


@pytest.mark.asyncio
async def test_not_found():
    registry = type("FakeRegistry", (), {"get": lambda self, pid: None})()
    service = ExtensionExecutionService(registry=registry)
    request = ExtensionExecutionRequest(
        plugin_id="missing",
        capability="echo",
        payload={},
        context=ExtensionExecutionContext.for_runtime(
            request_id="req-1",
            correlation_id="corr-1",
            user_id="user-1",
            tenant_id="tenant-1",
        ),
    )
    result = await service.execute(request)
    assert result.status == "failed"
    assert result.error_code == "not_found"

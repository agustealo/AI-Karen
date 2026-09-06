"""Architecture proofs for chat transport authority closure.

These tests deliberately inspect production source in addition to unit behavior.
They prevent a future transport adapter from reintroducing provider selection,
fake model output, synthesized tenant identity, or fail-open Copilot RBAC.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.chat.execution_identity import (
    can_execute_copilot_action,
    require_execution_identity,
)

ROOT = Path(__file__).resolve().parents[2]
WEBSOCKET = ROOT / "src/ai_karen_engine/api_routes/chat/websocket.py"
COPILOT = ROOT / "src/ai_karen_engine/api_routes/chat/copilot.py"
AUTH_UTILS = ROOT / "src/ai_karen_engine/auth/auth_utils.py"
STREAM_PROCESSOR = ROOT / "src/ai_karen_engine/services/streaming/stream_processor.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_realtime_chat_has_one_generation_authority() -> None:
    source = _read(WEBSOCKET)

    assert "AsyncStreamProcessor" not in source
    assert "services.streaming.stream_processor" not in source
    assert "get_chat_runtime().execute_stream" in source
    assert "This is a simulated streaming response" not in source
    assert "_generate_fallback_chunk" not in source


def test_legacy_stream_processor_is_not_imported_by_chat_routes() -> None:
    chat_route_dir = ROOT / "src/ai_karen_engine/api_routes/chat"
    offenders = []
    for path in chat_route_dir.glob("*.py"):
        source = _read(path)
        if "services.streaming.stream_processor" in source or "AsyncStreamProcessor" in source:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_chat_transports_do_not_synthesize_default_tenant() -> None:
    for path in (WEBSOCKET, COPILOT, AUTH_UTILS):
        source = _read(path)
        assert 'tenant_id=str(' not in source or 'or "default"' not in source
        assert 'tenant_id"] = "default"' not in source
        assert "tenant_id'] = 'default'" not in source


def test_copilot_rbac_has_no_fail_open_swallow() -> None:
    source = _read(COPILOT)

    assert "can_execute_copilot_action" in source
    assert "Copilot action permission required" in source
    assert "roles\": [\"admin\"]" not in source
    assert "ALLOW_PUBLIC_COPILOT" not in source
    assert "AUTH_MODE" not in source


def test_transport_errors_do_not_echo_raw_exceptions_to_clients() -> None:
    for path in (WEBSOCKET, COPILOT):
        source = _read(path)
        assert '"content": str(exc)' not in source
        assert 'detail=f"Failed to' not in source
        assert '"message": str(exc)' not in source


def test_legacy_stream_controls_are_explicitly_retired() -> None:
    source = _read(WEBSOCKET)

    assert "status_code=410" in source
    assert '"canonical_stream_endpoint": "/api/stream"' in source
    assert '"runtime_authority": "ChatRuntime"' in source


def test_default_tenant_fails_closed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_execution_identity(
            {"user_id": "user-1", "tenant_id": "default", "roles": ["user"]}
        )

    assert exc_info.value.status_code == 401


def test_missing_tenant_fails_closed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_execution_identity({"user_id": "user-1", "roles": ["user"]})

    assert exc_info.value.status_code == 401


def test_copilot_action_permission_is_explicit() -> None:
    assert can_execute_copilot_action(
        {
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "permissions": ["chat:write"],
        }
    )
    assert can_execute_copilot_action(
        {
            "user_id": "admin-1",
            "tenant_id": "tenant-1",
            "roles": ["admin"],
        }
    )
    assert not can_execute_copilot_action(
        {
            "user_id": "user-2",
            "tenant_id": "tenant-1",
            "roles": ["user"],
            "permissions": [],
        }
    )


def test_simulated_stream_processor_is_quarantined_from_production_routes() -> None:
    """The legacy implementation may remain temporarily, but cannot be reachable."""

    legacy_source = _read(STREAM_PROCESSOR)
    assert "This is a simulated streaming response" in legacy_source

    websocket_source = _read(WEBSOCKET)
    copilot_source = _read(COPILOT)
    assert "stream_processor" not in websocket_source.lower()
    assert "stream_processor" not in copilot_source.lower()

from __future__ import annotations

from pathlib import Path

from ai_karen_engine.config.agent_medusa import (
    AgentMedusaConfigError,
    AgentMedusaRuntimeSettings,
)

ROOT = Path(__file__).resolve().parents[2]
RUN_MANAGER = ROOT / "src/ai_karen_engine/agent_medusa/execution/run_manager.py"
STORE = ROOT / "src/ai_karen_engine/agent_medusa/execution/distributed_run_store.py"
CONTROL_PLANE = ROOT / "src/ai_karen_engine/agent_medusa/control_plane.py"
API = ROOT / "src/ai_karen_engine/api_routes/admin/agents.py"


def test_distributed_run_store_reuses_canonical_redis_authority() -> None:
    source = STORE.read_text(encoding="utf-8")

    assert "ai_karen_engine.platform.memory.redis" in source
    assert "get_redis_manager" in source
    assert "redis.asyncio" not in source
    assert "Redis.from_url" not in source
    assert "_redis.client" in source
    assert "_redis.set(" not in source
    assert "_RENEW_CLAIM_SCRIPT" in source
    assert "_RELEASE_CLAIM_SCRIPT" in source
    assert "_CANCEL_RUN_SCRIPT" in source
    assert "_MARK_TERMINAL_SCRIPT" in source


def test_run_manager_owns_task_cancellation_and_remote_delivery() -> None:
    source = RUN_MANAGER.read_text(encoding="utf-8")

    assert "task.cancel()" in source
    assert "_heartbeat_loop" in source
    assert "request_cancel" in source
    assert "RedisDistributedRunStore" in source
    assert "provider" not in source.lower()
    assert "prompt" not in source.lower()


def test_control_plane_owns_admin_cancellation_audit() -> None:
    source = CONTROL_PLANE.read_text(encoding="utf-8")

    assert "get_audit_logger" in source
    assert 'message="medusa_run_cancel_requested"' in source
    assert "tenant_id=tenant_id" in source
    assert "user_id=actor_user_id" in source
    assert "correlation_id=" in source
    assert "run_id" in source


def test_admin_route_only_forwards_actor_and_tenant_context() -> None:
    source = API.read_text(encoding="utf-8")

    assert "Redis" not in source
    assert "worker_id" not in source
    assert "task.cancel" not in source
    assert "MedusaRunManager(" not in source
    assert "get_audit_logger" not in source
    assert "actor_user_id=_actor_user_id(current_user)" in source
    assert "session_id=_session_id(current_user)" in source


def test_medusa_runtime_settings_reject_invalid_lease_relationship() -> None:
    try:
        AgentMedusaRuntimeSettings(
            distributed_run_control_enabled=True,
            run_lease_ttl_seconds=10,
            run_heartbeat_interval_seconds=10,
            run_terminal_retention_seconds=60,
            run_key_prefix="test",
            worker_id="worker-a",
        )
    except AgentMedusaConfigError:
        pass
    else:
        raise AssertionError("heartbeat interval equal to lease TTL must be rejected")

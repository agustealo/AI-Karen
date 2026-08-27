from __future__ import annotations

from pathlib import Path

from ai_karen_engine.config.agent_medusa import (
    AgentMedusaConfigError,
    AgentMedusaRuntimeSettings,
)

ROOT = Path(__file__).resolve().parents[2]
RUN_MANAGER = ROOT / "src/ai_karen_engine/agent_medusa/execution/run_manager.py"
STORE = ROOT / "src/ai_karen_engine/agent_medusa/execution/distributed_run_store.py"
API = ROOT / "src/ai_karen_engine/api_routes/admin/agents.py"


def test_distributed_run_store_reuses_canonical_redis_authority() -> None:
    source = STORE.read_text(encoding="utf-8")

    assert "ai_karen_engine.platform.memory.redis" in source
    assert "get_redis_manager" in source
    assert "redis.asyncio" not in source
    assert "Redis.from_url" not in source
    assert "_redis.client" in source
    assert "_redis.set(" not in source


def test_run_manager_owns_task_cancellation_and_remote_delivery() -> None:
    source = RUN_MANAGER.read_text(encoding="utf-8")

    assert "task.cancel()" in source
    assert "_heartbeat_loop" in source
    assert "request_cancel" in source
    assert "RedisDistributedRunStore" in source
    assert "provider" not in source.lower()
    assert "prompt" not in source.lower()


def test_admin_route_does_not_own_distributed_coordination() -> None:
    source = API.read_text(encoding="utf-8")

    assert "Redis" not in source
    assert "worker_id" not in source
    assert "task.cancel" not in source
    assert "MedusaRunManager(" not in source


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

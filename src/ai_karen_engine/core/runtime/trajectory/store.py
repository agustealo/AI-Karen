from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ai_karen_engine.core.runtime.trajectory.contracts import ExecutionTrajectory


class TrajectoryStore(ABC):
    """Abstract storage for execution trajectories."""

    @abstractmethod
    def save(self, trajectory: ExecutionTrajectory) -> None:
        """Persist a trajectory."""

    @abstractmethod
    def get(self, trajectory_id: str) -> ExecutionTrajectory | None:
        """Retrieve a trajectory by ID."""

    @abstractmethod
    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[ExecutionTrajectory]:
        """List recent trajectories for a tenant."""


class InMemoryTrajectoryStore(TrajectoryStore):
    """Non-durable in-memory store for testing and fallback."""

    def __init__(self) -> None:
        self._records: dict[str, ExecutionTrajectory] = {}
        self._tenant_index: dict[str, list[str]] = {}

    def save(self, trajectory: ExecutionTrajectory) -> None:
        self._records[trajectory.trajectory_id] = trajectory
        tenant = trajectory.tenant_id or "_unknown"
        self._tenant_index.setdefault(tenant, []).append(trajectory.trajectory_id)

    def get(self, trajectory_id: str) -> ExecutionTrajectory | None:
        return self._records.get(trajectory_id)

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[ExecutionTrajectory]:
        ids = self._tenant_index.get(tenant_id or "_unknown", [])
        return [self._records[tid] for tid in ids[-limit:] if tid in self._records]


class PostgresTrajectoryStore(TrajectoryStore):
    """PostgreSQL-backed trajectory store.

    This is the canonical durable store. It stores trajectory summaries
    and references, not raw conversation content.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn

    def save(self, trajectory: ExecutionTrajectory) -> None:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            payload = json.dumps(trajectory.to_dict(), default=str)
            db.execute(
                """
                INSERT INTO execution_trajectories (trajectory_id, tenant_id, payload, created_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (trajectory_id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    trajectory.trajectory_id,
                    trajectory.tenant_id,
                    payload,
                ),
            )
        except Exception:
            pass

    def get(self, trajectory_id: str) -> ExecutionTrajectory | None:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            row = db.fetch_one(
                "SELECT payload FROM execution_trajectories WHERE trajectory_id = %s",
                (trajectory_id,),
            )
            if not row:
                return None
            data = json.loads(row["payload"])
            return self._from_dict(data)
        except Exception:
            return None

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[ExecutionTrajectory]:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            rows = db.fetch_all(
                "SELECT payload FROM execution_trajectories WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
                (tenant_id, limit),
            )
            results = []
            for row in rows:
                try:
                    results.append(self._from_dict(json.loads(row["payload"])))
                except Exception:
                    continue
            return results
        except Exception:
            return []

    def _from_dict(self, data: dict[str, Any]) -> ExecutionTrajectory:
        return ExecutionTrajectory(
            trajectory_id=data["trajectory_id"],
            request_id=data.get("request_id"),
            correlation_id=data.get("correlation_id"),
            tenant_id=data.get("tenant_id"),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            conversation_id=data.get("conversation_id"),
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=(
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at")
                else None
            ),
            input_fingerprint=data.get("input_fingerprint"),
            intent=data.get("intent"),
            intelligence_signals=data.get("intelligence_signals", {}),
            cortex_decision=data.get("cortex_decision"),
            policy_decision_id=data.get("policy_decision_id"),
            policy_allowed_capabilities=data.get("policy_allowed_capabilities", []),
            policy_denied_capabilities=data.get("policy_denied_capabilities", []),
            prompt_id=data.get("prompt_id"),
            prompt_version=data.get("prompt_version"),
            prompt_hash=data.get("prompt_hash"),
            requested_provider=data.get("requested_provider"),
            requested_model=data.get("requested_model"),
            actual_provider=data.get("actual_provider"),
            actual_model=data.get("actual_model"),
            runtime_engine=data.get("runtime_engine"),
            provider_attempts=[
                ProviderAttempt(
                    provider=a["provider"],
                    model=a["model"],
                    runtime_engine=a["runtime_engine"],
                    started_at=datetime.fromisoformat(a["started_at"]),
                    duration_ms=a.get("duration_ms"),
                    status=a.get("status"),
                    error_code=a.get("error_code"),
                    fallback_level=a.get("fallback_level"),
                )
                for a in data.get("provider_attempts", [])
            ],
            fallback_level=data.get("fallback_level"),
            degraded_mode=data.get("degraded_mode"),
            degradation_reason=data.get("degradation_reason"),
            memory_recall_refs=data.get("memory_recall_refs", []),
            memory_recall_count=data.get("memory_recall_count"),
            plugin_actions=[
                PluginAction(
                    plugin_id=a["plugin_id"],
                    action=a["action"],
                    policy_decision_id=a.get("policy_decision_id"),
                    duration_ms=a.get("duration_ms"),
                    status=a.get("status"),
                    error_code=a.get("error_code"),
                )
                for a in data.get("plugin_actions", [])
            ],
            latencies=data.get("latencies", {}),
            execution_status=data.get("execution_status"),
            error_code=data.get("error_code"),
            response_source=data.get("response_source"),
            metadata=data.get("metadata", {}),
        )

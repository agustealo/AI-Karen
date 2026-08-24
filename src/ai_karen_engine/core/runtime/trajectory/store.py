from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from ai_karen_engine.core.runtime.trajectory.contracts import (
    ExecutionTrajectory,
    PluginAction,
    ProviderAttempt,
)
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    DecisionObservation,
    FeatureSnapshot,
)


class TrajectoryStore(ABC):
    """Abstract storage for execution trajectories and learning records."""

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

    @abstractmethod
    def save_feature_snapshot(self, snapshot: FeatureSnapshot) -> None:
        """Persist a decision-time feature snapshot (durable)."""

    @abstractmethod
    def get_feature_snapshot(
        self, feature_snapshot_id: str
    ) -> FeatureSnapshot | None:
        """Retrieve a feature snapshot by ID."""

    @abstractmethod
    def list_feature_snapshots(
        self, trajectory_id: str
    ) -> list[FeatureSnapshot]:
        """List feature snapshots bound to a trajectory."""

    @abstractmethod
    def list_feature_snapshots_for_tenant(
        self, tenant_id: str, *, limit: int = 100
    ) -> list[FeatureSnapshot]:
        """List recent feature snapshots for a tenant (tenant-isolated)."""

    @abstractmethod
    def save_decision_observation(self, observation: DecisionObservation) -> None:
        """Persist a decision observation (durable)."""

    @abstractmethod
    def get_decision_observation(
        self, decision_observation_id: str
    ) -> DecisionObservation | None:
        """Retrieve a decision observation by ID."""

    @abstractmethod
    def list_decision_observations(
        self, trajectory_id: str
    ) -> list[DecisionObservation]:
        """List decision observations bound to a trajectory."""

    @abstractmethod
    def list_decision_observations_for_tenant(
        self, tenant_id: str, *, limit: int = 100
    ) -> list[DecisionObservation]:
        """List recent decision observations for a tenant (tenant-isolated)."""


class InMemoryTrajectoryStore(TrajectoryStore):
    """Non-durable in-memory store for testing and fallback."""

    def __init__(self) -> None:
        self._records: dict[str, ExecutionTrajectory] = {}
        self._tenant_index: dict[str, list[str]] = {}

        self._feature_snapshots: dict[str, FeatureSnapshot] = {}
        self._feature_snapshot_tenant_index: dict[str, list[str]] = {}
        self._feature_snapshot_trajectory_index: dict[str, list[str]] = {}

        self._decision_observations: dict[str, DecisionObservation] = {}
        self._decision_observation_tenant_index: dict[str, list[str]] = {}
        self._decision_observation_trajectory_index: dict[str, list[str]] = {}

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

    def save_feature_snapshot(self, snapshot: FeatureSnapshot) -> None:
        self._feature_snapshots[snapshot.feature_snapshot_id] = snapshot
        tenant = snapshot.tenant_id or "_unknown"
        self._feature_snapshot_tenant_index.setdefault(tenant, []).append(
            snapshot.feature_snapshot_id
        )
        traj_key = snapshot.trajectory_id or "_unknown"
        self._feature_snapshot_trajectory_index.setdefault(traj_key, []).append(
            snapshot.feature_snapshot_id
        )

    def get_feature_snapshot(
        self, feature_snapshot_id: str
    ) -> FeatureSnapshot | None:
        return self._feature_snapshots.get(feature_snapshot_id)

    def list_feature_snapshots(self, trajectory_id: str) -> list[FeatureSnapshot]:
        ids = self._feature_snapshot_trajectory_index.get(trajectory_id, [])
        return [self._feature_snapshots[i] for i in ids if i in self._feature_snapshots]

    def list_feature_snapshots_for_tenant(
        self, tenant_id: str, *, limit: int = 100
    ) -> list[FeatureSnapshot]:
        ids = self._flatten_tenant_index(
            self._feature_snapshot_tenant_index, tenant_id
        )
        return [
            self._feature_snapshots[i]
            for i in ids[-limit:]
            if i in self._feature_snapshots
        ]

    def save_decision_observation(self, observation: DecisionObservation) -> None:
        self._decision_observations[observation.decision_observation_id] = observation
        tenant = observation.tenant_id or "_unknown"
        self._decision_observation_tenant_index.setdefault(tenant, []).append(
            observation.decision_observation_id
        )
        self._decision_observation_trajectory_index.setdefault(
            observation.trajectory_id, []
        ).append(observation.decision_observation_id)

    def get_decision_observation(
        self, decision_observation_id: str
    ) -> DecisionObservation | None:
        return self._decision_observations.get(decision_observation_id)

    def list_decision_observations(
        self, trajectory_id: str
    ) -> list[DecisionObservation]:
        ids = self._decision_observation_trajectory_index.get(trajectory_id, [])
        return [self._decision_observations[i] for i in ids if i in self._decision_observations]

    def list_decision_observations_for_tenant(
        self, tenant_id: str, *, limit: int = 100
    ) -> list[DecisionObservation]:
        ids = self._flatten_tenant_index(
            self._decision_observation_tenant_index, tenant_id
        )
        return [
            self._decision_observations[i]
            for i in ids[-limit:]
            if i in self._decision_observations
        ]

    @staticmethod
    def _flatten_tenant_index(index: dict[str, list[str]], tenant_id: str) -> list[str]:
        return index.get(tenant_id or "_unknown", [])


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

    def save_feature_snapshot(self, snapshot: FeatureSnapshot) -> None:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            payload = json.dumps(snapshot.to_dict(), default=str)
            db.execute(
                """
                INSERT INTO feature_snapshots
                    (feature_snapshot_id, trajectory_id, tenant_id, payload, created_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (feature_snapshot_id)
                DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    snapshot.feature_snapshot_id,
                    snapshot.trajectory_id,
                    snapshot.tenant_id,
                    payload,
                ),
            )
        except Exception:
            pass

    def get_feature_snapshot(
        self, feature_snapshot_id: str
    ) -> FeatureSnapshot | None:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            row = db.fetch_one(
                "SELECT payload FROM feature_snapshots WHERE feature_snapshot_id = %s",
                (feature_snapshot_id,),
            )
            if not row:
                return None
            return FeatureSnapshot.from_dict(json.loads(row["payload"]))
        except Exception:
            return None

    def list_feature_snapshots(self, trajectory_id: str) -> list[FeatureSnapshot]:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            rows = db.fetch_all(
                "SELECT payload FROM feature_snapshots WHERE trajectory_id = %s",
                (trajectory_id,),
            )
            return [FeatureSnapshot.from_dict(json.loads(r["payload"])) for r in rows]
        except Exception:
            return []

    def list_feature_snapshots_for_tenant(
        self, tenant_id: str, *, limit: int = 100
    ) -> list[FeatureSnapshot]:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            rows = db.fetch_all(
                """
                SELECT payload FROM feature_snapshots
                WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s
                """,
                (tenant_id, limit),
            )
            return [FeatureSnapshot.from_dict(json.loads(r["payload"])) for r in rows]
        except Exception:
            return []

    def save_decision_observation(self, observation: DecisionObservation) -> None:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            payload = json.dumps(observation.to_dict(), default=str)
            db.execute(
                """
                INSERT INTO decision_observations
                    (decision_observation_id, trajectory_id, tenant_id, payload, created_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (decision_observation_id)
                DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    observation.decision_observation_id,
                    observation.trajectory_id,
                    observation.tenant_id,
                    payload,
                ),
            )
        except Exception:
            pass

    def get_decision_observation(
        self, decision_observation_id: str
    ) -> DecisionObservation | None:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            row = db.fetch_one(
                "SELECT payload FROM decision_observations WHERE decision_observation_id = %s",
                (decision_observation_id,),
            )
            if not row:
                return None
            return DecisionObservation.from_dict(json.loads(row["payload"]))
        except Exception:
            return None

    def list_decision_observations(
        self, trajectory_id: str
    ) -> list[DecisionObservation]:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            rows = db.fetch_all(
                "SELECT payload FROM decision_observations WHERE trajectory_id = %s",
                (trajectory_id,),
            )
            return [
                DecisionObservation.from_dict(json.loads(r["payload"])) for r in rows
            ]
        except Exception:
            return []

    def list_decision_observations_for_tenant(
        self, tenant_id: str, *, limit: int = 100
    ) -> list[DecisionObservation]:
        try:
            import json

            from ai_karen_engine.database.connection import get_database_connection

            db = get_database_connection(self._dsn)
            rows = db.fetch_all(
                """
                SELECT payload FROM decision_observations
                WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s
                """,
                (tenant_id, limit),
            )
            return [
                DecisionObservation.from_dict(json.loads(r["payload"])) for r in rows
            ]
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
            executed_topology=data.get("executed_topology"),
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
            feature_snapshot_refs=data.get("feature_snapshot_refs", []),
            decision_observation_refs=data.get("decision_observation_refs", []),
            metadata=data.get("metadata", {}),
        )

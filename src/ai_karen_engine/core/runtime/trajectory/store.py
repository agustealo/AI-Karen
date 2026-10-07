from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import (
    async_transaction_scope,
    transaction_scope,
)

logger = logging.getLogger(__name__)

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

    async def save_async(self, trajectory: ExecutionTrajectory) -> None:
        await asyncio.to_thread(self.save, trajectory)

    @abstractmethod
    def get(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ExecutionTrajectory | None:
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

    async def save_feature_snapshot_async(self, snapshot: FeatureSnapshot) -> None:
        await asyncio.to_thread(self.save_feature_snapshot, snapshot)

    @abstractmethod
    def get_feature_snapshot(
        self,
        feature_snapshot_id: str,
        *,
        tenant_id: str | None = None,
    ) -> FeatureSnapshot | None:
        """Retrieve a feature snapshot by ID."""

    @abstractmethod
    def list_feature_snapshots(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
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

    async def save_decision_observation_async(
        self,
        observation: DecisionObservation,
    ) -> None:
        await asyncio.to_thread(self.save_decision_observation, observation)

    @abstractmethod
    def get_decision_observation(
        self,
        decision_observation_id: str,
        *,
        tenant_id: str | None = None,
    ) -> DecisionObservation | None:
        """Retrieve a decision observation by ID."""

    @abstractmethod
    def list_decision_observations(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
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
        ids = self._tenant_index.setdefault(tenant, [])
        if trajectory.trajectory_id not in ids:
            ids.append(trajectory.trajectory_id)

    def get(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ExecutionTrajectory | None:
        trajectory = self._records.get(trajectory_id)
        if trajectory is None:
            return None
        if tenant_id is not None and trajectory.tenant_id != tenant_id:
            return None
        return trajectory

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
        self,
        feature_snapshot_id: str,
        *,
        tenant_id: str | None = None,
    ) -> FeatureSnapshot | None:
        snapshot = self._feature_snapshots.get(feature_snapshot_id)
        if snapshot is None:
            return None
        if tenant_id is not None and snapshot.tenant_id != tenant_id:
            return None
        return snapshot

    def list_feature_snapshots(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[FeatureSnapshot]:
        ids = self._feature_snapshot_trajectory_index.get(trajectory_id, [])
        snapshots = [
            self._feature_snapshots[i]
            for i in ids
            if i in self._feature_snapshots
        ]
        if tenant_id is not None:
            snapshots = [item for item in snapshots if item.tenant_id == tenant_id]
        return snapshots

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
        self,
        decision_observation_id: str,
        *,
        tenant_id: str | None = None,
    ) -> DecisionObservation | None:
        observation = self._decision_observations.get(decision_observation_id)
        if observation is None:
            return None
        if tenant_id is not None and observation.tenant_id != tenant_id:
            return None
        return observation

    def list_decision_observations(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[DecisionObservation]:
        ids = self._decision_observation_trajectory_index.get(trajectory_id, [])
        observations = [
            self._decision_observations[i]
            for i in ids
            if i in self._decision_observations
        ]
        if tenant_id is not None:
            observations = [
                item for item in observations if item.tenant_id == tenant_id
            ]
        return observations

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


class TrajectoryStoreError(RuntimeError):
    """Durable trajectory/learning-lineage persistence failed."""


class PostgresTrajectoryStore(TrajectoryStore):
    """Canonical PostgreSQL-backed learning-lineage store."""

    @staticmethod
    def _require_tenant(tenant_id: str | None) -> str:
        tenant = str(tenant_id or "").strip()
        if not tenant or tenant == "default":
            raise TrajectoryStoreError(
                "explicit non-default tenant_id is required for learning lineage"
            )
        return tenant

    @staticmethod
    def _bounded_limit(limit: int) -> int:
        return max(1, min(int(limit), 100_000))

    @staticmethod
    def _payload(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        raise TrajectoryStoreError("stored learning-lineage payload is not an object")

    @staticmethod
    def _normalize_datetime(value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            if normalized.endswith("Z"):
                normalized = f"{normalized[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise TrajectoryStoreError(
                    "learning timestamp must be an ISO-8601 value"
                ) from exc
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        raise TrajectoryStoreError(
            "learning timestamp must be a datetime, ISO-8601 string, or null"
        )

    @staticmethod
    def _trajectory_params(
        trajectory: ExecutionTrajectory,
        tenant_id: str,
    ) -> dict[str, Any]:
        return {
            "trajectory_id": trajectory.trajectory_id,
            "request_id": trajectory.request_id,
            "correlation_id": trajectory.correlation_id,
            "conversation_id": trajectory.conversation_id,
            "session_id": trajectory.session_id,
            "tenant_id": tenant_id,
            "user_id": str(trajectory.user_id or ""),
            "started_at": PostgresTrajectoryStore._normalize_datetime(
                trajectory.started_at
            ),
            "completed_at": PostgresTrajectoryStore._normalize_datetime(
                trajectory.completed_at
            ),
            "execution_status": trajectory.execution_status,
            "policy_decision_id": trajectory.policy_decision_id,
            "payload": json.dumps(trajectory.to_dict(), default=str),
        }

    @staticmethod
    def _trajectory_upsert():
        return text(
            """
            INSERT INTO public.execution_trajectories (
                trajectory_id, request_id, correlation_id, conversation_id,
                session_id, tenant_id, user_id, started_at, completed_at,
                execution_status, policy_decision_id, payload, created_at, updated_at
            ) VALUES (
                :trajectory_id, :request_id, :correlation_id, :conversation_id,
                :session_id, CAST(:tenant_id AS uuid), NULLIF(:user_id, '')::uuid,
                CAST(:started_at AS timestamptz), CAST(:completed_at AS timestamptz),
                :execution_status, :policy_decision_id, CAST(:payload AS jsonb),
                now(), now()
            )
            ON CONFLICT (trajectory_id) DO UPDATE SET
                request_id = EXCLUDED.request_id,
                correlation_id = EXCLUDED.correlation_id,
                conversation_id = EXCLUDED.conversation_id,
                session_id = EXCLUDED.session_id,
                user_id = EXCLUDED.user_id,
                completed_at = EXCLUDED.completed_at,
                execution_status = EXCLUDED.execution_status,
                policy_decision_id = EXCLUDED.policy_decision_id,
                payload = EXCLUDED.payload,
                updated_at = now()
            """
        )

    def save(self, trajectory: ExecutionTrajectory) -> None:
        tenant = self._require_tenant(trajectory.tenant_id)
        try:
            with transaction_scope(tenant) as session:
                session.execute(
                    self._trajectory_upsert(),
                    self._trajectory_params(trajectory, tenant),
                )
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.trajectory.save_failed",
                extra={"trajectory_id": trajectory.trajectory_id, "tenant_id": tenant},
            )
            raise TrajectoryStoreError("trajectory persistence failed") from exc

    async def save_async(self, trajectory: ExecutionTrajectory) -> None:
        tenant = self._require_tenant(trajectory.tenant_id)
        try:
            async with async_transaction_scope(tenant) as session:
                await session.execute(
                    self._trajectory_upsert(),
                    self._trajectory_params(trajectory, tenant),
                )
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.trajectory.async_save_failed",
                extra={"trajectory_id": trajectory.trajectory_id, "tenant_id": tenant},
            )
            raise TrajectoryStoreError("trajectory persistence failed") from exc

    def get(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ExecutionTrajectory | None:
        tenant = self._require_tenant(tenant_id)
        try:
            with transaction_scope(tenant) as session:
                row = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.execution_trajectories
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND trajectory_id = :trajectory_id
                        """
                    ),
                    {"tenant_id": tenant, "trajectory_id": trajectory_id},
                ).mappings().first()
            return None if row is None else self._from_dict(self._payload(row["payload"]))
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.trajectory.read_failed",
                extra={"trajectory_id": trajectory_id, "tenant_id": tenant},
            )
            raise TrajectoryStoreError("trajectory retrieval failed") from exc

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[ExecutionTrajectory]:
        tenant = self._require_tenant(tenant_id)
        try:
            with transaction_scope(tenant) as session:
                rows = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.execution_trajectories
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                        ORDER BY started_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"tenant_id": tenant, "limit": self._bounded_limit(limit)},
                ).mappings().all()
            return [self._from_dict(self._payload(row["payload"])) for row in rows]
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.trajectory.list_failed",
                extra={"tenant_id": tenant},
            )
            raise TrajectoryStoreError("trajectory tenant retrieval failed") from exc

    @staticmethod
    def _feature_params(
        snapshot: FeatureSnapshot,
        tenant_id: str,
    ) -> dict[str, Any]:
        return {
            "feature_snapshot_id": snapshot.feature_snapshot_id,
            "trajectory_id": snapshot.trajectory_id,
            "request_id": snapshot.request_id,
            "correlation_id": snapshot.correlation_id,
            "tenant_id": tenant_id,
            "user_id": str(snapshot.user_id or ""),
            "feature_version": snapshot.feature_version,
            "created_at": PostgresTrajectoryStore._normalize_datetime(
                snapshot.created_at
            ),
            "payload": json.dumps(snapshot.to_dict(), default=str),
        }

    @staticmethod
    def _feature_insert():
        return text(
            """
            INSERT INTO public.feature_snapshots (
                feature_snapshot_id, trajectory_id, request_id, correlation_id,
                tenant_id, user_id, feature_version, created_at, payload
            ) VALUES (
                :feature_snapshot_id, :trajectory_id, :request_id, :correlation_id,
                CAST(:tenant_id AS uuid), NULLIF(:user_id, '')::uuid,
                :feature_version, CAST(:created_at AS timestamptz),
                CAST(:payload AS jsonb)
            )
            ON CONFLICT (feature_snapshot_id) DO NOTHING
            """
        )

    def save_feature_snapshot(self, snapshot: FeatureSnapshot) -> None:
        tenant = self._require_tenant(snapshot.tenant_id)
        if not snapshot.trajectory_id:
            raise TrajectoryStoreError("feature snapshot requires trajectory_id")
        try:
            with transaction_scope(tenant) as session:
                session.execute(
                    self._feature_insert(),
                    self._feature_params(snapshot, tenant),
                )
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.feature_snapshot.save_failed",
                extra={
                    "feature_snapshot_id": snapshot.feature_snapshot_id,
                    "tenant_id": tenant,
                },
            )
            raise TrajectoryStoreError("feature snapshot persistence failed") from exc

    async def save_feature_snapshot_async(self, snapshot: FeatureSnapshot) -> None:
        tenant = self._require_tenant(snapshot.tenant_id)
        if not snapshot.trajectory_id:
            raise TrajectoryStoreError("feature snapshot requires trajectory_id")
        try:
            async with async_transaction_scope(tenant) as session:
                await session.execute(
                    self._feature_insert(),
                    self._feature_params(snapshot, tenant),
                )
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.feature_snapshot.async_save_failed",
                extra={
                    "feature_snapshot_id": snapshot.feature_snapshot_id,
                    "tenant_id": tenant,
                },
            )
            raise TrajectoryStoreError("feature snapshot persistence failed") from exc

    def get_feature_snapshot(
        self,
        feature_snapshot_id: str,
        *,
        tenant_id: str | None = None,
    ) -> FeatureSnapshot | None:
        tenant = self._require_tenant(tenant_id)
        try:
            with transaction_scope(tenant) as session:
                row = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.feature_snapshots
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND feature_snapshot_id = :feature_snapshot_id
                        """
                    ),
                    {"tenant_id": tenant, "feature_snapshot_id": feature_snapshot_id},
                ).mappings().first()
            return None if row is None else FeatureSnapshot.from_dict(self._payload(row["payload"]))
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.feature_snapshot.read_failed",
                extra={"feature_snapshot_id": feature_snapshot_id, "tenant_id": tenant},
            )
            raise TrajectoryStoreError("feature snapshot retrieval failed") from exc

    def list_feature_snapshots(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[FeatureSnapshot]:
        tenant = self._require_tenant(tenant_id)
        try:
            with transaction_scope(tenant) as session:
                rows = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.feature_snapshots
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND trajectory_id = :trajectory_id
                        ORDER BY created_at ASC
                        """
                    ),
                    {"tenant_id": tenant, "trajectory_id": trajectory_id},
                ).mappings().all()
            return [FeatureSnapshot.from_dict(self._payload(row["payload"])) for row in rows]
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.feature_snapshot.list_failed",
                extra={"trajectory_id": trajectory_id, "tenant_id": tenant},
            )
            raise TrajectoryStoreError("feature snapshot list failed") from exc

    def list_feature_snapshots_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[FeatureSnapshot]:
        tenant = self._require_tenant(tenant_id)
        try:
            with transaction_scope(tenant) as session:
                rows = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.feature_snapshots
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                        ORDER BY created_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"tenant_id": tenant, "limit": self._bounded_limit(limit)},
                ).mappings().all()
            return [FeatureSnapshot.from_dict(self._payload(row["payload"])) for row in rows]
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.feature_snapshot.tenant_list_failed",
                extra={"tenant_id": tenant},
            )
            raise TrajectoryStoreError("feature snapshot tenant retrieval failed") from exc

    @staticmethod
    def _decision_params(
        observation: DecisionObservation,
        tenant_id: str,
    ) -> dict[str, Any]:
        return {
            "decision_observation_id": observation.decision_observation_id,
            "trajectory_id": observation.trajectory_id,
            "feature_snapshot_id": observation.feature_snapshot_id,
            "tenant_id": tenant_id,
            "user_id": str(observation.user_id or ""),
            "decision_type": observation.decision_type,
            "behavior_policy_id": observation.behavior_policy_id,
            "behavior_policy_version": observation.behavior_policy_version,
            "chosen_action": observation.chosen_action,
            "ope_eligible": observation.ope_eligible,
            "created_at": PostgresTrajectoryStore._normalize_datetime(
                observation.created_at
            ),
            "payload": json.dumps(observation.to_dict(), default=str),
        }

    @staticmethod
    def _decision_insert():
        return text(
            """
            INSERT INTO public.decision_observations (
                decision_observation_id, trajectory_id, feature_snapshot_id,
                tenant_id, user_id, decision_type, behavior_policy_id,
                behavior_policy_version, chosen_action, ope_eligible,
                created_at, payload
            ) VALUES (
                :decision_observation_id, :trajectory_id, :feature_snapshot_id,
                CAST(:tenant_id AS uuid), NULLIF(:user_id, '')::uuid,
                :decision_type, :behavior_policy_id, :behavior_policy_version,
                :chosen_action, :ope_eligible, CAST(:created_at AS timestamptz),
                CAST(:payload AS jsonb)
            )
            ON CONFLICT (decision_observation_id) DO NOTHING
            """
        )

    def save_decision_observation(self, observation: DecisionObservation) -> None:
        tenant = self._require_tenant(observation.tenant_id)
        try:
            with transaction_scope(tenant) as session:
                session.execute(
                    self._decision_insert(),
                    self._decision_params(observation, tenant),
                )
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.decision_observation.save_failed",
                extra={
                    "decision_observation_id": observation.decision_observation_id,
                    "tenant_id": tenant,
                },
            )
            raise TrajectoryStoreError("decision observation persistence failed") from exc

    async def save_decision_observation_async(
        self,
        observation: DecisionObservation,
    ) -> None:
        tenant = self._require_tenant(observation.tenant_id)
        try:
            async with async_transaction_scope(tenant) as session:
                await session.execute(
                    self._decision_insert(),
                    self._decision_params(observation, tenant),
                )
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.decision_observation.async_save_failed",
                extra={
                    "decision_observation_id": observation.decision_observation_id,
                    "tenant_id": tenant,
                },
            )
            raise TrajectoryStoreError("decision observation persistence failed") from exc

    def get_decision_observation(
        self,
        decision_observation_id: str,
        *,
        tenant_id: str | None = None,
    ) -> DecisionObservation | None:
        tenant = self._require_tenant(tenant_id)
        try:
            with transaction_scope(tenant) as session:
                row = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.decision_observations
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND decision_observation_id = :decision_observation_id
                        """
                    ),
                    {
                        "tenant_id": tenant,
                        "decision_observation_id": decision_observation_id,
                    },
                ).mappings().first()
            return None if row is None else DecisionObservation.from_dict(self._payload(row["payload"]))
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.decision_observation.read_failed",
                extra={
                    "decision_observation_id": decision_observation_id,
                    "tenant_id": tenant,
                },
            )
            raise TrajectoryStoreError("decision observation retrieval failed") from exc

    def list_decision_observations(
        self,
        trajectory_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[DecisionObservation]:
        tenant = self._require_tenant(tenant_id)
        try:
            with transaction_scope(tenant) as session:
                rows = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.decision_observations
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND trajectory_id = :trajectory_id
                        ORDER BY created_at ASC
                        """
                    ),
                    {"tenant_id": tenant, "trajectory_id": trajectory_id},
                ).mappings().all()
            return [
                DecisionObservation.from_dict(self._payload(row["payload"]))
                for row in rows
            ]
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.decision_observation.list_failed",
                extra={"trajectory_id": trajectory_id, "tenant_id": tenant},
            )
            raise TrajectoryStoreError("decision observation list failed") from exc

    def list_decision_observations_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[DecisionObservation]:
        tenant = self._require_tenant(tenant_id)
        try:
            with transaction_scope(tenant) as session:
                rows = session.execute(
                    text(
                        """
                        SELECT payload
                        FROM public.decision_observations
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                        ORDER BY created_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"tenant_id": tenant, "limit": self._bounded_limit(limit)},
                ).mappings().all()
            return [
                DecisionObservation.from_dict(self._payload(row["payload"]))
                for row in rows
            ]
        except TrajectoryStoreError:
            raise
        except Exception as exc:
            logger.exception(
                "learning.decision_observation.tenant_list_failed",
                extra={"tenant_id": tenant},
            )
            raise TrajectoryStoreError("decision observation tenant retrieval failed") from exc

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> ExecutionTrajectory:
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


_trajectory_store: TrajectoryStore | None = None


def get_trajectory_store() -> TrajectoryStore:
    """Return the canonical durable runtime learning-lineage store."""
    global _trajectory_store
    if _trajectory_store is None:
        _trajectory_store = PostgresTrajectoryStore()
    return _trajectory_store


def set_trajectory_store(store: TrajectoryStore | None) -> None:
    """Install an explicit store for tests/application composition."""
    global _trajectory_store
    _trajectory_store = store


__all__ = [
    "InMemoryTrajectoryStore",
    "PostgresTrajectoryStore",
    "TrajectoryStore",
    "TrajectoryStoreError",
    "get_trajectory_store",
    "set_trajectory_store",
]

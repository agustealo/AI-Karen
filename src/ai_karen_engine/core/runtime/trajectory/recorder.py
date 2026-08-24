from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ai_karen_engine.core.observability import RuntimeEventType
from ai_karen_engine.core.observability import emit as _emit_event
from ai_karen_engine.core.observability.context import get_observability_context
from ai_karen_engine.core.runtime.trajectory.contracts import (
    ExecutionTrajectory,
    PluginAction,
    ProviderAttempt,
)
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    CORTEX_TOPOLOGY_POLICY_ID,
    CORTEX_TOPOLOGY_POLICY_VERSION,
    DecisionObservation,
    FeatureSnapshot,
    create_decision_observation,
    create_feature_snapshot,
)


class TrajectoryRecorder:
    """Builds and finalizes ExecutionTrajectory records.

    This component is observational only. It does not change runtime behavior.
    """

    def __init__(self, store: Any | None = None) -> None:
        self._store = store

    def start(self, *, input_fingerprint: str | None = None) -> ExecutionTrajectory:
        """Begin a new trajectory for the current request."""
        ctx = get_observability_context()
        return ExecutionTrajectory(
            trajectory_id=f"traj_{uuid.uuid4().hex}",
            request_id=ctx.request_id,
            correlation_id=ctx.correlation_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            conversation_id=ctx.conversation_id,
            input_fingerprint=input_fingerprint,
        )

    def record_provider_attempt(
        self,
        trajectory: ExecutionTrajectory,
        *,
        provider: str,
        model: str,
        runtime_engine: str,
        status: str | None = None,
        error_code: str | None = None,
        duration_ms: float | None = None,
        fallback_level: int | None = None,
    ) -> None:
        """Append a provider attempt to the trajectory."""
        trajectory.provider_attempts.append(
            ProviderAttempt(
                provider=provider,
                model=model,
                runtime_engine=runtime_engine,
                started_at=datetime.utcnow(),
                duration_ms=duration_ms,
                status=status,
                error_code=error_code,
                fallback_level=fallback_level,
            )
        )
        if provider:
            trajectory.actual_provider = provider
        if model:
            trajectory.actual_model = model
        if runtime_engine:
            trajectory.runtime_engine = runtime_engine

    def record_plugin_action(
        self,
        trajectory: ExecutionTrajectory,
        *,
        plugin_id: str,
        action: str,
        policy_decision_id: str | None = None,
        duration_ms: float | None = None,
        status: str | None = None,
        error_code: str | None = None,
    ) -> None:
        """Append a plugin/tool execution to the trajectory."""
        trajectory.plugin_actions.append(
            PluginAction(
                plugin_id=plugin_id,
                action=action,
                policy_decision_id=policy_decision_id,
                duration_ms=duration_ms,
                status=status,
                error_code=error_code,
            )
        )

    def complete(
        self,
        trajectory: ExecutionTrajectory,
        *,
        execution_status: str,
        error_code: str | None = None,
        response_source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionTrajectory:
        """Finalize the trajectory and optionally persist it."""
        trajectory.completed_at = datetime.utcnow()
        trajectory.execution_status = execution_status
        trajectory.error_code = error_code
        trajectory.response_source = response_source
        if metadata:
            trajectory.metadata.update(metadata)
        if self._store is not None:
            try:
                self._store.save(trajectory)
            except Exception:
                pass
        return trajectory

    def build_feature_snapshot(
        self,
        trajectory: ExecutionTrajectory,
        *,
        feature_version: str,
        intent: str | None = None,
        intent_confidence: float | None = None,
        domain: str | None = None,
        complexity: str | None = None,
        ambiguity: float | None = None,
        memory_relevance: float | None = None,
        capability_hints: dict[str, Any] | None = None,
        topology_signals: dict[str, Any] | None = None,
        risk_signals: dict[str, Any] | None = None,
        runtime_capabilities: dict[str, Any] | None = None,
        provider_health_snapshot: dict[str, Any] | None = None,
        resource_snapshot: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FeatureSnapshot:
        """Build an immutable, secret-sanitized feature snapshot for a trajectory."""
        return create_feature_snapshot(
            trajectory,
            feature_version=feature_version,
            intent=intent if intent is not None else trajectory.intent,
            intent_confidence=intent_confidence,
            domain=domain,
            complexity=complexity,
            ambiguity=ambiguity,
            memory_relevance=memory_relevance,
            capability_hints=capability_hints,
            topology_signals=topology_signals,
            risk_signals=risk_signals,
            runtime_capabilities=runtime_capabilities,
            provider_health_snapshot=provider_health_snapshot,
            resource_snapshot=resource_snapshot,
            metadata=metadata,
        )

    def record_feature_snapshot(
        self,
        trajectory: ExecutionTrajectory,
        *,
        feature_snapshot: FeatureSnapshot,
    ) -> FeatureSnapshot:
        """Persist a feature snapshot and link it to the trajectory.

        Chat must still succeed even if learning persistence fails: we emit
        ``learning_recording_failed`` and never claim ``learning_recorded``.
        """
        if feature_snapshot.trajectory_id != trajectory.trajectory_id:
            raise ValueError("feature snapshot trajectory_id does not match trajectory")
        if feature_snapshot.feature_snapshot_id not in trajectory.feature_snapshot_refs:
            trajectory.feature_snapshot_refs.append(feature_snapshot.feature_snapshot_id)
        status = "success"
        try:
            if self._store is not None:
                self._store.save_feature_snapshot(feature_snapshot)
        except Exception:
            status = "failed"
            _emit_event(
                RuntimeEventType.LEARNING_RECORDING_FAILED,
                metadata={
                    "kind": "feature_snapshot",
                    "trajectory_id": trajectory.trajectory_id,
                    "feature_snapshot_id": feature_snapshot.feature_snapshot_id,
                },
            )
        _emit_event(
            RuntimeEventType.LEARNING_FEATURE_SNAPSHOT_RECORDED,
            status=status,
            tenant_scope=feature_snapshot.tenant_id,
            metadata={
                "trajectory_id": trajectory.trajectory_id,
                "feature_snapshot_id": feature_snapshot.feature_snapshot_id,
                "feature_version": feature_snapshot.feature_version,
            },
        )
        return feature_snapshot

    def build_decision_observation(
        self,
        trajectory: ExecutionTrajectory,
        *,
        feature_snapshot_id: str,
        decision_type: str,
        behavior_policy_id: str = CORTEX_TOPOLOGY_POLICY_ID,
        behavior_policy_version: str = CORTEX_TOPOLOGY_POLICY_VERSION,
        candidate_actions: tuple[str, ...] | list[str],
        eligible_actions: tuple[str, ...] | list[str],
        chosen_action: str,
        chosen_probability: float | None = None,
        action_probabilities: dict[str, float] | None = None,
        decision_id: str | None = None,
        ope_eligible: bool | None = None,
        ope_ineligible_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionObservation:
        """Build a validated decision observation bound to the trajectory."""
        return create_decision_observation(
            trajectory_id=trajectory.trajectory_id,
            feature_snapshot_id=feature_snapshot_id,
            decision_type=decision_type,
            behavior_policy_id=behavior_policy_id,
            behavior_policy_version=behavior_policy_version,
            candidate_actions=candidate_actions,
            eligible_actions=eligible_actions,
            chosen_action=chosen_action,
            chosen_probability=chosen_probability,
            action_probabilities=action_probabilities,
            decision_id=decision_id,
            ope_eligible=ope_eligible,
            ope_ineligible_reason=ope_ineligible_reason,
            tenant_id=trajectory.tenant_id,
            user_id=trajectory.user_id,
            metadata=metadata,
        )

    def record_decision_observation(
        self,
        trajectory: ExecutionTrajectory,
        *,
        decision_observation: DecisionObservation,
    ) -> DecisionObservation:
        """Persist a decision observation and link it to the trajectory."""
        if decision_observation.trajectory_id != trajectory.trajectory_id:
            raise ValueError("decision observation trajectory_id does not match trajectory")
        if (
            decision_observation.decision_observation_id
            not in trajectory.decision_observation_refs
        ):
            trajectory.decision_observation_refs.append(
                decision_observation.decision_observation_id
            )
        status = "success"
        try:
            if self._store is not None:
                self._store.save_decision_observation(decision_observation)
        except Exception:
            status = "failed"
            _emit_event(
                RuntimeEventType.LEARNING_RECORDING_FAILED,
                metadata={
                    "kind": "decision_observation",
                    "trajectory_id": trajectory.trajectory_id,
                    "decision_observation_id": decision_observation.decision_observation_id,
                },
            )
        _emit_event(
            RuntimeEventType.LEARNING_DECISION_OBSERVATION_RECORDED,
            status=status,
            tenant_scope=decision_observation.tenant_id,
            metadata={
                "trajectory_id": trajectory.trajectory_id,
                "decision_observation_id": decision_observation.decision_observation_id,
                "decision_type": decision_observation.decision_type,
                "chosen_action": decision_observation.chosen_action,
                "ope_eligible": decision_observation.ope_eligible,
            },
        )
        return decision_observation

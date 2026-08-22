from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ai_karen_engine.core.observability.context import get_observability_context
from ai_karen_engine.core.runtime.trajectory.contracts import (
    ExecutionTrajectory,
    PluginAction,
    ProviderAttempt,
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

"""KCOG-01C1B2C3C: read back one real authenticated, durable strategy outcome.

Run only inside the disposable production first-boot/Ollama CI API container
after the existing authenticated /api/chat call. This module never performs
inference, chooses a response strategy, writes learning evidence, or grants OPE.
It reads the original canonical owners and reports only bounded result codes.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from typing import Any

from sqlalchemy import text

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    get_conversation_runtime_gateway,
)
from ai_karen_engine.core.runtime.outcome.store import PostgresOutcomeStore
from ai_karen_engine.core.runtime.trajectory.store import PostgresTrajectoryStore
from ai_karen_engine.persistence.postgres.transactions import transaction_scope


class DurableLineageProofError(RuntimeError):
    """A required durable runtime fact is absent or contradictory."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise DurableLineageProofError(code)


def verify_persisted_chain(
    *,
    trajectory: Any,
    decisions: list[Any],
    feature: Any,
    outcomes: list[dict[str, Any]],
    snapshot: Any,
    tenant_id: str,
    user_id: str,
    session_id: str,
    model: str,
) -> dict[str, Any]:
    """Validate existing PostgreSQL and conversation-owner records only.

    This deliberately accepts deserialized canonical records, making negative
    source tests independent of any database fixture or fabricated live model.
    """
    require(
        trajectory is not None
        and trajectory.tenant_id == tenant_id
        and trajectory.user_id == user_id
        and trajectory.session_id == session_id
        and trajectory.request_id
        and trajectory.correlation_id
        and trajectory.conversation_id
        and trajectory.policy_decision_id
        and trajectory.execution_status == "success"
        and trajectory.completed_at is not None
        and trajectory.error_code is None
        and trajectory.degraded_mode is False
        and trajectory.fallback_level == 0
        and trajectory.actual_provider in {"ollama", "ollama-local"}
        and trajectory.actual_model == model
        and not trajectory.plugin_actions,
        "trajectory_scope_or_execution_unverified",
    )
    require(
        snapshot is not None
        and snapshot.conversation is not None
        and str(snapshot.conversation.id) == trajectory.conversation_id
        and str(snapshot.conversation.tenant_id) == tenant_id
        and str(snapshot.conversation.user_id) == user_id
        and str(snapshot.conversation.session_id) == session_id,
        "canonical_conversation_scope_mismatch",
    )
    messages = tuple(snapshot.messages)
    require(
        len(messages) == 2
        and [message.role for message in messages] == ["user", "assistant"]
        and all(
            isinstance(message.content, str)
            and bool(message.content.strip())
            and str(message.conversation_id) == trajectory.conversation_id
            and str(message.tenant_id) == tenant_id
            for message in messages
        ),
        "committed_transcript_pair_missing",
    )
    for message, role in zip(messages, ("user", "assistant")):
        metadata = message.metadata
        require(
            isinstance(metadata, dict)
            and metadata.get("request_id") == trajectory.request_id
            and metadata.get("correlation_id") == trajectory.correlation_id
            and metadata.get("session_id") == session_id
            and metadata.get("conversation_id") == trajectory.conversation_id
            and metadata.get("authorized_user_id") == user_id
            and metadata.get("transcript_actor") == role,
            "committed_transcript_identity_mismatch",
        )
    require(
        messages[1].metadata.get("trajectory_id") == trajectory.trajectory_id
        and messages[1].metadata.get("actual_provider") == trajectory.actual_provider
        and messages[1].metadata.get("actual_model") == trajectory.actual_model
        and messages[1].metadata.get("fallback_level") == 0
        and messages[1].metadata.get("degraded_mode") is False,
        "committed_transcript_trajectory_mismatch",
    )

    strategies = [d for d in decisions if d.decision_type == "respond_strategy"]
    topologies = [d for d in decisions if d.decision_type == "execution_topology"]
    require(
        len(strategies) == len(topologies) == 1,
        "original_decision_lineage_ambiguous",
    )
    strategy, topology = strategies[0], topologies[0]
    require(
        strategy.tenant_id == tenant_id
        and strategy.user_id == user_id
        and strategy.trajectory_id == topology.trajectory_id == trajectory.trajectory_id
        and strategy.feature_snapshot_id == topology.feature_snapshot_id
        and strategy.decision_id == trajectory.policy_decision_id
        and strategy.chosen_action in {"respond_direct", "verify_then_respond"}
        and topology.chosen_action == trajectory.executed_topology
        and trajectory.executed_topology == (
            "direct" if strategy.chosen_action == "respond_direct"
            else "reasoning"
        )
        and strategy.eligible_actions == (strategy.chosen_action,)
        and strategy.ope_eligible is False
        and strategy.chosen_probability is None
        and not strategy.action_probabilities,
        "original_strategy_not_proven_or_ope_ineligible",
    )
    require(
        feature is not None
        and feature.feature_snapshot_id == strategy.feature_snapshot_id
        and feature.trajectory_id == trajectory.trajectory_id
        and feature.tenant_id == tenant_id
        and feature.user_id == user_id
        and feature.request_id == trajectory.request_id
        and feature.correlation_id == trajectory.correlation_id
        and feature.metadata.get("policy_decision_id") == trajectory.policy_decision_id,
        "original_feature_snapshot_scope_mismatch",
    )
    original_link = (trajectory.metadata or {}).get(
        "selected_strategy_decision_observation_v1",
    )
    require(
        isinstance(original_link, dict)
        and original_link.get("schema_version")
        == "selected_strategy_decision_observation_v1"
        and original_link.get("decision_observation_id")
        == strategy.decision_observation_id
        and original_link.get("trajectory_id") == trajectory.trajectory_id
        and original_link.get("feature_snapshot_id") == feature.feature_snapshot_id
        and original_link.get("policy_decision_id") == trajectory.policy_decision_id
        and original_link.get("policy_version") == strategy.behavior_policy_version
        and original_link.get("selected_action") == strategy.chosen_action
        and original_link.get("ope_eligible") is False,
        "persisted_strategy_reference_mismatch",
    )

    selected = [
        o for o in outcomes
        if isinstance(o, dict) and o.get("source") == "runtime.execution"
    ]
    require(
        len(selected) == 1
        and not any(
            isinstance(o, dict) and o.get("source") == "intelligence.ml"
            for o in outcomes
        ),
        "execution_or_review_receipt_ambiguous",
    )
    outcome = selected[0]
    metadata = outcome.get("metadata")
    execution = (
        metadata.get("selected_strategy_execution")
        if isinstance(metadata, dict) else None
    )
    require(
        outcome.get("trajectory_id") == trajectory.trajectory_id
        and outcome.get("decision_observation_id")
        == strategy.decision_observation_id
        and outcome.get("tenant_id") == tenant_id
        and outcome.get("user_id") == user_id
        and outcome.get("request_id") == trajectory.request_id
        and outcome.get("correlation_id") == trajectory.correlation_id
        and outcome.get("session_id") == session_id
        and outcome.get("conversation_id") == trajectory.conversation_id
        and outcome.get("status") == "success"
        and outcome.get("response_completed") is True
        and outcome.get("persistence_success") is True
        and outcome.get("fallback_count") == 0,
        "selected_execution_outcome_scope_mismatch",
    )
    require(
        isinstance(metadata, dict)
        and metadata.get("topology_decision_observation_id")
        == topology.decision_observation_id
        and metadata.get("transcript_persistence_status")
        in {"persisted", "already_persisted"}
        and metadata.get("actual_provider") == trajectory.actual_provider
        and metadata.get("actual_model") == model
        and type(metadata.get("model_calls")) is int
        and metadata["model_calls"] > 0
        and metadata.get("tool_calls") == 0
        and isinstance(execution, dict)
        and execution.get("schema_version") == "selected_strategy_execution_v1"
        and execution.get("policy_decision_id") == trajectory.policy_decision_id
        and execution.get("policy_version") == strategy.behavior_policy_version
        and execution.get("selected_action") == strategy.chosen_action
        and execution.get("status") == "selected_runtime_path_observed"
        and execution.get("provider_receipt_observed") is True
        and execution.get("response_completed") is True
        and execution.get("transcript_durable") is True
        and execution.get("actual_provider") == trajectory.actual_provider
        and execution.get("actual_model") == model
        and execution.get("independent_verification_proven") is False
        and execution.get("dual_action_eligibility_established") is False
        and execution.get("randomized_selection") is False
        and execution.get("ope_eligible") is False,
        "selected_execution_provenance_unverified",
    )
    return {
        "status": "passed",
        "scope": "one_authenticated_real_model_durable_selected_turn",
        "transcript_messages": 2,
        "strategy_observations": 1,
        "execution_receipts": 1,
        "review_receipts": 0,
        "randomized_selection": False,
        "ope_eligible": False,
    }


async def read_back(
    *, tenant_id: str, user_id: str, session_id: str, model: str,
) -> dict[str, Any]:
    """Read a single session's original committed records without mutation."""
    for value in (tenant_id, user_id):
        uuid.UUID(value)
    require(session_id.startswith("kcog_c3c_"), "unapproved_acceptance_session")
    require(bool(model), "expected_installed_model_missing")

    trajectory_store = PostgresTrajectoryStore()
    with transaction_scope(tenant_id) as db:
        rows = db.execute(
            text(
                "SELECT trajectory_id FROM public.execution_trajectories "
                "WHERE tenant_id = CAST(:tenant AS uuid) "
                "AND user_id = CAST(:user_id AS uuid) AND session_id = :session"
            ),
            {"tenant": tenant_id, "user_id": user_id, "session": session_id},
        ).scalars().all()
    require(len(rows) == 1, "exactly_one_runtime_trajectory_required")
    trajectory = trajectory_store.get(rows[0], tenant_id=tenant_id)
    require(trajectory is not None, "runtime_trajectory_unavailable")

    context = ChatExecutionContext(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        request_id=trajectory.request_id,
        correlation_id=trajectory.correlation_id,
    )
    snapshot = await get_conversation_runtime_gateway().get_owned_snapshot_by_session(
        context, message_limit=3,
    )
    decisions = trajectory_store.list_decision_observations(
        trajectory.trajectory_id, tenant_id=tenant_id,
    )
    strategy = next(
        (d for d in decisions if d.decision_type == "respond_strategy"), None
    )
    feature = (
        trajectory_store.get_feature_snapshot(
            strategy.feature_snapshot_id, tenant_id=tenant_id,
        )
        if strategy is not None else None
    )
    outcomes = PostgresOutcomeStore().get_for_trajectory(
        trajectory.trajectory_id, tenant_id=tenant_id,
    )
    proof = verify_persisted_chain(
        trajectory=trajectory,
        decisions=decisions,
        feature=feature,
        outcomes=outcomes,
        snapshot=snapshot,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        model=model,
    )

    # Exercise the same canonical readers under an unrelated, valid tenant
    # identity. A real FORCE-RLS proof is separately mandatory in Cognitive CI.
    foreign_tenant = str(uuid.uuid4())
    require(
        trajectory_store.get(trajectory.trajectory_id, tenant_id=foreign_tenant)
        is None
        and PostgresOutcomeStore().get_for_trajectory(
            trajectory.trajectory_id, tenant_id=foreign_tenant,
        ) == [],
        "foreign_tenant_readback_exposed",
    )
    return proof


def main() -> int:
    if os.environ.get("KAREN_CI_C3C_LINEAGE_PROOF") != "enabled":
        print(json.dumps({"status": "failed", "code": "ci_authorization_missing"}))
        return 1
    try:
        result = asyncio.run(
            read_back(
                tenant_id=os.environ.get("KAREN_CI_C3C_TENANT_ID", ""),
                user_id=os.environ.get("KAREN_CI_C3C_USER_ID", ""),
                session_id=os.environ.get("KAREN_CI_C3C_SESSION_ID", ""),
                model=os.environ.get("KAREN_CI_C3C_MODEL", ""),
            )
        )
    except Exception as exc:
        known = {
            "unapproved_acceptance_session",
            "expected_installed_model_missing",
            "exactly_one_runtime_trajectory_required",
            "runtime_trajectory_unavailable",
            "trajectory_scope_or_execution_unverified",
            "canonical_conversation_scope_mismatch",
            "committed_transcript_pair_missing",
            "committed_transcript_identity_mismatch",
            "committed_transcript_trajectory_mismatch",
            "original_decision_lineage_ambiguous",
            "original_strategy_not_proven_or_ope_ineligible",
            "original_feature_snapshot_scope_mismatch",
            "persisted_strategy_reference_mismatch",
            "execution_or_review_receipt_ambiguous",
            "selected_execution_outcome_scope_mismatch",
            "selected_execution_provenance_unverified",
            "foreign_tenant_readback_exposed",
        }
        code = (
            str(exc)
            if isinstance(exc, DurableLineageProofError) and str(exc) in known
            else "unclassified"
        )
        # Never emit database errors, credentials, user identities, text, or
        # provider exception arguments from the CI container.
        print(
            json.dumps(
                {"status": "failed", "code": code, "error_type": type(exc).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

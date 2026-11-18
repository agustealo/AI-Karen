"""KCOG C3C/C3D: inspect real authenticated durable strategy lineage.

C3C reads the original authenticated /api/chat records. C3D executes two
policy-authorized requests inside the disposable production-image CI container.
Neither path mints learning labels, selects an experimental policy, or grants OPE.
Only bounded evidence counts and error classes are emitted.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import traceback
import uuid
from pathlib import Path
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


class _ScopedMemoryFailureTypeCapture(logging.Handler):
    """Observe only an already-redacted runtime error class inside CI.

    Do not copy message content, exception arguments, principal identifiers,
    prompt text, or provider outputs into the proof's diagnostics.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.error_type: str | None = None
        self.error_origin: str | None = None

    def emit(self, record: logging.LogRecord) -> None:
        if (
            record.name != "ai_karen_engine.core.runtime.chat_runtime"
            or record.msg != "Memory persistence failed"
        ):
            return
        candidate = getattr(record, "error_type", None)
        if (
            isinstance(candidate, str)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", candidate)
        ):
            self.error_type = candidate
            # Canonical ChatRuntime logs this record synchronously from its
            # exception handler. Read only stack locations, never exception
            # arguments or the raw traceback, then discard the traceback.
            _type, _value, tb = sys.exc_info()
            if _type is None or _type.__name__ != candidate or tb is None:
                return
            self.error_origin = "outside_memory"
            for frame in reversed(traceback.extract_tb(tb)):
                filename = frame.filename.replace("\\", "/")
                if not (
                    "/ai_karen_engine/core/memory/" in filename
                    or "/ai_karen_engine/platform/memory/" in filename
                ):
                    continue
                basename = Path(filename).name
                if (
                    re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}\.py", basename)
                    and 1 <= frame.lineno <= 99999
                ):
                    self.error_origin = f"{basename}:{frame.lineno}"
                break


def _bounded_runtime_degradation(
    metadata: dict[str, Any], *, expected_model: str | None = None,
) -> dict[str, Any]:
    """Emit only fixed runtime state enums and registered projection targets.

    Never forward arbitrary model, provider, memory, SQL or failure strings.
    This diagnoses real CI failures without changing the canonical runtime.
    """
    allowed: dict[str, frozenset[str]] = {
        "memory_persistence_status": frozenset({
            "persisted", "persisted_projection_degraded", "failed",
            "skipped", "no_candidate", "disabled_or_shadow",
            "denied_by_policy",
        }),
        "memory_formation_status": frozenset({
            "success", "degraded", "failed", "rejected", "skipped",
            "no_candidate", "noop",
        }),
        "transcript_persistence_status": frozenset({
            "persisted", "already_persisted", "failed", "rejected",
            "skipped",
        }),
        "degradation_reason": frozenset({
            "memory_projection_failed", "memory_persistence_failed",
            "memory_authorization_proof_rejected",
            "transcript_persistence_failed",
            "durable_learning_disabled_or_shadow",
            "output_token_limit",
        }),
    }
    result: dict[str, Any] = {}
    for key, values in allowed.items():
        observed = metadata.get(key)
        if isinstance(observed, str):
            result[key] = observed if observed in values else "other"
        else:
            result[key] = "unknown"

    failed_targets: set[str] = set()
    targets = metadata.get("memory_projection_targets")
    if isinstance(targets, list):
        for item in targets[:32]:
            if not isinstance(item, dict):
                continue
            target = item.get("target")
            count = item.get("failure_count")
            if (
                isinstance(target, str)
                and target in {"stm", "memory_graph", "projection_pipeline"}
                and type(count) is int
                and count > 0
            ):
                failed_targets.add(target)
    result["memory_failed_projection_targets"] = sorted(failed_targets)

    if expected_model:
        # Compare executed provider/model IDs without emitting identities or
        # untrusted provider/model/error text into the CI log.
        provider = metadata.get("actual_provider")
        actual_model = metadata.get("actual_model")
        result["observed_provider"] = (
            "ollama" if provider in {"ollama", "ollama-local"}
            else "missing" if provider is None or provider == ""
            else "other"
        ) if isinstance(provider, (str, type(None))) else "other"
        result["observed_model"] = (
            "expected" if actual_model == expected_model
            else "missing" if actual_model is None or actual_model == ""
            else "other"
        ) if isinstance(actual_model, (str, type(None))) else "other"

        for key, choices in {
            "reasoning_status": frozenset({
                "success", "completed", "partial", "abstained",
                "failed", "budget_exhausted", "not_applicable",
            }),
            "reasoning_activation": frozenset({"core_defaults"}),
            "reasoning_generation_mode": frozenset({
                "model_after_authorized_reasoning",
            }),
        }.items():
            value = metadata.get(key)
            result[key] = (
                value if value in choices else "other"
            ) if isinstance(value, str) else "unknown"

        verification = metadata.get("verification_strategy_executed")
        result["verification_strategy_executed"] = (
            verification if type(verification) is bool else "unknown"
        )
        calls = metadata.get("reasoning_model_calls")
        result["reasoning_model_calls"] = (
            "zero" if calls == 0
            else "positive" if calls > 0
            else "invalid"
        ) if type(calls) is int else "unknown"
        level = metadata.get("fallback_level")
        result["fallback_level"] = (
            "zero" if level == 0
            else "positive" if level > 0
            else "invalid"
        ) if type(level) is int else "unknown"

        # ExpressionGateway marks a result as degraded when generation
        # reaches its output-token limit. Never certify such a partial turn.
        truncated = metadata.get("output_truncated")
        result["output_truncated"] = (
            truncated if type(truncated) is bool else "unknown"
        )
        finish = metadata.get("finish_reason")
        result["finish_reason"] = (
            finish if finish in {"length", "stop", "eos", "end_turn"}
            else "other"
        ) if isinstance(finish, str) else "unknown"
    return result


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
    expected_action: str | None = None,
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
        and (expected_action is None or strategy.chosen_action == expected_action)
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
    if expected_action == "verify_then_respond":
        # The verifier's own reasoned execution receipt is required in
        # addition to the model call. An authorized hint is not execution.
        reasoning_modes = (trajectory.cortex_decision or {}).get("reasoning_modes")
        require(
            isinstance(reasoning_modes, list)
            and "verification" in reasoning_modes
            and strategy.chosen_action == "verify_then_respond"
            and trajectory.executed_topology == "reasoning"
            and isinstance(execution.get("reasoning_id"), str)
            and bool(execution["reasoning_id"])
            and execution.get("reasoning_status") in {"success", "completed"}
            and execution.get("reason_codes") == []
            and execution.get("status") == "selected_runtime_path_observed"
            and execution.get("independent_verification_proven") is False,
            "verification_execution_receipt_unverified",
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
    expected_session_prefix: str = "kcog_c3c_",
    expected_action: str | None = None,
    expected_assistant_digest: str | None = None,
) -> dict[str, Any]:
    """Read a single session's original committed records without mutation."""
    for value in (tenant_id, user_id):
        uuid.UUID(value)
    require(
        expected_session_prefix in {"kcog_c3c_", "kcog_c3d_"}
        and session_id.startswith(expected_session_prefix)
        and len(session_id) == len(expected_session_prefix) + 32
        and all(character in "0123456789abcdef" for character in session_id[-32:]),
        "unapproved_acceptance_session",
    )
    require(
        expected_action in {None, "verify_then_respond"},
        "unsupported_expected_strategy",
    )
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
    if expected_assistant_digest is not None:
        require(
            isinstance(expected_assistant_digest, str)
            and len(expected_assistant_digest) == 64
            and len(snapshot.messages) == 2
            and hashlib.sha256(
                snapshot.messages[-1].content.strip().encode("utf-8")
            ).hexdigest() == expected_assistant_digest,
            "delivered_answer_differs_from_committed_transcript",
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
        expected_action=expected_action,
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


def _principal_from_validated_session(
    *, tenant_id: str, user_id: str, observed: Any,
) -> Any:
    """Admit only the identity and RBAC claims verified by the CI HTTP session.

    The shell harness obtains this bounded envelope from the production
    /api/auth/validate-session route with the same authenticated cookie.
    Never manufacture elevated roles or permissions in this internal proof.
    """
    from ai_karen_engine.auth.models import UserData

    require(
        type(observed) is dict
        and observed.get("user_id") == user_id
        and observed.get("tenant_id") == tenant_id
        and observed.get("authenticated") is True
        and observed.get("session_valid") is True
        and observed.get("is_active") is True,
        "ci_authenticated_principal_unverified",
    )
    roles = observed.get("roles")
    permissions = observed.get("permissions")
    require(
        type(roles) is list
        and 0 < len(roles) <= 32
        and type(permissions) is list
        and len(permissions) <= 256
        and all(
            type(role) is str
            and 0 < len(role) <= 128
            and role.strip() == role
            for role in roles
        )
        and len(set(roles)) == len(roles)
        and all(
            type(permission) is str
            and 0 < len(permission) <= 128
            and permission.strip() == permission
            for permission in permissions
        )
        and len(set(permissions)) == len(permissions),
        "ci_authenticated_principal_unverified",
    )
    # UserData's verification bit describes the already-validated runtime
    # principal. It comes from session validation, never a hardcoded grant.
    return UserData(
        tenant_id=tenant_id,
        user_id=user_id,
        roles=list(roles),
        permissions=list(permissions),
        is_active=observed["is_active"],
        is_verified=observed["session_valid"],
    )


async def prove_verified_durable_runtime(
    *, tenant_id: str, user_id: str, model: str,
    authenticated_context: Any,
) -> dict[str, Any]:
    """Run two genuine CORTEX -> RuntimePolicy -> ChatRuntime executions.

    A CI-only verification hint is advisory. The persisted original strategy
    decision and executed verifier receipt must independently confirm that
    policy actually permitted and Runtime executed the verification path.
    """
    from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
    from ai_karen_engine.core.runtime.chat_runtime_contract import (
        ChatExecutionContext, ChatExecutionRequest, ChatExecutionStatus,
    )

    uuid.UUID(tenant_id)
    uuid.UUID(user_id)
    require(bool(model), "expected_installed_model_missing")
    principal = _principal_from_validated_session(
        tenant_id=tenant_id,
        user_id=user_id,
        observed=authenticated_context,
    )
    runtime = get_chat_runtime()
    observed: list[dict[str, Any]] = []

    for stream in (False, True):
        session_id = f"kcog_c3d_{uuid.uuid4().hex}"
        context = ChatExecutionContext(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            request_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            roles=list(principal.roles),
            permissions=list(principal.permissions),
            authenticated_user=principal,
        )
        request = ChatExecutionRequest(
            messages=[{
                "role": "user",
                "content": (
                    "Review this simple claim: A lighthouse helps ships navigate "
                    "at night. Verify the reasoning and give one short conclusion."
                ),
            }],
            context=context,
            preferred_provider="ollama",
            preferred_model=model,
            temperature=0.0,
            # The installed 135M CI model reached its output limit at both
            # 256 and 512 tokens after an authorized verifier preflight.
            # Give synthesis a bounded 1024-token allowance, beneath the
            # central 2048-token ceiling. The existing proof still rejects
            # incomplete, degraded, or fallback model generations.
            max_tokens=1024,
            stream=stream,
            metadata={
                "transport": "ci_verified_durable_runtime",
                "reasoning_modes": ["verification"],
                "max_model_calls": 2,
                "max_steps": 6,
                "time_budget_ms": 120000,
                "token_budget": 4096,
            },
        )

        if stream:
            fragments: list[str] = []
            completion: list[Any] = []
            sequence: list[int] = []
            observed_error = False
            async for chunk in runtime.execute_stream(request):
                kind = getattr(chunk.type, "value", chunk.type)
                observed_error |= kind == "error"
                if kind == "content":
                    fragments.append(chunk.content)
                if kind == "complete":
                    completion.append(chunk)
                if isinstance(chunk.sequence, int):
                    sequence.append(chunk.sequence)
            require(
                not observed_error and len(completion) == 1
                and sequence == sorted(set(sequence))
                and completion[0].correlation_id == context.correlation_id,
                "stream_terminal_contract_unverified",
            )
            answer = "".join(fragments)
            response_meta = completion[0].metadata or {}
        else:
            from ai_karen_engine.core.runtime.chat_runtime import (
                logger as runtime_logger,
            )

            memory_failure = _ScopedMemoryFailureTypeCapture()
            runtime_logger.addHandler(memory_failure)
            try:
                result = await runtime.execute(request)
            finally:
                runtime_logger.removeHandler(memory_failure)
            response_meta = result.metadata.to_dict()
            if result.status != ChatExecutionStatus.OK or not result.answer.strip():
                # Fixed, bounded source codes only. Never reveal user text,
                # provider exception text, model output or scoped identities.
                if response_meta.get("transcript_persistence_status") not in {
                    "persisted", "already_persisted",
                }:
                    failure_code = "nonstream_transcript_not_committed"
                elif response_meta.get("memory_persistence_status") == "failed":
                    failure_code = "nonstream_memory_formation_failed"
                elif result.status == ChatExecutionStatus.DEGRADED:
                    failure_code = "nonstream_runtime_degraded"
                elif result.status == ChatExecutionStatus.ERROR:
                    failure_code = "nonstream_runtime_error"
                else:
                    failure_code = "nonstream_response_missing"
                failure = DurableLineageProofError(failure_code)
                failure.observed_error_type = memory_failure.error_type
                failure.observed_error_origin = memory_failure.error_origin
                failure.observed_runtime_diagnostics = _bounded_runtime_degradation(
                    response_meta, expected_model=model,
                )
                raise failure
            answer = result.answer

        require(
            bool(answer.strip())
            and response_meta.get("actual_provider") in {"ollama", "ollama-local"}
            and response_meta.get("actual_model") == model
            and response_meta.get("fallback_level") == 0
            and response_meta.get("degraded_mode") is False
            and response_meta.get("transcript_persistence_status")
            in {"persisted", "already_persisted"},
            "runtime_generation_or_durability_unverified",
        )
        original_digest = hashlib.sha256(
            answer.strip().encode("utf-8")
        ).hexdigest()
        proof = await read_back(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            model=model,
            expected_session_prefix="kcog_c3d_",
            expected_action="verify_then_respond",
            expected_assistant_digest=original_digest,
        )
        require(proof["ope_eligible"] is False, "unlawful_learning_admission")
        observed.append({
            "transport": "stream" if stream else "nonstream",
            "committed_messages": proof["transcript_messages"],
            "verified_strategy_receipts": proof["execution_receipts"],
            "verification_executed": True,
            "ope_eligible": False,
        })

    return {
        "status": "passed",
        "scope": "ci_policy_authorized_verified_durable_runtime",
        "executions": observed,
        "independent_quality_review": False,
        "randomized_selection": False,
        "ope_eligible": False,
    }


def main() -> int:
    c3c = os.environ.get("KAREN_CI_C3C_LINEAGE_PROOF") == "enabled"
    c3d = os.environ.get("KAREN_CI_C3D_VERIFIED_DURABLE_PROOF") == "enabled"
    if c3c == c3d:
        print(json.dumps({"status": "failed", "code": "ci_authorization_missing"}))
        return 1
    try:
        if c3d:
            result = asyncio.run(
                prove_verified_durable_runtime(
                    tenant_id=os.environ.get("KAREN_CI_C3D_TENANT_ID", ""),
                    user_id=os.environ.get("KAREN_CI_C3D_USER_ID", ""),
                    model=os.environ.get("KAREN_CI_C3D_MODEL", ""),
                    authenticated_context=json.loads(
                        os.environ.get("KAREN_CI_C3D_AUTH_CONTEXT", "null")
                    ),
                )
            )
        else:
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
            "ci_authenticated_principal_unverified",
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
            "verification_execution_receipt_unverified",
            "delivered_answer_differs_from_committed_transcript",
            "unsupported_expected_strategy",
            "stream_terminal_contract_unverified",
            "nonstream_execution_unverified",
            "nonstream_transcript_not_committed",
            "nonstream_memory_formation_failed",
            "nonstream_runtime_degraded",
            "nonstream_runtime_error",
            "nonstream_response_missing",
            "runtime_generation_or_durability_unverified",
            "unlawful_learning_admission",
        }
        code = (
            str(exc)
            if isinstance(exc, DurableLineageProofError) and str(exc) in known
            else "unclassified"
        )
        # Never emit database errors, credentials, user identities, text, or
        # provider exception arguments from the CI container.
        diagnostics = {
            "status": "failed",
            "code": code,
            "error_type": type(exc).__name__,
        }
        observed = getattr(exc, "observed_error_type", None)
        if (
            isinstance(exc, DurableLineageProofError)
            and isinstance(observed, str)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", observed)
        ):
            diagnostics["memory_exception_type"] = observed
        origin = getattr(exc, "observed_error_origin", None)
        if (
            isinstance(exc, DurableLineageProofError)
            and isinstance(origin, str)
            and re.fullmatch(
                r"(?:[A-Za-z_][A-Za-z0-9_]{0,63}\.py:[1-9][0-9]{0,4}|outside_memory)",
                origin,
            )
        ):
            diagnostics["memory_exception_origin"] = origin
        if isinstance(exc, DurableLineageProofError):
            runtime_diagnostics = getattr(
                exc, "observed_runtime_diagnostics", None,
            )
            if isinstance(runtime_diagnostics, dict):
                diagnostics["runtime_observation"] = runtime_diagnostics
        print(
            json.dumps(diagnostics, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

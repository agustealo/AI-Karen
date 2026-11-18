"""KCOG-01C1B2C3C adversarial source proof for durable real-model lineage.

These tests exercise only the readback validator. The Ollama production-image
workflow separately executes real authenticated inference and PostgreSQL reads.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationSnapshot,
)
from ai_karen_engine.services.database.repositories import Conversation, Message
from scripts.ci.verification_strategy_durable_live_proof import (
    DurableLineageProofError,
    verify_persisted_chain,
)

TENANT = "11111111-1111-4111-8111-111111111111"
USER = "22222222-2222-4222-8222-222222222222"
SESSION = "kcog_c3c_0123456789abcdef0123456789abcdef"
MODEL = "installed-test-model"


def _evidence(*, verify: bool = False) -> dict:
    action = "verify_then_respond" if verify else "respond_direct"
    topology = "reasoning" if verify else "direct"
    trajectory = SimpleNamespace(
        trajectory_id="traj-original",
        request_id="req-original",
        correlation_id="corr-original",
        conversation_id="33333333-3333-4333-8333-333333333333",
        policy_decision_id="policy-original",
        tenant_id=TENANT,
        user_id=USER,
        session_id=SESSION,
        execution_status="success",
        executed_topology=topology,
        completed_at=datetime.now(timezone.utc),
        error_code=None,
        actual_provider="ollama",
        actual_model=MODEL,
        degraded_mode=False,
        fallback_level=0,
        plugin_actions=[],
        metadata={
            "selected_strategy_decision_observation_v1": {
                "schema_version": "selected_strategy_decision_observation_v1",
                "decision_observation_id": "strategy-original",
                "trajectory_id": "traj-original",
                "feature_snapshot_id": "features-original",
                "policy_decision_id": "policy-original",
                "policy_version": "policy-v1",
                "selected_action": action,
                "ope_eligible": False,
            }
        },
    )
    strategy = SimpleNamespace(
        decision_type="respond_strategy",
        decision_observation_id="strategy-original",
        trajectory_id=trajectory.trajectory_id,
        feature_snapshot_id="features-original",
        behavior_policy_version="policy-v1",
        decision_id=trajectory.policy_decision_id,
        chosen_action=action,
        eligible_actions=(action,),
        ope_eligible=False,
        chosen_probability=None,
        action_probabilities={},
        tenant_id=TENANT,
        user_id=USER,
    )
    decision_topology = SimpleNamespace(
        decision_type="execution_topology",
        decision_observation_id="topology-original",
        trajectory_id=trajectory.trajectory_id,
        feature_snapshot_id=strategy.feature_snapshot_id,
        chosen_action=topology,
    )
    feature = SimpleNamespace(
        feature_snapshot_id=strategy.feature_snapshot_id,
        trajectory_id=trajectory.trajectory_id,
        tenant_id=TENANT,
        user_id=USER,
        request_id=trajectory.request_id,
        correlation_id=trajectory.correlation_id,
        metadata={"policy_decision_id": trajectory.policy_decision_id},
    )
    common = {
        "request_id": trajectory.request_id,
        "correlation_id": trajectory.correlation_id,
        "session_id": SESSION,
        "conversation_id": trajectory.conversation_id,
        "authorized_user_id": USER,
    }
    snapshot = ConversationSnapshot(
        conversation=Conversation(
            id=trajectory.conversation_id,
            user_id=USER,
            tenant_id=TENANT,
            session_id=SESSION,
        ),
        messages=(
            Message(
                id="user-message",
                conversation_id=trajectory.conversation_id,
                tenant_id=TENANT,
                role="user",
                content="User's source task.",
                metadata={**common, "transcript_actor": "user"},
            ),
            Message(
                id="assistant-message",
                conversation_id=trajectory.conversation_id,
                tenant_id=TENANT,
                role="assistant",
                content="Generated model answer.",
                metadata={
                    **common,
                    "transcript_actor": "assistant",
                    "trajectory_id": trajectory.trajectory_id,
                    "actual_provider": trajectory.actual_provider,
                    "actual_model": MODEL,
                    "fallback_level": 0,
                    "degraded_mode": False,
                },
            ),
        ),
    )
    outcome = {
        "source": "runtime.execution",
        "trajectory_id": trajectory.trajectory_id,
        "decision_observation_id": strategy.decision_observation_id,
        "tenant_id": TENANT,
        "user_id": USER,
        "request_id": trajectory.request_id,
        "correlation_id": trajectory.correlation_id,
        "session_id": SESSION,
        "conversation_id": trajectory.conversation_id,
        "status": "success",
        "response_completed": True,
        "persistence_success": True,
        "fallback_count": 0,
        "metadata": {
            "topology_decision_observation_id": "topology-original",
            "transcript_persistence_status": "persisted",
            "actual_provider": "ollama",
            "actual_model": MODEL,
            "model_calls": 1,
            "tool_calls": 0,
            "selected_strategy_execution": {
                "schema_version": "selected_strategy_execution_v1",
                "policy_decision_id": trajectory.policy_decision_id,
                "policy_version": "policy-v1",
                "selected_action": action,
                "status": "selected_runtime_path_observed",
                "provider_receipt_observed": True,
                "response_completed": True,
                "transcript_durable": True,
                "actual_provider": "ollama",
                "actual_model": MODEL,
                "independent_verification_proven": False,
                "dual_action_eligibility_established": False,
                "randomized_selection": False,
                "ope_eligible": False,
            },
        },
    }
    return {
        "trajectory": trajectory,
        "decisions": [decision_topology, strategy],
        "feature": feature,
        "outcomes": [outcome],
        "snapshot": snapshot,
        "tenant_id": TENANT,
        "user_id": USER,
        "session_id": SESSION,
        "model": MODEL,
    }


@pytest.mark.parametrize("verify", [False, True])
def test_exact_original_committed_chain_is_observational_only(verify: bool) -> None:
    proof = verify_persisted_chain(**_evidence(verify=verify))
    assert proof == {
        "status": "passed",
        "scope": "one_authenticated_real_model_durable_selected_turn",
        "transcript_messages": 2,
        "strategy_observations": 1,
        "execution_receipts": 1,
        "review_receipts": 0,
        "randomized_selection": False,
        "ope_eligible": False,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", "foreign"),
        ("user_id", "foreign"),
        ("session_id", "foreign"),
        ("request_id", ""),
        ("execution_status", "cancelled"),
        ("completed_at", None),
        ("degraded_mode", True),
        ("fallback_level", 1),
        ("actual_model", "wrong-model"),
        ("plugin_actions", ["unauthorized-plugin"]),
    ],
)
def test_denied_trajectory_scope_or_execution(field: str, value: object) -> None:
    evidence = _evidence()
    setattr(evidence["trajectory"], field, value)
    with pytest.raises(
        DurableLineageProofError, match="trajectory_scope_or_execution_unverified"
    ):
        verify_persisted_chain(**evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("decision_observation_id", "forged-strategy"),
        ("feature_snapshot_id", "forged-features"),
        ("policy_decision_id", "forged-policy"),
        ("policy_version", "forged-version"),
        ("selected_action", "verify_then_respond"),
        ("ope_eligible", True),
    ],
)
def test_strategy_reference_cannot_be_rewritten(field: str, value: object) -> None:
    evidence = _evidence()
    evidence["trajectory"].metadata[
        "selected_strategy_decision_observation_v1"
    ][field] = value
    with pytest.raises(
        DurableLineageProofError, match="persisted_strategy_reference_mismatch"
    ):
        verify_persisted_chain(**evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ope_eligible", True),
        ("chosen_probability", 1.0),
        ("action_probabilities", {"respond_direct": 1.0}),
        ("eligible_actions", ("respond_direct", "verify_then_respond")),
        ("decision_id", "foreign-policy"),
    ],
)
def test_no_synthetic_ope_evidence(field: str, value: object) -> None:
    evidence = _evidence()
    setattr(evidence["decisions"][1], field, value)
    with pytest.raises(
        DurableLineageProofError,
        match="original_strategy_not_proven_or_ope_ineligible",
    ):
        verify_persisted_chain(**evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "other-request"),
        ("correlation_id", "other-correlation"),
        ("session_id", "other-session"),
        ("authorized_user_id", "other-user"),
        ("transcript_actor", "assistant"),
    ],
)
def test_committed_pair_requires_exact_original_identity(
    field: str, value: str,
) -> None:
    evidence = _evidence()
    evidence["snapshot"].messages[0].metadata[field] = value
    with pytest.raises(
        DurableLineageProofError, match="committed_transcript_identity_mismatch"
    ):
        verify_persisted_chain(**evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("decision_observation_id", "topology-original"),
        ("tenant_id", "foreign"),
        ("correlation_id", "foreign"),
        ("persistence_success", False),
        ("response_completed", False),
        ("fallback_count", 1),
    ],
)
def test_execution_outcome_must_match_actual_strategy(
    field: str, value: object,
) -> None:
    evidence = _evidence()
    evidence["outcomes"][0][field] = value
    with pytest.raises(
        DurableLineageProofError, match="selected_execution_outcome_scope_mismatch"
    ):
        verify_persisted_chain(**evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("topology_decision_observation_id", "wrong-topology"),
        ("actual_model", "wrong-model"),
        ("model_calls", 0),
        ("model_calls", True),
        ("tool_calls", 1),
        ("transcript_persistence_status", "failed"),
    ],
)
def test_outcome_cannot_promote_incomplete_execution(
    field: str, value: object,
) -> None:
    evidence = _evidence()
    evidence["outcomes"][0]["metadata"][field] = value
    with pytest.raises(
        DurableLineageProofError, match="selected_execution_provenance_unverified"
    ):
        verify_persisted_chain(**evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "unverified"),
        ("provider_receipt_observed", False),
        ("actual_provider", "fallback"),
        ("selected_action", "verify_then_respond"),
        ("independent_verification_proven", True),
        ("dual_action_eligibility_established", True),
        ("randomized_selection", True),
        ("ope_eligible", True),
    ],
)
def test_gateway_receipt_must_be_original_and_non_ope(
    field: str, value: object,
) -> None:
    evidence = _evidence()
    evidence["outcomes"][0]["metadata"]["selected_strategy_execution"][field] = value
    with pytest.raises(
        DurableLineageProofError, match="selected_execution_provenance_unverified"
    ):
        verify_persisted_chain(**evidence)


def test_duplicate_execution_receipt_denied() -> None:
    evidence = _evidence()
    evidence["outcomes"].append(deepcopy(evidence["outcomes"][0]))
    with pytest.raises(
        DurableLineageProofError, match="execution_or_review_receipt_ambiguous"
    ):
        verify_persisted_chain(**evidence)


def test_reviewer_label_denied_without_independent_admission() -> None:
    evidence = _evidence()
    evidence["outcomes"].append({"source": "intelligence.ml"})
    with pytest.raises(
        DurableLineageProofError, match="execution_or_review_receipt_ambiguous"
    ):
        verify_persisted_chain(**evidence)


def test_missing_or_partial_transcript_denied() -> None:
    evidence = _evidence()
    evidence["snapshot"] = ConversationSnapshot(
        conversation=evidence["snapshot"].conversation,
        messages=evidence["snapshot"].messages[:1],
    )
    with pytest.raises(
        DurableLineageProofError, match="committed_transcript_pair_missing"
    ):
        verify_persisted_chain(**evidence)


def test_unmatched_assistant_trajectory_denied() -> None:
    evidence = _evidence()
    evidence["snapshot"].messages[1].metadata["trajectory_id"] = "wrong"
    with pytest.raises(
        DurableLineageProofError, match="committed_transcript_trajectory_mismatch"
    ):
        verify_persisted_chain(**evidence)


def test_original_feature_must_match_request_and_tenant() -> None:
    evidence = _evidence()
    evidence["feature"].correlation_id = "wrong"
    with pytest.raises(
        DurableLineageProofError, match="original_feature_snapshot_scope_mismatch"
    ):
        verify_persisted_chain(**evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actual_provider", "fallback"),
        ("actual_model", "wrong-model"),
        ("fallback_level", 1),
        ("degraded_mode", True),
    ],
)
def test_committed_assistant_cannot_claim_other_model(
    field: str, value: object,
) -> None:
    evidence = _evidence()
    evidence["snapshot"].messages[1].metadata[field] = value
    with pytest.raises(
        DurableLineageProofError, match="committed_transcript_trajectory_mismatch"
    ):
        verify_persisted_chain(**evidence)


def test_forged_topology_cannot_pass_as_original_strategy() -> None:
    evidence = _evidence()
    evidence["trajectory"].executed_topology = "reasoning"
    with pytest.raises(
        DurableLineageProofError,
        match="original_strategy_not_proven_or_ope_ineligible",
    ):
        verify_persisted_chain(**evidence)


# KCOG-01C1B2C3D: accepted verification must have original verifier evidence.
def _verified_durable_evidence() -> dict:
    evidence = _evidence(verify=True)
    evidence["trajectory"].cortex_decision = {
        "reasoning_modes": ["verification"],
    }
    evidence["outcomes"][0]["metadata"]["selected_strategy_execution"].update({
        "reasoning_id": "original-executed-verifier",
        "reasoning_status": "success",
        "reason_codes": [],
    })
    return evidence


def test_c3d_requires_original_verifier_receipt() -> None:
    evidence = _verified_durable_evidence()
    result = verify_persisted_chain(
        **evidence, expected_action="verify_then_respond",
    )
    assert result["status"] == "passed"
    assert result["ope_eligible"] is False
    assert result["review_receipts"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reasoning_id", None),
        ("reasoning_id", ""),
        ("reasoning_status", "failed"),
        ("reasoning_status", "budget_exhausted"),
        ("reasoning_status", "unknown"),
        ("reason_codes", ["model_generation_receipt_unverified"]),
        ("status", "unverified"),
        ("independent_verification_proven", True),
    ],
)
def test_c3d_rejects_unobserved_or_fabricated_verification(
    field: str, value: object,
) -> None:
    evidence = _verified_durable_evidence()
    execution = evidence["outcomes"][0]["metadata"]["selected_strategy_execution"]
    execution[field] = value
    with pytest.raises(
        DurableLineageProofError,
        match=(
            "selected_execution_provenance_unverified"
            if field in {"status", "independent_verification_proven"}
            else "verification_execution_receipt_unverified"
        ),
    ):
        verify_persisted_chain(
            **evidence, expected_action="verify_then_respond",
        )


def test_c3d_rejects_direct_path_misreported_as_verification() -> None:
    evidence = _evidence()
    evidence["trajectory"].cortex_decision = {"reasoning_modes": []}
    with pytest.raises(
        DurableLineageProofError, match="original_strategy_not_proven_or_ope_ineligible",
    ):
        verify_persisted_chain(
            **evidence, expected_action="verify_then_respond",
        )


def test_c3d_rejects_verification_without_original_cortex_mode() -> None:
    evidence = _verified_durable_evidence()
    evidence["trajectory"].cortex_decision["reasoning_modes"] = []
    with pytest.raises(
        DurableLineageProofError, match="verification_execution_receipt_unverified",
    ):
        verify_persisted_chain(
            **evidence, expected_action="verify_then_respond",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session_id,expected_prefix",
    [
        ("kcog_c3c_0123456789abcdef0123456789abcdef", "kcog_c3d_"),
        ("kcog_c3d_bad", "kcog_c3d_"),
        ("kcog_c3d_0123456789abcdef0123456789abcdeg", "kcog_c3d_"),
        ("kcog_c3d_0123456789abcdef0123456789abcdef", "unapproved_"),
    ],
)
async def test_c3d_readback_denies_unapproved_session_before_database(
    session_id: str, expected_prefix: str,
) -> None:
    from scripts.ci.verification_strategy_durable_live_proof import read_back

    with pytest.raises(
        DurableLineageProofError, match="unapproved_acceptance_session",
    ):
        await read_back(
            tenant_id=TENANT, user_id=USER,
            session_id=session_id, model=MODEL,
            expected_session_prefix=expected_prefix,
            expected_action="verify_then_respond",
        )


def test_c3d_ci_entrypoint_requires_exclusive_authorization(monkeypatch, capsys) -> None:
    from scripts.ci.verification_strategy_durable_live_proof import main

    monkeypatch.setenv("KAREN_CI_C3C_LINEAGE_PROOF", "enabled")
    monkeypatch.setenv("KAREN_CI_C3D_VERIFIED_DURABLE_PROOF", "enabled")
    assert main() == 1
    assert "ci_authorization_missing" in capsys.readouterr().out

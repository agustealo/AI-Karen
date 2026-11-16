"""Canonical provenance and probability validation for offline policy evidence.

Only authenticated, independently evaluated observations with *logged*
behavior and candidate action probabilities may enter the existing
IPS/SNIPS/DR evaluation. Validation does not establish label authenticity,
authorize exploration, or activate any runtime policy.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from ai_karen_engine.core.intelligence.ml.policy_evaluation.contracts import (
    DecisionType,
    PolicyObservation,
    validate_probability_distribution,
)


def validate_evaluated_policy_observations(
    observations: Sequence[PolicyObservation],
    *,
    tenant_id: str,
    decision_type: DecisionType,
    domain: str,
) -> None:
    """Reject fabricated, missing, duplicate, or cross-principal policy data.

    The named domain is diagnostic wording only. Runtime authority and
    permission checks belong to authenticated owners upstream, never to an
    evaluation report. Caller must verify the source of the label receipts.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip() or tenant_id == "default":
        raise ValueError(
            f"A verified tenant scope is required for {domain} policy evaluation"
        )
    if not isinstance(decision_type, DecisionType):
        raise ValueError("A canonical decision type is required")
    if domain not in {"model", "verification"}:
        raise ValueError("Unsupported policy evaluation domain")

    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    for item in observations:
        if not isinstance(item, PolicyObservation):
            raise TypeError("Only canonical typed policy observations may be evaluated")
        if item.context is None or item.context.decision_type != decision_type:
            raise ValueError(
                f"Non-{domain} decisions cannot prove {domain} policy improvement"
            )
        if item.context.tenant_scope != tenant_id:
            raise PermissionError("Cross-tenant policy evidence is forbidden")
        if not isinstance(item.observation_id, str) or not item.observation_id:
            raise ValueError(f"{domain.title()} decision identity is required")
        if item.observation_id in seen_ids:
            raise ValueError(f"Duplicate {domain} decision is not independent evidence")
        seen_ids.add(item.observation_id)

        if not isinstance(item.context.feature_snapshot_id, str) or not item.context.feature_snapshot_id:
            raise ValueError("Decision-time feature snapshot is required")
        metadata = item.metadata
        if (
            not isinstance(metadata, dict)
            or metadata.get("reward_evidence_type") not in {
                "independent_test", "human_review",
            }
            or not isinstance(metadata.get("reward_evidence_ref"), str)
            or not 1 <= len(metadata["reward_evidence_ref"]) <= 256
            or not metadata["reward_evidence_ref"].isascii()
            or not all(
                ch.isalnum() or ch in "-._:/"
                for ch in metadata["reward_evidence_ref"]
            )
        ):
            raise ValueError("Independent evaluation or human review is required")
        evidence_ref = metadata["reward_evidence_ref"]
        if evidence_ref in seen_labels:
            raise ValueError("Duplicate independent reward evidence reference")
        seen_labels.add(evidence_ref)

        if (
            isinstance(item.reward, bool)
            or not isinstance(item.reward, (int, float))
            or not math.isfinite(item.reward)
            or not 0 <= item.reward <= 1
        ):
            raise ValueError(f"{domain.title()} policy reward must be finite and verified")

        actions = item.eligible_actions
        if (
            not isinstance(actions, list)
            or not actions
            or any(not isinstance(action, str) or not action for action in actions)
            or len(set(actions)) != len(actions)
            or item.chosen_action not in actions
            or item.context.eligible_actions != actions
        ):
            raise ValueError(
                f"Actual chosen {domain} is not in the eligible set"
            )
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                item.behavior_policy_id,
                item.behavior_policy_version,
                item.candidate_policy_id,
                item.candidate_policy_version,
            )
        ):
            raise ValueError(
                "Versioned behavior and candidate policy provenance is required"
            )
        distributions = (
            item.behavior_probabilities,
            item.candidate_probabilities,
        )
        if any(
            not isinstance(dist, dict)
            or set(dist) != set(actions)
            or any(
                isinstance(p, bool)
                or not isinstance(p, (int, float))
                or not math.isfinite(p)
                for p in dist.values()
            )
            for dist in distributions
        ):
            raise ValueError("Action probabilities must be finite numeric values")
        if any(
            validate_probability_distribution(dist, actions) is not None
            for dist in distributions
        ):
            raise ValueError(
                "Real behavior and candidate action distributions are required"
            )
        if (
            isinstance(item.chosen_probability, bool)
            or not isinstance(item.chosen_probability, (int, float))
            or not math.isfinite(item.chosen_probability)
            or not 0 < item.chosen_probability <= 1
            or abs(
                item.behavior_probabilities[item.chosen_action]
                - item.chosen_probability
            ) > 1e-6
        ):
            raise ValueError(
                f"Chosen-{domain} propensity must match the logged behavior policy"
            )

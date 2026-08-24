from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DecisionType(str, Enum):
    """Kinds of runtime decisions that may eventually be learned.

    Phase 2 only fully wires EXECUTION_TOPOLOGY now. The contract is
    extensible so later phases reuse it for providers/models/agents/tools/
    plugins/memory without breaking the schema.
    """

    EXECUTION_TOPOLOGY = "execution_topology"
    PROVIDER_SELECTION = "provider_selection"
    MODEL_SELECTION = "model_selection"
    AGENT_SELECTION = "agent_selection"
    TOOL_SELECTION = "tool_selection"
    PLUGIN_SELECTION = "plugin_selection"
    MEMORY_SELECTION = "memory_selection"


class OpeEligibilityReason(str, Enum):
    """Why a decision observation is or is not eligible for OPE."""

    MISSING_PROPENSITY = "missing_propensity"
    INVALID_PROBABILITY_DISTRIBUTION = "invalid_probability_distribution"
    UNKNOWN_BEHAVIOR_POLICY = "unknown_behavior_policy"
    INCOMPLETE_CANDIDATE_SET = "incomplete_candidate_set"


# Feature schema versions. Do not force all ML tasks into one giant schema.
TOPOLOGY_FEATURES_V1 = "topology_features_v1"
PROVIDER_ROUTING_FEATURES_V1 = "provider_routing_features_v1"
MEMORY_RANKING_FEATURES_V1 = "memory_ranking_features_v1"
AGENT_RANKING_FEATURES_V1 = "agent_ranking_features_v1"

# Deterministic baseline behavior policy identity. Never use "current": that
# destroys reproducibility. Later phases introduce adaptive_* variants.
CORTEX_TOPOLOGY_POLICY_ID = "cortex_topology"
CORTEX_TOPOLOGY_POLICY_VERSION = "v1"


# Keys that must never be persisted into a learning record. Mirrors the
# observability redaction hints but applied at record-build time so secrets
# never reach durable storage in the first place.
_SECRET_FIELD_HINTS = {
    "password",
    "secret",
    "token",
    "api_key",
    "authorization",
    "credential",
    "auth",
    "private_key",
    "client_secret",
    "access_token",
    "refresh_token",
    "bearer",
    "x_api_key",
    "oauth",
    "session_token",
    "cookie",
    "apikey",
}


def _is_secret_key(key: Any) -> bool:
    return isinstance(key, str) and any(hint in key.lower() for hint in _SECRET_FIELD_HINTS)


def sanitize_secrets(value: Any) -> Any:
    """Recursively strip secret-named keys from a structure.

    Returns a copy; never mutates the input. Used when building immutable
    learning records so raw credentials cannot be persisted.
    """
    if isinstance(value, dict):
        return {
            k: sanitize_secrets(v) for k, v in value.items() if not _is_secret_key(k)
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_secrets(v) for v in value]
    return value


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    """Immutable snapshot of what was known at decision time.

    Copies normalized fields at decision time. It must never hold references
    to mutable runtime objects, otherwise the model could train on a state
    that never existed when the decision was made.
    """

    feature_snapshot_id: str
    request_id: str
    correlation_id: str

    feature_version: str
    created_at: datetime

    # Audit metadata only. These are NOT model features.
    trajectory_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None

    intent: str | None = None
    intent_confidence: float | None = None

    domain: str | None = None
    complexity: str | None = None
    ambiguity: float | None = None
    memory_relevance: float | None = None

    capability_hints: dict[str, Any] = field(default_factory=dict)
    topology_signals: dict[str, Any] = field(default_factory=dict)
    risk_signals: dict[str, Any] = field(default_factory=dict)

    runtime_capabilities: dict[str, Any] = field(default_factory=dict)
    provider_health_snapshot: dict[str, Any] = field(default_factory=dict)
    resource_snapshot: dict[str, Any] = field(default_factory=dict)

    metadata: dict[str, Any] = field(default_factory=dict)

    def feature_vector(self) -> dict[str, Any]:
        """Model feature vector. Excludes tenant/user ids and record ids."""
        return {
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "domain": self.domain,
            "complexity": self.complexity,
            "ambiguity": self.ambiguity,
            "memory_relevance": self.memory_relevance,
            "capability_hints": self.capability_hints,
            "topology_signals": self.topology_signals,
            "risk_signals": self.risk_signals,
            "runtime_capabilities": self.runtime_capabilities,
            "provider_health_snapshot": self.provider_health_snapshot,
            "resource_snapshot": self.resource_snapshot,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_snapshot_id": self.feature_snapshot_id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "feature_version": self.feature_version,
            "created_at": self.created_at.isoformat(),
            "trajectory_id": self.trajectory_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "domain": self.domain,
            "complexity": self.complexity,
            "ambiguity": self.ambiguity,
            "memory_relevance": self.memory_relevance,
            "capability_hints": self.capability_hints,
            "topology_signals": self.topology_signals,
            "risk_signals": self.risk_signals,
            "runtime_capabilities": self.runtime_capabilities,
            "provider_health_snapshot": self.provider_health_snapshot,
            "resource_snapshot": self.resource_snapshot,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Deterministic JSON serialization (sorted keys, stable types)."""
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureSnapshot:
        return cls(
            feature_snapshot_id=data["feature_snapshot_id"],
            request_id=data["request_id"],
            correlation_id=data["correlation_id"],
            feature_version=data["feature_version"],
            created_at=datetime.fromisoformat(data["created_at"]),
            trajectory_id=data.get("trajectory_id"),
            tenant_id=data.get("tenant_id"),
            user_id=data.get("user_id"),
            intent=data.get("intent"),
            intent_confidence=data.get("intent_confidence"),
            domain=data.get("domain"),
            complexity=data.get("complexity"),
            ambiguity=data.get("ambiguity"),
            memory_relevance=data.get("memory_relevance"),
            capability_hints=data.get("capability_hints", {}),
            topology_signals=data.get("topology_signals", {}),
            risk_signals=data.get("risk_signals", {}),
            runtime_capabilities=data.get("runtime_capabilities", {}),
            provider_health_snapshot=data.get("provider_health_snapshot", {}),
            resource_snapshot=data.get("resource_snapshot", {}),
            metadata={},
        )


@dataclass(frozen=True, slots=True)
class DecisionObservation:
    """Canonical observation of a single learned decision.

    Records the context, the legal action set, what was chosen, and the
    propensity the choosing policy assigned. Without this, Phase 3 cannot do
    legitimate off-policy evaluation.
    """

    decision_observation_id: str
    trajectory_id: str
    feature_snapshot_id: str

    decision_type: str
    behavior_policy_id: str
    behavior_policy_version: str

    candidate_actions: tuple[str, ...]
    eligible_actions: tuple[str, ...]
    chosen_action: str

    created_at: datetime

    chosen_probability: float | None = None
    action_probabilities: dict[str, float] = field(default_factory=dict)

    ope_eligible: bool = True
    ope_ineligible_reason: str | None = None

    decision_id: str | None = None

    # Audit metadata only. NOT model features.
    tenant_id: str | None = None
    user_id: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_observation_id": self.decision_observation_id,
            "trajectory_id": self.trajectory_id,
            "feature_snapshot_id": self.feature_snapshot_id,
            "decision_type": self.decision_type,
            "behavior_policy_id": self.behavior_policy_id,
            "behavior_policy_version": self.behavior_policy_version,
            "candidate_actions": list(self.candidate_actions),
            "eligible_actions": list(self.eligible_actions),
            "chosen_action": self.chosen_action if self.chosen_action else None,
            "chosen_action_value": self.chosen_action,
            "chosen_probability": self.chosen_probability,
            "action_probabilities": self.action_probabilities,
            "ope_eligible": self.ope_eligible,
            "ope_ineligible_reason": self.ope_ineligible_reason,
            "decision_id": self.decision_id,
            "created_at": self.created_at.isoformat(),
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionObservation:
        return cls(
            decision_observation_id=data["decision_observation_id"],
            trajectory_id=data["trajectory_id"],
            feature_snapshot_id=data["feature_snapshot_id"],
            decision_type=data["decision_type"],
            behavior_policy_id=data["behavior_policy_id"],
            behavior_policy_version=data["behavior_policy_version"],
            candidate_actions=tuple(data.get("candidate_actions", [])),
            eligible_actions=tuple(data.get("eligible_actions", [])),
            chosen_action=str(data.get("chosen_action_value") or data.get("chosen_action") or ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            chosen_probability=data.get("chosen_probability"),
            action_probabilities=data.get("action_probabilities", {}),
            ope_eligible=data.get("ope_eligible", True),
            ope_ineligible_reason=data.get("ope_ineligible_reason"),
            decision_id=data.get("decision_id"),
            tenant_id=data.get("tenant_id"),
            user_id=data.get("user_id"),
            metadata=data.get("metadata", {}),
        )


def validate_probability_distribution(
    chosen_action: str,
    chosen_probability: float | None,
    action_probabilities: dict[str, float],
) -> tuple[bool, OpeEligibilityReason | None]:
    """Validate raw propensity values are in [0, 1]."""
    for value in action_probabilities.values():
        if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            return False, OpeEligibilityReason.INVALID_PROBABILITY_DISTRIBUTION
    if chosen_probability is not None and not 0.0 <= float(chosen_probability) <= 1.0:
        return False, OpeEligibilityReason.INVALID_PROBABILITY_DISTRIBUTION
    return True, None


def compute_ope_eligibility(
    candidate_actions: tuple[str, ...] | list[str],
    behavior_policy_id: str,
    chosen_action: str,
    chosen_probability: float | None,
    action_probabilities: dict[str, float],
) -> tuple[bool, OpeEligibilityReason | None]:
    """Decide whether an observation can be used by propensity estimators."""
    if not candidate_actions:
        return False, OpeEligibilityReason.INCOMPLETE_CANDIDATE_SET
    if not behavior_policy_id:
        return False, OpeEligibilityReason.UNKNOWN_BEHAVIOR_POLICY
    if chosen_probability is None:
        return False, OpeEligibilityReason.MISSING_PROPENSITY
    if not action_probabilities or chosen_action not in action_probabilities:
        return False, OpeEligibilityReason.MISSING_PROPENSITY
    valid, reason = validate_probability_distribution(
        chosen_action, chosen_probability, action_probabilities
    )
    if not valid:
        return False, reason
    return True, None


def create_feature_snapshot(
    trajectory: Any,
    *,
    feature_version: str,
    request_id: str | None = None,
    correlation_id: str | None = None,
    trajectory_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
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
    feature_snapshot_id: str | None = None,
    created_at: datetime | None = None,
) -> FeatureSnapshot:
    """Build an immutable, secret-sanitized feature snapshot from a trajectory."""
    request_id = request_id or getattr(trajectory, "request_id", None)
    correlation_id = correlation_id or getattr(trajectory, "correlation_id", None)
    tenant_id = tenant_id or getattr(trajectory, "tenant_id", None)
    user_id = user_id or getattr(trajectory, "user_id", None)
    trajectory_id = trajectory_id or getattr(trajectory, "trajectory_id", None)

    if not request_id:
        raise ValueError("feature snapshot requires request_id")
    if not correlation_id:
        raise ValueError("feature snapshot requires correlation_id")
    if not feature_version:
        raise ValueError("feature_version is required")

    return FeatureSnapshot(
        feature_snapshot_id=feature_snapshot_id or f"fs_{uuid.uuid4().hex}",
        request_id=request_id,
        correlation_id=correlation_id,
        feature_version=feature_version,
        created_at=created_at or datetime.utcnow(),
        trajectory_id=trajectory_id,
        tenant_id=tenant_id,
        user_id=user_id,
        intent=intent,
        intent_confidence=intent_confidence,
        domain=domain,
        complexity=complexity,
        ambiguity=ambiguity,
        memory_relevance=memory_relevance,
        capability_hints=sanitize_secrets(capability_hints or {}),
        topology_signals=sanitize_secrets(topology_signals or {}),
        risk_signals=sanitize_secrets(risk_signals or {}),
        runtime_capabilities=sanitize_secrets(runtime_capabilities or {}),
        provider_health_snapshot=sanitize_secrets(provider_health_snapshot or {}),
        resource_snapshot=sanitize_secrets(resource_snapshot or {}),
        metadata=sanitize_secrets(metadata or {}),
    )


def create_decision_observation(
    *,
    trajectory_id: str,
    feature_snapshot_id: str,
    decision_type: str,
    behavior_policy_id: str,
    behavior_policy_version: str,
    candidate_actions: tuple[str, ...] | list[str],
    eligible_actions: tuple[str, ...] | list[str],
    chosen_action: str,
    chosen_probability: float | None = None,
    action_probabilities: dict[str, float] | None = None,
    decision_id: str | None = None,
    ope_eligible: bool | None = None,
    ope_ineligible_reason: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    decision_observation_id: str | None = None,
    created_at: datetime | None = None,
) -> DecisionObservation:
    """Build a validated decision observation.

    Raises ValueError if the chosen action is not in the eligible set. The
    OPE eligibility is computed from the supplied propensity; callers may
    override ``ope_eligible``/``ope_ineligible_reason`` but validation still
    runs.
    """
    candidate_actions = tuple(candidate_actions)
    eligible_actions = tuple(eligible_actions)
    action_probabilities = dict(action_probabilities or {})

    if chosen_action not in eligible_actions:
        raise ValueError(
            f"chosen_action {chosen_action!r} is not in eligible_actions {eligible_actions!r}"
        )

    valid_dist, dist_reason = validate_probability_distribution(
        chosen_action, chosen_probability, action_probabilities
    )
    if not valid_dist:
        raise ValueError(
            f"invalid probability distribution: "
            f"{dist_reason.value if dist_reason is not None else 'invalid'}"
        )

    if ope_eligible is None or ope_ineligible_reason is None:
        eligible, reason = compute_ope_eligibility(
            candidate_actions,
            behavior_policy_id,
            chosen_action,
            chosen_probability,
            action_probabilities,
        )
        if ope_eligible is None:
            ope_eligible = eligible
        if ope_ineligible_reason is None:
            ope_ineligible_reason = reason.value if reason is not None else None

    return DecisionObservation(
        decision_observation_id=decision_observation_id or f"obs_{uuid.uuid4().hex}",
        trajectory_id=trajectory_id,
        feature_snapshot_id=feature_snapshot_id,
        decision_type=decision_type,
        behavior_policy_id=behavior_policy_id,
        behavior_policy_version=behavior_policy_version,
        candidate_actions=candidate_actions,
        eligible_actions=eligible_actions,
        chosen_action=chosen_action,
        chosen_probability=chosen_probability,
        action_probabilities=action_probabilities,
        ope_eligible=ope_eligible,
        ope_ineligible_reason=ope_ineligible_reason,
        decision_id=decision_id,
        created_at=created_at or datetime.utcnow(),
        tenant_id=tenant_id,
        user_id=user_id,
        metadata=sanitize_secrets(metadata or {}),
    )

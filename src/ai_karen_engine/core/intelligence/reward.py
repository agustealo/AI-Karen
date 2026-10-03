"""Evidence-backed reward and growth projection.

This module is Intelligence-owned and advisory. Runtime records observable facts;
this projector derives explainable quality/reward evidence from those records.
It never authorizes actions, changes routing, mutates memory, or grants RBAC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RewardPolicy:
    policy_id: str = "karen_growth"
    version: str = "v1"
    quality_threshold: float = 0.75
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "completion": 0.28,
            "durability": 0.22,
            "verification": 0.18,
            "efficiency": 0.12,
            "resilience": 0.08,
            "user_feedback": 0.12,
        }
    )


@dataclass(frozen=True, slots=True)
class RewardEvidence:
    trajectory_id: str
    score: float
    confidence: float
    dimensions: dict[str, float]
    reason_codes: tuple[str, ...]
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "score": round(self.score, 1),
            "confidence": round(self.confidence, 3),
            "dimensions": {key: round(value * 100.0, 1) for key, value in self.dimensions.items()},
            "reason_codes": list(self.reason_codes),
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class ProgressMilestone:
    milestone_id: str
    title: str
    description: str
    unlocked: bool
    evidence_count: int
    threshold: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.milestone_id,
            "title": self.title,
            "description": self.description,
            "unlocked": self.unlocked,
            "evidence_count": self.evidence_count,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class RewardProgressSnapshot:
    policy_id: str
    policy_version: str
    level: str
    progress_index: float
    average_quality: float
    evidence_count: int
    quality_run: int
    dimensions: dict[str, float]
    dimension_coverage: dict[str, float]
    milestones: tuple[ProgressMilestone, ...]
    recent_evidence: tuple[RewardEvidence, ...]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": {"id": self.policy_id, "version": self.policy_version},
            "level": self.level,
            "progress_index": round(self.progress_index, 1),
            "average_quality": round(self.average_quality, 1),
            "evidence_count": self.evidence_count,
            "quality_run": self.quality_run,
            "dimensions": {key: round(value * 100.0, 1) for key, value in self.dimensions.items()},
            "dimension_coverage": {
                key: round(value * 100.0, 1) for key, value in self.dimension_coverage.items()
            },
            "milestones": [milestone.to_dict() for milestone in self.milestones],
            "recent_evidence": [item.to_dict() for item in self.recent_evidence],
            "generated_at": self.generated_at,
            "principles": {
                "engagement_volume_rewarded": False,
                "daily_login_streaks_rewarded": False,
                "rbac_affected": False,
                "routing_affected": False,
                "memory_consent_affected": False,
            },
        }


class RewardProjector:
    """Derive progress from completed evidence without inventing unknown quality."""

    def __init__(self, policy: RewardPolicy | None = None) -> None:
        self._policy = policy or RewardPolicy()

    def project(self, records: list[dict[str, Any]]) -> RewardProgressSnapshot:
        ordered = sorted(records, key=lambda item: str(item.get("recorded_at") or ""))
        feedback_by_trajectory = self._feedback_by_trajectory(ordered)
        evidence: list[RewardEvidence] = []

        for record in ordered:
            if record.get("source") != "runtime.execution":
                continue
            trajectory_id = str(record.get("trajectory_id") or "").strip()
            if not trajectory_id:
                continue
            evidence.append(
                self._score_execution(record, feedback_by_trajectory.get(trajectory_id, []))
            )

        dimension_values: dict[str, list[float]] = {
            key: [] for key in self._policy.weights
        }
        for item in evidence:
            for key, value in item.dimensions.items():
                dimension_values.setdefault(key, []).append(value)

        dimensions = {
            key: sum(values) / len(values)
            for key, values in dimension_values.items()
            if values
        }
        total = max(1, len(evidence))
        coverage = {
            key: len(values) / total
            for key, values in dimension_values.items()
        }

        average_quality = self._confidence_weighted_average(evidence)
        progress_index = 0.0
        if evidence:
            evidence_depth = min(1.0, len(evidence) / 25.0)
            progress_index = min(100.0, average_quality * 0.8 + evidence_depth * 20.0)

        quality_run = self._quality_run(evidence)
        level = self._level(evidence, average_quality, quality_run)
        milestones = self._milestones(evidence, quality_run)

        return RewardProgressSnapshot(
            policy_id=self._policy.policy_id,
            policy_version=self._policy.version,
            level=level,
            progress_index=progress_index,
            average_quality=average_quality,
            evidence_count=len(evidence),
            quality_run=quality_run,
            dimensions=dimensions,
            dimension_coverage=coverage,
            milestones=tuple(milestones),
            recent_evidence=tuple(reversed(evidence[-8:])),
            generated_at=datetime.utcnow().isoformat(),
        )

    def _score_execution(
        self,
        execution: dict[str, Any],
        feedback_records: list[dict[str, Any]],
    ) -> RewardEvidence:
        dimensions: dict[str, float] = {}
        reasons: list[str] = []

        status = str(execution.get("status") or "").lower()
        completion = 1.0 if status == "success" else 0.5 if status == "partial_success" else 0.0
        if execution.get("response_completed") is False:
            completion = min(completion, 0.25)
            reasons.append("response_incomplete")
        dimensions["completion"] = completion

        persistence = execution.get("persistence_success")
        if isinstance(persistence, bool):
            dimensions["durability"] = 1.0 if persistence else 0.0
            reasons.append("durable_persistence" if persistence else "persistence_failed")

        verification_checks = [
            execution.get("schema_valid"),
            execution.get("tool_success"),
            execution.get("plugin_success"),
        ]
        verification_values = [
            1.0 if value else 0.0
            for value in verification_checks
            if isinstance(value, bool)
        ]
        if verification_values:
            dimensions["verification"] = sum(verification_values) / len(verification_values)
            reasons.append("verification_evidence")

        latency = execution.get("latency_ms")
        if isinstance(latency, (int, float)) and latency >= 0:
            dimensions["efficiency"] = max(0.0, 1.0 - min(float(latency) / 30000.0, 1.0))

        fallback_count = execution.get("fallback_count")
        if isinstance(fallback_count, int) and fallback_count >= 0:
            dimensions["resilience"] = max(0.0, 1.0 - min(float(fallback_count) / 3.0, 1.0))
            if fallback_count:
                reasons.append("fallback_used")

        feedback = self._feedback_score(feedback_records)
        if feedback is not None:
            dimensions["user_feedback"] = feedback
            reasons.append("explicit_user_feedback")
        else:
            reasons.append("user_feedback_unavailable")

        observed_weight = sum(
            self._policy.weights[key] for key in dimensions if key in self._policy.weights
        )
        total_weight = sum(self._policy.weights.values())
        weighted = sum(
            self._policy.weights[key] * value
            for key, value in dimensions.items()
            if key in self._policy.weights
        )
        scalar = (weighted / observed_weight) if observed_weight > 0 else 0.0
        confidence = (observed_weight / total_weight) if total_weight > 0 else 0.0

        return RewardEvidence(
            trajectory_id=str(execution.get("trajectory_id")),
            score=max(0.0, min(100.0, scalar * 100.0)),
            confidence=max(0.0, min(1.0, confidence)),
            dimensions=dimensions,
            reason_codes=tuple(reasons),
            recorded_at=str(execution.get("recorded_at") or ""),
        )

    @staticmethod
    def _feedback_by_trajectory(
        records: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            if record.get("source") != "user.feedback":
                continue
            trajectory_id = str(record.get("trajectory_id") or "").strip()
            if trajectory_id:
                grouped.setdefault(trajectory_id, []).append(record)
        return grouped

    @staticmethod
    def _feedback_score(records: list[dict[str, Any]]) -> float | None:
        scores: list[float] = []
        for record in records:
            feedback_type = str(record.get("feedback_type") or "")
            rating = record.get("rating")
            if isinstance(rating, (int, float)):
                scores.append(max(0.0, min(1.0, float(rating) / 5.0)))
                continue
            if feedback_type in {"thumbs_up", "task_completion_confirmation"}:
                scores.append(1.0)
            elif feedback_type in {"thumbs_down", "user_correction"}:
                scores.append(0.0)
            elif feedback_type in {"retry", "regeneration"}:
                scores.append(0.25)
            elif feedback_type == "follow_up_clarification":
                scores.append(0.5)
        if not scores:
            return None
        return sum(scores) / len(scores)

    def _quality_run(self, evidence: list[RewardEvidence]) -> int:
        run = 0
        for item in reversed(evidence):
            if item.score >= self._policy.quality_threshold * 100.0 and item.confidence >= 0.55:
                run += 1
            else:
                break
        return run

    @staticmethod
    def _confidence_weighted_average(evidence: list[RewardEvidence]) -> float:
        total_weight = sum(item.confidence for item in evidence)
        if total_weight <= 0.0:
            return 0.0
        return sum(item.score * item.confidence for item in evidence) / total_weight

    @staticmethod
    def _level(
        evidence: list[RewardEvidence],
        average_quality: float,
        quality_run: int,
    ) -> str:
        count = len(evidence)
        if count < 3:
            return "Foundation"
        if count < 10 or average_quality < 70.0:
            return "Momentum"
        if count < 25 or average_quality < 78.0:
            return "Reliable"
        if count < 50 or average_quality < 85.0 or quality_run < 5:
            return "Adaptive"
        return "Mastery"

    @staticmethod
    def _milestones(
        evidence: list[RewardEvidence],
        quality_run: int,
    ) -> list[ProgressMilestone]:
        durable = sum(
            1
            for item in evidence
            if item.dimensions.get("completion") == 1.0
            and item.dimensions.get("durability") == 1.0
        )
        verified = sum(
            1 for item in evidence if item.dimensions.get("verification", 0.0) >= 0.8
        )
        feedback = sum(1 for item in evidence if "user_feedback" in item.dimensions)
        resilient = sum(
            1
            for item in evidence
            if item.dimensions.get("completion") == 1.0
            and item.dimensions.get("resilience") == 1.0
        )
        specs = (
            (
                "first_durable_win",
                "Durable Win",
                "Complete work and persist its result successfully.",
                durable,
                1,
            ),
            (
                "quality_run_5",
                "Quality Run",
                "Deliver five evidence-backed high-quality outcomes in a row.",
                quality_run,
                5,
            ),
            (
                "verified_work_5",
                "Verified Work",
                "Accumulate five outcomes with strong verification evidence.",
                verified,
                5,
            ),
            (
                "feedback_loop_3",
                "Feedback Loop",
                "Connect three explicit user-feedback signals to completed work.",
                feedback,
                3,
            ),
            (
                "resilient_work_10",
                "Clean Runtime",
                "Complete ten successful outcomes without fallback pressure.",
                resilient,
                10,
            ),
        )
        return [
            ProgressMilestone(
                milestone_id=mid,
                title=title,
                description=description,
                unlocked=count >= threshold,
                evidence_count=count,
                threshold=threshold,
            )
            for mid, title, description, count, threshold in specs
        ]


__all__ = [
    "ProgressMilestone",
    "RewardEvidence",
    "RewardPolicy",
    "RewardProgressSnapshot",
    "RewardProjector",
]

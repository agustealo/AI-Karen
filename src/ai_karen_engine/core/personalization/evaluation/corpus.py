"""
Evaluation corpus for AI-Karen personalization.

Synthetic/non-private cases for deterministic lifecycle validation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List

from ..contracts import (
    BehaviorPattern,
    CurrentUserState,
    PreferenceEvidence,
    PreferenceEvidenceSourceType,
    PreferenceRecord,
    PreferenceScope,
    PreferenceState,
    PreferenceStability,
    UserGoal,
    UserStateSnapshot,
)


class EvaluationCorpus:
    """Synthetic evaluation cases for personalization."""

    @staticmethod
    def explicit_preference_case() -> Dict[str, Any]:
        return {
            "name": "explicit_preference",
            "interactions": [
                {"text": "I always want local models unless I explicitly allow cloud.", "source": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT}
            ],
            "expected": {"state": PreferenceState.STABLE, "min_confidence": 0.85, "scope": PreferenceScope.GLOBAL},
        }

    @staticmethod
    def temporary_preference_case() -> Dict[str, Any]:
        return {
            "name": "temporary_preference",
            "interactions": [
                {"text": "For this conversation give me terse answers.", "source": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT}
            ],
            "expected": {"state": PreferenceState.OBSERVED, "scope": PreferenceScope.CONVERSATION},
        }

    @staticmethod
    def contradictory_preference_case() -> Dict[str, Any]:
        return {
            "name": "contradictory_preference",
            "interactions": [
                {"text": "Give me short answers.", "source": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT},
                {"text": "I want detailed responses from now on.", "source": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT},
            ],
            "expected": {"state": PreferenceState.CONTRADICTED, "contradictions": 1},
        }

    @staticmethod
    def repeated_behavior_case() -> Dict[str, Any]:
        return {
            "name": "repeated_behavior",
            "interactions": [
                {"text": "Run audit.", "source": PreferenceEvidenceSourceType.REPEATED_BEHAVIOR},
                {"text": "Run audit.", "source": PreferenceEvidenceSourceType.REPEATED_BEHAVIOR},
                {"text": "Run audit.", "source": PreferenceEvidenceSourceType.REPEATED_BEHAVIOR},
            ],
            "expected": {"pattern_type": "audit_workflow", "min_observations": 3},
        }

    @staticmethod
    def domain_scoped_preference_case() -> Dict[str, Any]:
        return {
            "name": "domain_scoped_preference",
            "interactions": [
                {"text": "For architecture audits, give me detailed explanations.", "source": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT}
            ],
            "expected": {"state": PreferenceState.TENTATIVE, "scope": PreferenceScope.DOMAIN},
        }

    @staticmethod
    def single_weak_behavior_case() -> Dict[str, Any]:
        return {
            "name": "single_weak_behavior",
            "interactions": [
                {"text": "Used tool X once.", "source": PreferenceEvidenceSourceType.TOOL_SELECTION}
            ],
            "expected": {"state": PreferenceState.OBSERVED, "pattern_promoted": False},
        }

    @staticmethod
    def preference_reversal_case() -> Dict[str, Any]:
        return {
            "name": "preference_reversal",
            "interactions": [
                {"text": "I prefer concise answers.", "source": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT},
                {"text": "Actually, give me detailed explanations from now on.", "source": PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT},
            ],
            "expected": {"state": PreferenceState.CONTRADICTED, "version_incremented": True},
        }

    @staticmethod
    def stale_preference_case() -> Dict[str, Any]:
        old_date = datetime.utcnow() - timedelta(days=60)
        return {
            "name": "stale_preference",
            "interactions": [],
            "last_observed": old_date,
            "expected": {"state": PreferenceState.DECAYING},
        }

    @staticmethod
    def all_cases() -> List[Dict[str, Any]]:
        return [
            EvaluationCorpus.explicit_preference_case(),
            EvaluationCorpus.temporary_preference_case(),
            EvaluationCorpus.contradictory_preference_case(),
            EvaluationCorpus.repeated_behavior_case(),
            EvaluationCorpus.domain_scoped_preference_case(),
            EvaluationCorpus.single_weak_behavior_case(),
            EvaluationCorpus.preference_reversal_case(),
            EvaluationCorpus.stale_preference_case(),
        ]


__all__ = ["EvaluationCorpus"]

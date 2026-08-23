"""
Preference taxonomy catalog for AI-Karen personalization.

Defines the hierarchical preference key system and default weights.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..contracts import PreferenceCategory, PreferenceEvidenceSourceType


class PreferenceCatalog:
    """Canonical preference taxonomy and configuration."""

    CATEGORIES: List[PreferenceCategory] = [
        PreferenceCategory.COMMUNICATION,
        PreferenceCategory.WORKFLOW,
        PreferenceCategory.TOOL,
        PreferenceCategory.MODEL_LOCALITY,
        PreferenceCategory.OUTPUT_FORMAT,
        PreferenceCategory.AUTOMATION,
        PreferenceCategory.INTERACTION,
        PreferenceCategory.DOMAIN,
        PreferenceCategory.RISK,
        PreferenceCategory.PRIVACY,
    ]

    DEFAULT_EVIDENCE_WEIGHTS: Dict[PreferenceEvidenceSourceType, float] = {
        PreferenceEvidenceSourceType.EXPLICIT_USER_STATEMENT: 1.0,
        PreferenceEvidenceSourceType.USER_CORRECTION: 0.9,
        PreferenceEvidenceSourceType.TASK_OUTCOME: 0.7,
        PreferenceEvidenceSourceType.TOOL_SELECTION: 0.6,
        PreferenceEvidenceSourceType.REPEATED_BEHAVIOR: 0.5,
        PreferenceEvidenceSourceType.OUTPUT_EDIT: 0.4,
        PreferenceEvidenceSourceType.SYSTEM_INFERENCE: 0.2,
    }

    PROMOTION_THRESHOLDS: Dict[str, Dict[str, float]] = {
        "session": {"min_evidence": 1, "min_confidence": 0.7},
        "short_term": {"min_evidence": 2, "min_confidence": 0.75},
        "medium_term": {"min_evidence": 4, "min_confidence": 0.8},
        "long_term": {"min_evidence": 8, "min_confidence": 0.85},
        "durable": {"min_evidence": 15, "min_confidence": 0.9},
    }

    @classmethod
    def get_evidence_weight(cls, source_type: PreferenceEvidenceSourceType) -> float:
        return cls.DEFAULT_EVIDENCE_WEIGHTS.get(source_type, 0.3)

    @classmethod
    def get_promotion_threshold(cls, stability: str) -> Dict[str, float]:
        return cls.PROMOTION_THRESHOLDS.get(stability, {"min_evidence": 3, "min_confidence": 0.8})

    @classmethod
    def parse_key(cls, key: str) -> tuple[str, str]:
        parts = key.split(".", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return key, ""

    @classmethod
    def build_key(cls, category: str, attribute: str) -> str:
        return f"{category}.{attribute}"


__all__ = ["PreferenceCatalog"]

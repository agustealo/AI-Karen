from __future__ import annotations

from dataclasses import dataclass

from ai_karen_engine.config import load_memory_policy_config


@dataclass(frozen=True)
class NeuroMemorySettings:
    neuro_enabled: bool = True
    activation_gate_enabled: bool = True
    procedural_enabled: bool = True
    lesson_enabled: bool = True
    graph_escalation_enabled: bool = True
    writeback_review_required: bool = False
    fast_recall_timeout_ms: int = 250
    graph_recall_timeout_ms: int = 1200
    profile_timeout_ms: int = 400
    procedural_timeout_ms: int = 500
    writeback_timeout_ms: int = 800
    max_context_tokens: int = 1600
    max_profile_facts: int = 12
    max_procedures: int = 3
    max_lessons: int = 5


def get_neuro_settings() -> NeuroMemorySettings:
    cfg = load_memory_policy_config() or {}
    neuro = cfg.get("neuro", {}) if isinstance(cfg, dict) else {}
    return NeuroMemorySettings(
        neuro_enabled=neuro.get("KARI_MEMORY_NEURO_ENABLED", True),
        activation_gate_enabled=neuro.get("KARI_MEMORY_NEURO_ACTIVATION_GATE_ENABLED", True),
        procedural_enabled=neuro.get("KARI_MEMORY_NEURO_PROCEDURAL_ENABLED", True),
        lesson_enabled=neuro.get("KARI_MEMORY_NEURO_LESSON_ENABLED", True),
        graph_escalation_enabled=neuro.get("KARI_MEMORY_NEURO_GRAPH_ESCALATION_ENABLED", True),
        writeback_review_required=neuro.get("KARI_MEMORY_NEURO_WRITEBACK_REVIEW_REQUIRED", False),
        fast_recall_timeout_ms=neuro.get("KARI_MEMORY_FAST_RECALL_TIMEOUT_MS", 250),
        graph_recall_timeout_ms=neuro.get("KARI_MEMORY_GRAPH_RECALL_TIMEOUT_MS", 1200),
        profile_timeout_ms=neuro.get("KARI_MEMORY_PROFILE_TIMEOUT_MS", 400),
        procedural_timeout_ms=neuro.get("KARI_MEMORY_PROCEDURAL_TIMEOUT_MS", 500),
        writeback_timeout_ms=neuro.get("KARI_MEMORY_WRITEBACK_TIMEOUT_MS", 800),
        max_context_tokens=neuro.get("KARI_MEMORY_MAX_CONTEXT_TOKENS", 1600),
        max_profile_facts=neuro.get("KARI_MEMORY_MAX_PROFILE_FACTS", 12),
        max_procedures=neuro.get("KARI_MEMORY_MAX_PROCEDURES", 3),
        max_lessons=neuro.get("KARI_MEMORY_MAX_LESSONS", 5),
    )

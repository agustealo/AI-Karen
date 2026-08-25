"""Cognitive policy configuration for meta-cognition thresholds."""

from dataclasses import dataclass, field
from enum import Enum


class ThresholdDomain(str, Enum):
    MEMORY = "memory"
    REASONING = "reasoning"
    EVIDENCE = "evidence"
    VERIFICATION = "verification"
    LOOP = "loop"
    CONTEXT = "context"


@dataclass(slots=True)
class CognitiveThresholds:
    weak_memory_threshold: float = 0.4
    weak_reasoning_threshold: float = 0.3
    weak_evidence_threshold: float = 0.3
    verification_threshold: float = 0.4
    deep_reasoning_threshold: float = 0.5
    loop_repeat_threshold: int = 3
    max_reconsideration_steps: int = 5
    minimum_information_gain: float = 0.1
    low_confidence_abort_threshold: float = 0.2
    high_confidence_trust_threshold: float = 0.8
    budget_exhaustion_threshold: int = 1

    def should_verify_memory(self, reliability: float) -> bool:
        return reliability < self.verification_threshold

    def should_deepen_reasoning(self, confidence: float) -> bool:
        return confidence < self.deep_reasoning_threshold

    def is_memory_weak(self, reliability: float) -> bool:
        return reliability < self.weak_memory_threshold

    def is_reasoning_weak(self, confidence: float) -> bool:
        return confidence < self.weak_reasoning_threshold

    def is_evidence_weak(self, consistency: float) -> bool:
        return consistency < self.weak_evidence_threshold

    def is_loop_detected(self, repeat_count: int) -> bool:
        return repeat_count >= self.loop_repeat_threshold

    def has_budget_remaining(self, budget: int) -> bool:
        return budget > self.budget_exhaustion_threshold

    def meets_information_gain(self, gain: float) -> bool:
        return gain >= self.minimum_information_gain

    def should_trust_confidence(self, confidence: float) -> bool:
        return confidence >= self.high_confidence_trust_threshold

    def should_abort_low_confidence(self, confidence: float) -> bool:
        return confidence < self.low_confidence_abort_threshold


@dataclass(slots=True)
class CognitivePolicyConfig:
    version: str = "1.0.0"
    thresholds: CognitiveThresholds = field(default_factory=CognitiveThresholds)
    enable_loop_detection: bool = True
    enable_budget_tracking: bool = True
    enable_calibration: bool = True
    enable_context_validation: bool = True
    strict_mode: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def get_thresholds(self) -> CognitiveThresholds:
        return self.thresholdes

    def is_strict_mode(self) -> bool:
        return self.strict_mode

    def with_strict_mode(self, strict: bool = True) -> "CognitivePolicyConfig":
        return CognitivePolicyConfig(
            version=self.version,
            thresholds=self.thresholds,
            enable_loop_detection=self.enable_loop_detection,
            enable_budget_tracking=self.enable_budget_tracking,
            enable_calibration=self.enable_calibration,
            enable_context_validation=self.enable_context_validation,
            strict_mode=strict,
            metadata=self.metadata.copy(),
        )
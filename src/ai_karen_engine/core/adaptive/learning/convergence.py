"""Learning convergence ledger for adaptive learning system."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LearningGeneration(str, Enum):
    """Learning system generation identifiers."""
    POLICY_LEGACY = "policy_legacy"
    EXPERIENCE_MODERN = "experience_modern"


class ConvergenceStatus(str, Enum):
    """Status of learning convergence."""
    DIVERGENT = "divergent"
    CONVERGING = "converging"
    CONVERGED = "converged"
    MIGRATED = "migrated"
    DEPRECATED = "deprecated"


@dataclass(slots=True)
class LearningPathMapping:
    """Maps legacy learning paths to modern equivalents."""
    legacy_path: str
    modern_path: str
    generation: LearningGeneration = LearningGeneration.POLICY_LEGACY
    migration_status: ConvergenceStatus = ConvergenceStatus.DIVERGENT
    equivalence_score: float = 0.0
    migration_date: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LearningConvergenceLedger:
    """Central ledger for tracking learning system convergence."""
    
    path_mappings: list[LearningPathMapping] = field(default_factory=list)
    
    observation_authority: str = "experience_modern"
    reward_authority: str = "experience_modern"
    promotion_authority: str = "experience_modern"
    utility_authority: str = "experience_modern"
    
    deprecation_timeline: dict[str, str] = field(default_factory=dict)
    migration_warnings: list[str] = field(default_factory=list)
    
    convergence_target_date: str = "2026-09-01"
    current_status: ConvergenceStatus = ConvergenceStatus.CONVERGING
    
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_mapping(self, legacy: str, modern: str, equivalence: float = 1.0) -> None:
        mapping = LearningPathMapping(
            legacy_path=legacy,
            modern_path=modern,
            equivalence_score=equivalence,
        )
        self.path_mappings.append(mapping)

    def get_modern_path(self, legacy_path: str) -> str | None:
        for mapping in self.path_mappings:
            if mapping.legacy_path == legacy_path:
                return mapping.modern_path
        return None

    def is_legacy_deprecated(self, legacy_path: str) -> bool:
        for mapping in self.path_mappings:
            if mapping.legacy_path == legacy_path:
                return mapping.migration_status == ConvergenceStatus.DEPRECATED
        return False

    def get_authority(self, domain: str) -> str:
        authorities = {
            "observation": self.observation_authority,
            "reward": self.reward_authority,
            "promotion": self.promotion_authority,
            "utility": self.utility_authority,
        }
        return authorities.get(domain, "experience_modern")

    def record_migration(self, legacy_path: str, status: ConvergenceStatus) -> None:
        for mapping in self.path_mappings:
            if mapping.legacy_path == legacy_path:
                mapping.migration_status = status
                break

    def add_migration_warning(self, warning: str) -> None:
        if warning not in self.migration_warnings:
            self.migration_warnings.append(warning)

    def get_unmigrated_paths(self) -> list[LearningPathMapping]:
        return [m for m in self.path_mappings 
                if m.migration_status in (ConvergenceStatus.DIVERGENT, ConvergenceStatus.CONVERGING)]

    def get_convergence_percentage(self) -> float:
        if not self.path_mappings:
            return 0.0
        converged = sum(1 for m in self.path_mappings 
                       if m.migration_status == ConvergenceStatus.CONVERGED)
        return (converged / len(self.path_mappings)) * 100.0

    def is_fully_converged(self) -> bool:
        return self.current_status == ConvergenceStatus.CONVERGED


_default_ledger = LearningConvergenceLedger(
    path_mappings=[
        LearningPathMapping(
            legacy_path="observations.py",
            modern_path="experience/normalization.py",
            generation=LearningGeneration.POLICY_LEGACY,
            migration_status=ConvergenceStatus.CONVERGED,
            equivalence_score=0.95,
        ),
        LearningPathMapping(
            legacy_path="utility.py",
            modern_path="experience/reward.py",
            generation=LearningGeneration.POLICY_LEGACY,
            migration_status=ConvergenceStatus.CONVERGED,
            equivalence_score=0.90,
        ),
        LearningPathMapping(
            legacy_path="promotion.py",
            modern_path="experience/reflection_contracts.py",
            generation=LearningGeneration.POLICY_LEGACY,
            migration_status=ConvergenceStatus.CONVERGING,
            equivalence_score=0.85,
        ),
        LearningPathMapping(
            legacy_path="aggregates.py",
            modern_path="experience/attribution.py",
            generation=LearningGeneration.POLICY_LEGACY,
            migration_status=ConvergenceStatus.CONVERGING,
            equivalence_score=0.80,
        ),
        LearningPathMapping(
            legacy_path="contextual_policy.py",
            modern_path="experience/contracts.py",
            generation=LearningGeneration.POLICY_LEGACY,
            migration_status=ConvergenceStatus.CONVERGING,
            equivalence_score=0.75,
        ),
    ],
    deprecation_timeline={
        "observations.py": "2026-09-15",
        "utility.py": "2026-09-15",
        "promotion.py": "2026-10-01",
        "aggregates.py": "2026-10-01",
        "contextual_policy.py": "2026-10-01",
    },
)


def get_convergence_ledger() -> LearningConvergenceLedger:
    return _default_ledger


def is_legacy_path(path: str) -> bool:
    ledger = get_convergence_ledger()
    return any(m.legacy_path == path for m in ledger.path_mappings)


def get_modern_equivalent(path: str) -> str | None:
    ledger = get_convergence_ledger()
    return ledger.get_modern_path(path)
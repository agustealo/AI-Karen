"""
Memory Policy Engine - Phase 4.1.b
Implements configurable decay tiers and importance-based retention policies.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import yaml

from ai_karen_engine.config import load_memory_policy_config
from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


class DecayTier(str, Enum):
    """Memory decay tiers with retention periods"""

    SHORT = "short"  # 1-7 days
    MEDIUM = "medium"  # 14-45 days
    LONG = "long"  # 90-180 days
    PINNED = "pinned"  # indefinite


class ImportanceLevel(int, Enum):
    """Importance levels for memory classification"""

    TRIVIAL = 1
    LOW = 2
    MINOR = 3
    MODERATE = 4
    NORMAL = 5
    NOTABLE = 6
    IMPORTANT = 7
    CRITICAL = 8
    ESSENTIAL = 9
    PERMANENT = 10


@dataclass(frozen=True)
class MemoryPolicy:
    """Configurable memory policy with decay tiers and importance scoring"""

    # Query configuration
    top_k: int = 6
    rerank_window_factor: float = 3.0
    similarity_threshold: float = 0.7

    # Decay tier configuration (days)
    decay_map: dict[str, int | None] = field(
        default_factory=lambda: {
            DecayTier.SHORT: 7,  # 1-7 days
            DecayTier.MEDIUM: 30,  # 14-45 days
            DecayTier.LONG: 180,  # 90-180 days
            DecayTier.PINNED: None,  # indefinite
        }
    )

    # Importance-based tier assignment
    importance_long_threshold: int = 8  # importance ≥8 → long-term retention
    importance_medium_threshold: int = 5  # importance ≥5 → medium-term retention
    importance_short_threshold: int = 1  # importance ≥1 → short-term retention

    # Feedback loop configuration
    used_shard_rate_threshold: float = 0.3  # Minimum usage rate for promotion
    ignored_top_hit_rate_threshold: float = 0.7  # Maximum ignore rate before demotion

    # Auto-promotion/demotion settings
    auto_promotion_enabled: bool = True
    auto_demotion_enabled: bool = True
    promotion_usage_count: int = 5  # Minimum usage count for promotion consideration
    demotion_ignore_count: int = 10  # Minimum ignore count for demotion consideration

    # Recency weighting
    recency_alpha: float = 0.05  # Exponential decay factor for recency weighting

    @staticmethod
    def load(path: str | None = None) -> "MemoryPolicy":
        """Load memory policy from config_assets/memory.yml with fallback defaults"""
        # First try explicit path
        if path and os.path.exists(path):
            try:
                with open(path, "r") as f:
                    config = yaml.safe_load(f) or {}
                logger.info(f"Loaded memory policy from {path}")
                return MemoryPolicy._from_config(config)
            except Exception as e:
                logger.warning(f"Failed to load memory policy from {path}: {e}")

        # Try environment override
        env_override = os.getenv("KARI_MEMORY_POLICY_PATH", "").strip()
        if env_override and os.path.exists(env_override):
            try:
                with open(env_override, "r") as f:
                    config = yaml.safe_load(f) or {}
                logger.info(f"Loaded memory policy from {env_override}")
                return MemoryPolicy._from_config(config)
            except Exception as e:
                logger.warning(f"Failed to load memory policy from {env_override}: {e}")

        # Use canonical loader
        config = load_memory_policy_config()
        if config:
            logger.info("Loaded memory policy from config_assets/memory.yml")
            return MemoryPolicy._from_config(config)

        logger.info("Memory policy file not found. Using defaults.")
        return MemoryPolicy()

    @staticmethod
    def _from_config(config: dict[str, Any]) -> "MemoryPolicy":
        """Create MemoryPolicy from configuration dictionary"""
        # Extract decay map configuration
        decay_config = config.get("decay_tiers", {})
        decay_map = {
            DecayTier.SHORT: decay_config.get("short", 7),
            DecayTier.MEDIUM: decay_config.get("medium", 30),
            DecayTier.LONG: decay_config.get("long", 180),
            DecayTier.PINNED: decay_config.get("pinned", None),
        }

        # Extract importance thresholds
        importance_config = config.get("importance_thresholds", {})

        # Extract feedback loop configuration
        feedback_config = config.get("feedback_loop", {})

        # Extract auto-promotion/demotion settings
        auto_config = config.get("auto_adjustment", {})

        return MemoryPolicy(
            top_k=config.get("top_k", 6),
            rerank_window_factor=config.get("rerank_window_factor", 3.0),
            similarity_threshold=config.get("similarity_threshold", 0.7),
            decay_map=decay_map,
            importance_long_threshold=importance_config.get("long_threshold", 8),
            importance_medium_threshold=importance_config.get("medium_threshold", 5),
            importance_short_threshold=importance_config.get("short_threshold", 1),
            used_shard_rate_threshold=feedback_config.get(
                "used_shard_rate_threshold", 0.3
            ),
            ignored_top_hit_rate_threshold=feedback_config.get(
                "ignored_top_hit_rate_threshold", 0.7
            ),
            auto_promotion_enabled=auto_config.get("promotion_enabled", True),
            auto_demotion_enabled=auto_config.get("demotion_enabled", True),
            promotion_usage_count=auto_config.get("promotion_usage_count", 5),
            demotion_ignore_count=auto_config.get("demotion_ignore_count", 10),
            recency_alpha=config.get("recency_alpha", 0.05),
        )

    def assign_decay_tier(self, importance: int) -> DecayTier:
        """Assign decay tier based on importance score"""
        if importance >= self.importance_long_threshold:
            return DecayTier.LONG
        elif importance >= self.importance_medium_threshold:
            return DecayTier.MEDIUM
        elif importance >= self.importance_short_threshold:
            return DecayTier.SHORT
        else:
            return DecayTier.SHORT  # Default to short for any valid importance

    def calculate_expiry_date(
        self, decay_tier: DecayTier, created_at: datetime | None = None
    ) -> datetime | None:
        """Calculate expiry date based on decay tier"""
        if decay_tier == DecayTier.PINNED:
            return None  # Never expires

        if created_at is None:
            created_at = datetime.utcnow()

        retention_days = self.decay_map.get(decay_tier)
        if retention_days is None:
            return None

        return created_at + timedelta(days=retention_days)

    def is_expired(self, decay_tier: DecayTier, created_at: datetime) -> bool:
        """Check if memory has expired based on decay tier"""
        if decay_tier == DecayTier.PINNED:
            return False

        expiry_date = self.calculate_expiry_date(decay_tier, created_at)
        if expiry_date is None:
            return False

        return datetime.utcnow() > expiry_date

    def calculate_rerank_window(self, top_k: int) -> int:
        """Calculate rerank window size based on top_k and window factor"""
        return min(int(top_k * self.rerank_window_factor), 50)  # Cap at 50

    def should_promote_tier(
        self, current_tier: DecayTier, usage_stats: dict[str, Any]
    ) -> bool:
        """Determine if memory should be promoted to higher tier based on usage"""
        if not self.auto_promotion_enabled:
            return False

        if current_tier == DecayTier.PINNED:
            return False  # Already at highest tier

        usage_count = usage_stats.get("usage_count", 0)
        total_retrievals = usage_stats.get("total_retrievals", 0)

        if usage_count < self.promotion_usage_count:
            return False

        if total_retrievals == 0:
            return False

        usage_rate = usage_count / total_retrievals
        return usage_rate >= self.used_shard_rate_threshold

    def should_demote_tier(
        self, current_tier: DecayTier, usage_stats: dict[str, Any]
    ) -> bool:
        """Determine if memory should be demoted to lower tier based on usage"""
        if not self.auto_demotion_enabled:
            return False

        if current_tier == DecayTier.SHORT:
            return False  # Already at lowest tier

        ignore_count = usage_stats.get("ignore_count", 0)
        total_retrievals = usage_stats.get("total_retrievals", 0)

        if ignore_count < self.demotion_ignore_count:
            return False

        if total_retrievals == 0:
            return False

        ignore_rate = ignore_count / total_retrievals
        return ignore_rate >= self.ignored_top_hit_rate_threshold

    def get_next_tier_up(self, current_tier: DecayTier) -> DecayTier | None:
        """Get the next higher tier for promotion"""
        tier_hierarchy = [
            DecayTier.SHORT,
            DecayTier.MEDIUM,
            DecayTier.LONG,
            DecayTier.PINNED,
        ]

        try:
            current_index = tier_hierarchy.index(current_tier)
            if current_index < len(tier_hierarchy) - 1:
                return tier_hierarchy[current_index + 1]
        except ValueError:
            pass

        return None

    def get_next_tier_down(self, current_tier: DecayTier) -> DecayTier | None:
        """Get the next lower tier for demotion"""
        tier_hierarchy = [
            DecayTier.SHORT,
            DecayTier.MEDIUM,
            DecayTier.LONG,
            DecayTier.PINNED,
        ]

        try:
            current_index = tier_hierarchy.index(current_tier)
            if current_index > 0:
                return tier_hierarchy[current_index - 1]
        except ValueError:
            pass

        return None

    def calculate_importance_boost(
        self, base_importance: int, usage_stats: dict[str, Any]
    ) -> int:
        """Calculate importance boost based on usage patterns"""
        usage_count = usage_stats.get("usage_count", 0)
        total_retrievals = usage_stats.get("total_retrievals", 0)
        recency_score = usage_stats.get("recency_score", 0.0)

        boost = 0

        # Usage frequency boost
        if total_retrievals > 0:
            usage_rate = usage_count / total_retrievals
            if usage_rate >= 0.8:
                boost += 2
            elif usage_rate >= 0.5:
                boost += 1

        # Recency boost
        if recency_score >= 0.9:
            boost += 1

        # High usage count boost
        if usage_count >= 20:
            boost += 1
        elif usage_count >= 10:
            boost += 0.5

        # Ensure we don't exceed maximum importance
        return min(base_importance + int(boost), ImportanceLevel.PERMANENT)

    def to_dict(self) -> dict[str, Any]:
        """Convert policy to dictionary for serialization"""
        return {
            "top_k": self.top_k,
            "rerank_window_factor": self.rerank_window_factor,
            "similarity_threshold": self.similarity_threshold,
            "decay_tiers": {
                "short": self.decay_map[DecayTier.SHORT],
                "medium": self.decay_map[DecayTier.MEDIUM],
                "long": self.decay_map[DecayTier.LONG],
                "pinned": self.decay_map[DecayTier.PINNED],
            },
            "importance_thresholds": {
                "long_threshold": self.importance_long_threshold,
                "medium_threshold": self.importance_medium_threshold,
                "short_threshold": self.importance_short_threshold,
            },
            "feedback_loop": {
                "used_shard_rate_threshold": self.used_shard_rate_threshold,
                "ignored_top_hit_rate_threshold": self.ignored_top_hit_rate_threshold,
            },
            "auto_adjustment": {
                "promotion_enabled": self.auto_promotion_enabled,
                "demotion_enabled": self.auto_demotion_enabled,
                "promotion_usage_count": self.promotion_usage_count,
                "demotion_ignore_count": self.demotion_ignore_count,
            },
            "recency_alpha": self.recency_alpha,
        }


class MemoryPolicyManager:
    """Manager for memory policy operations and feedback loops"""

    def __init__(self, policy: MemoryPolicy | None = None):
        """Initialize with memory policy"""
        self.policy = policy or MemoryPolicy.load()
        self._usage_stats_cache = {}

    def reload_policy(self, path: str | None = None):
        """Reload policy from configuration file"""
        self.policy = MemoryPolicy.load(path)
        logger.info("Memory policy reloaded")

    def evaluate_memory_for_adjustment(
        self,
        memory_id: str,
        current_tier: DecayTier,
        current_importance: int,
        usage_stats: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate memory for tier/importance adjustment"""
        recommendations = {
            "memory_id": memory_id,
            "current_tier": current_tier,
            "current_importance": current_importance,
            "should_promote": False,
            "should_demote": False,
            "recommended_tier": current_tier,
            "importance_boost": 0,
            "recommended_importance": current_importance,
            "reasons": [],
        }

        # Check for tier promotion
        if self.policy.should_promote_tier(current_tier, usage_stats):
            next_tier = self.policy.get_next_tier_up(current_tier)
            if next_tier:
                recommendations["should_promote"] = True
                recommendations["recommended_tier"] = next_tier
                recommendations["reasons"].append(
                    f"High usage rate qualifies for promotion to {next_tier}"
                )

        # Check for tier demotion (only if not promoting)
        elif self.policy.should_demote_tier(current_tier, usage_stats):
            next_tier = self.policy.get_next_tier_down(current_tier)
            if next_tier:
                recommendations["should_demote"] = True
                recommendations["recommended_tier"] = next_tier
                recommendations["reasons"].append(
                    f"High ignore rate qualifies for demotion to {next_tier}"
                )

        # Calculate importance boost
        importance_boost = self.policy.calculate_importance_boost(
            current_importance, usage_stats
        )
        if importance_boost > current_importance:
            recommendations["importance_boost"] = importance_boost - current_importance
            recommendations["recommended_importance"] = importance_boost
            recommendations["reasons"].append(
                f"Usage patterns suggest importance boost of {recommendations['importance_boost']}"
            )

        return recommendations

    def calculate_feedback_metrics(
        self, retrieval_logs: list[dict[str, Any]]
    ) -> dict[str, float]:
        """Calculate feedback loop metrics from retrieval logs"""
        if not retrieval_logs:
            return {
                "used_shard_rate": 0.0,
                "ignored_top_hit_rate": 0.0,
                "total_retrievals": 0,
                "total_used": 0,
                "total_ignored_top_hits": 0,
            }

        total_retrievals = len(retrieval_logs)
        total_used = sum(1 for log in retrieval_logs if log.get("used", False))

        # Count ignored top hits (when top result was not used)
        total_ignored_top_hits = sum(
            1 for log in retrieval_logs if log.get("top_hit_ignored", False)
        )

        used_shard_rate = total_used / total_retrievals if total_retrievals > 0 else 0.0
        ignored_top_hit_rate = (
            total_ignored_top_hits / total_retrievals if total_retrievals > 0 else 0.0
        )

        return {
            "used_shard_rate": used_shard_rate,
            "ignored_top_hit_rate": ignored_top_hit_rate,
            "total_retrievals": total_retrievals,
            "total_used": total_used,
            "total_ignored_top_hits": total_ignored_top_hits,
        }

    def get_policy_summary(self) -> dict[str, Any]:
        """Get summary of current policy configuration"""
        return {
            "policy": self.policy.to_dict(),
            "tier_retention_days": {
                tier: self.policy.decay_map[DecayTier(tier)]
                for tier in ["short", "medium", "long", "pinned"]
            },
            "importance_tier_mapping": {
                f"importance_{i}": self.policy.assign_decay_tier(i).value
                for i in range(1, 11)
            },
        }


# Create default policy manager instance
default_policy_manager = MemoryPolicyManager()

# Export public interface
__all__ = [
    "DecayTier",
    "ImportanceLevel",
    "MemoryPolicy",
    "MemoryPolicyManager",
    "default_policy_manager",
]

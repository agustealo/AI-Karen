"""
Hierarchical truncation policy for PromptRuntime.

Defines truncation behavior with item-aware strategies and priority levels.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class TruncationStrategy(str, Enum):
    """Strategies for truncating prompt sections."""
    REMOVE_ENTIRE_SECTION = "remove_entire_section"
    REMOVE_OLDEST_ITEMS = "remove_oldest_items"
    TRIM_VERBOSE_DESCRIPTIONS = "trim_verbose_descriptions"
    COMPRESS_SUMMARY = "compress_summary"


class SectionPriority(int, Enum):
    """Priority levels for prompt sections (lower = more protected)."""
    SYSTEM_POLICY = 0
    TENANT_POLICY = 1
    SAFETY = 2
    OUTPUT_CONTRACT = 3
    LATEST_USER_MESSAGE = 4
    PERSONA = 5
    CORTEX = 6
    PROFILE = 7
    MEMORY = 8
    TOOL_CONTRACTS = 9
    WORKFLOW = 10
    HISTORY = 11


class SectionProtection(str, Enum):
    """Protection levels for sections."""
    PROTECTED = "protected"  # Never truncate
    COMPRESSIBLE = "compressible"  # Can be summarized/trimmed
    DROPPABLE = "droppable"  # Can be removed entirely
    ITEM_TRIMMABLE = "item_trimmable"  # Individual items can be removed


@dataclass
class TruncationRule:
    """Defines how a section should be truncated."""
    section_name: str
    priority: SectionPriority
    protection: SectionProtection
    strategy: TruncationStrategy
    min_keep_percentage: float = 0.0  # Minimum percentage to keep if item_trimmable


class HierarchicalTruncationPolicy:
    """Policy-driven truncation with item-aware strategies."""
    
    def __init__(self) -> None:
        self.rules = self._default_rules()
    
    def _default_rules(self) -> Dict[str, TruncationRule]:
        """Create default truncation rules."""
        return {
            "system": TruncationRule(
                section_name="system",
                priority=SectionPriority.SYSTEM_POLICY,
                protection=SectionProtection.PROTECTED,
                strategy=TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "output": TruncationRule(
                section_name="output",
                priority=SectionPriority.OUTPUT_CONTRACT,
                protection=SectionProtection.PROTECTED,
                strategy=TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "persona": TruncationRule(
                section_name="persona",
                priority=SectionPriority.PERSONA,
                protection=SectionProtection.COMPRESSIBLE,
                strategy=TruncationStrategy.TRIM_VERBOSE_DESCRIPTIONS,
            ),
            "cortex": TruncationRule(
                section_name="cortex",
                priority=SectionPriority.CORTEX,
                protection=SectionProtection.DROPPABLE,
                strategy=TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "profile": TruncationRule(
                section_name="profile",
                priority=SectionPriority.PROFILE,
                protection=SectionProtection.ITEM_TRIMMABLE,
                strategy=TruncationStrategy.REMOVE_OLDEST_ITEMS,
                min_keep_percentage=0.5,
            ),
            "provider_capabilities": TruncationRule(
                section_name="provider_capabilities",
                priority=SectionPriority.MEMORY,
                protection=SectionProtection.DROPPABLE,
                strategy=TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "memory": TruncationRule(
                section_name="memory",
                priority=SectionPriority.MEMORY,
                protection=SectionProtection.ITEM_TRIMMABLE,
                strategy=TruncationStrategy.REMOVE_OLDEST_ITEMS,
                min_keep_percentage=0.3,
            ),
            "tool": TruncationRule(
                section_name="tool",
                priority=SectionPriority.TOOL_CONTRACTS,
                protection=SectionProtection.ITEM_TRIMMABLE,
                strategy=TruncationStrategy.TRIM_VERBOSE_DESCRIPTIONS,
                min_keep_percentage=0.5,
            ),
            "workflow": TruncationRule(
                section_name="workflow",
                priority=SectionPriority.WORKFLOW,
                protection=SectionProtection.DROPPABLE,
                strategy=TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "user": TruncationRule(
                section_name="user",
                priority=SectionPriority.LATEST_USER_MESSAGE,
                protection=SectionProtection.PROTECTED,
                strategy=TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "assistant": TruncationRule(
                section_name="assistant",
                priority=SectionPriority.HISTORY,
                protection=SectionProtection.ITEM_TRIMMABLE,
                strategy=TruncationStrategy.REMOVE_OLDEST_ITEMS,
                min_keep_percentage=0.2,
            ),
        }
    
    def get_rule(self, section_name: str) -> Optional[TruncationRule]:
        """Get truncation rule for a section."""
        return self.rules.get(section_name)
    
    def can_truncate(self, section_name: str) -> bool:
        """Check if a section can be truncated."""
        rule = self.get_rule(section_name)
        return rule is not None and rule.protection != SectionProtection.PROTECTED
    
    def get_truncation_order(self) -> List[str]:
        """Get sections ordered by truncation priority (highest priority first)."""
        sorted_rules = sorted(
            self.rules.values(),
            key=lambda r: r.priority.value,
            reverse=True
        )
        return [rule.section_name for rule in sorted_rules]
    
    def add_rule(self, rule: TruncationRule) -> None:
        """Add or update a truncation rule."""
        self.rules[rule.section_name] = rule
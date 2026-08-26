"""Hierarchical truncation policy for PromptRuntime.

This module is the single PromptRuntime budget-selection policy. Domain owners
must rank their own inputs before handing them to PromptRuntime. This policy only
chooses which already-authorized prompt sections/items survive token pressure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional

from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptAssemblyRequest,
    PromptTruncationEvent,
)


class TruncationStrategy(str, Enum):
    REMOVE_ENTIRE_SECTION = "remove_entire_section"
    REMOVE_OLDEST_ITEMS = "remove_oldest_items"
    TRIM_VERBOSE_DESCRIPTIONS = "trim_verbose_descriptions"
    COMPRESS_SUMMARY = "compress_summary"


class SectionPriority(int, Enum):
    """Prompt section priority. Lower values are more protected."""

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
    PROTECTED = "protected"
    COMPRESSIBLE = "compressible"
    DROPPABLE = "droppable"
    ITEM_TRIMMABLE = "item_trimmable"


@dataclass(frozen=True)
class TruncationRule:
    section_name: str
    priority: SectionPriority
    protection: SectionProtection
    strategy: TruncationStrategy
    min_keep_percentage: float = 0.0


class HierarchicalTruncationPolicy:
    """Apply one deterministic, policy-driven prompt truncation path.

    Memory/tool inputs are assumed to arrive best-first from their canonical
    owners, so pressure removes items from the tail. Conversation history is
    different: the latest user message is always protected and older messages
    are removed first.
    """

    def __init__(self) -> None:
        self.rules = self._default_rules()

    def _default_rules(self) -> Dict[str, TruncationRule]:
        return {
            "system": TruncationRule(
                "system",
                SectionPriority.SYSTEM_POLICY,
                SectionProtection.PROTECTED,
                TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "output": TruncationRule(
                "output",
                SectionPriority.OUTPUT_CONTRACT,
                SectionProtection.PROTECTED,
                TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "persona": TruncationRule(
                "persona",
                SectionPriority.PERSONA,
                SectionProtection.COMPRESSIBLE,
                TruncationStrategy.TRIM_VERBOSE_DESCRIPTIONS,
            ),
            "cortex": TruncationRule(
                "cortex",
                SectionPriority.CORTEX,
                SectionProtection.DROPPABLE,
                TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "profile": TruncationRule(
                "profile",
                SectionPriority.PROFILE,
                SectionProtection.COMPRESSIBLE,
                TruncationStrategy.TRIM_VERBOSE_DESCRIPTIONS,
            ),
            "provider_capabilities": TruncationRule(
                "provider_capabilities",
                SectionPriority.MEMORY,
                SectionProtection.DROPPABLE,
                TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "memory": TruncationRule(
                "memory",
                SectionPriority.MEMORY,
                SectionProtection.ITEM_TRIMMABLE,
                TruncationStrategy.REMOVE_OLDEST_ITEMS,
                min_keep_percentage=0.3,
            ),
            "tool": TruncationRule(
                "tool",
                SectionPriority.TOOL_CONTRACTS,
                SectionProtection.ITEM_TRIMMABLE,
                TruncationStrategy.TRIM_VERBOSE_DESCRIPTIONS,
                min_keep_percentage=0.5,
            ),
            "workflow": TruncationRule(
                "workflow",
                SectionPriority.WORKFLOW,
                SectionProtection.DROPPABLE,
                TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "user": TruncationRule(
                "user",
                SectionPriority.LATEST_USER_MESSAGE,
                SectionProtection.PROTECTED,
                TruncationStrategy.REMOVE_ENTIRE_SECTION,
            ),
            "history": TruncationRule(
                "history",
                SectionPriority.HISTORY,
                SectionProtection.ITEM_TRIMMABLE,
                TruncationStrategy.REMOVE_OLDEST_ITEMS,
                min_keep_percentage=0.0,
            ),
        }

    def get_rule(self, section_name: str) -> Optional[TruncationRule]:
        return self.rules.get(section_name)

    def can_truncate(self, section_name: str) -> bool:
        rule = self.get_rule(section_name)
        return rule is not None and rule.protection != SectionProtection.PROTECTED

    def get_truncation_order(self) -> List[str]:
        return [
            rule.section_name
            for rule in sorted(
                self.rules.values(),
                key=lambda rule: rule.priority.value,
                reverse=True,
            )
            if rule.protection != SectionProtection.PROTECTED
        ]

    def add_rule(self, rule: TruncationRule) -> None:
        self.rules[rule.section_name] = rule

    def enforce(
        self,
        request: PromptAssemblyRequest,
        estimate_tokens: Callable[[PromptAssemblyRequest], object],
    ) -> List[PromptTruncationEvent]:
        """Mutate a working request copy until it fits the configured budget.

        The caller owns copying the request. Returning events makes every
        omission observable through the existing PromptRuntime provenance path.
        """

        events: List[PromptTruncationEvent] = []

        def total_tokens() -> int:
            estimate = estimate_tokens(request)
            return int(getattr(estimate, "total_tokens", 0))

        while total_tokens() > request.token_budget:
            changed = False
            for section in self.get_truncation_order():
                before = total_tokens()
                if before <= request.token_budget:
                    break

                removed = self._truncate_once(request, section)
                if removed <= 0:
                    continue

                after = total_tokens()
                rule = self.rules[section]
                events.append(
                    PromptTruncationEvent(
                        section=section,
                        reason="token_pressure",
                        original_tokens=before,
                        remaining_tokens=after,
                        items_removed=removed,
                        strategy=rule.strategy.value,
                        tokens_before=before,
                        tokens_after=after,
                        priority=rule.priority.value,
                    )
                )
                changed = True
                if after <= request.token_budget:
                    break

            if not changed:
                break

        return events

    def _truncate_once(self, request: PromptAssemblyRequest, section: str) -> int:
        if section == "history":
            return self._remove_oldest_history_message(request)
        if section == "workflow" and request.workflow_context:
            request.workflow_context = {}
            return 1
        if section == "provider_capabilities" and request.provider_capabilities:
            request.provider_capabilities = {}
            return 1
        if section == "tool" and request.tool_contracts:
            keep = max(0, int(len(request.tool_contracts) * self.rules[section].min_keep_percentage))
            if len(request.tool_contracts) <= keep:
                return 0
            request.tool_contracts.pop()
            return 1
        if section == "memory" and request.memory_items:
            keep = max(0, int(len(request.memory_items) * self.rules[section].min_keep_percentage))
            if len(request.memory_items) <= keep:
                return 0
            request.memory_items.pop()
            return 1
        if section == "profile" and request.profile:
            request.profile = {}
            return 1
        if section == "cortex" and request.cortex_intent:
            request.cortex_intent = {}
            return 1
        if section == "persona" and request.persona:
            request.persona = {}
            return 1
        return 0

    @staticmethod
    def _remove_oldest_history_message(request: PromptAssemblyRequest) -> int:
        if len(request.messages) <= 1:
            return 0

        latest_user_index: Optional[int] = None
        for index in range(len(request.messages) - 1, -1, -1):
            if str(request.messages[index].get("role", "")).lower() == "user":
                latest_user_index = index
                break

        for index, message in enumerate(request.messages):
            if index == latest_user_index:
                continue
            role = str(message.get("role", "")).lower()
            if role in {"user", "assistant"}:
                request.messages.pop(index)
                return 1
        return 0

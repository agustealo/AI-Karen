"""Adaptive action catalog.

Central registry of canonical action types.
No arbitrary action strings scattered across code.
"""

from __future__ import annotations

from ai_karen_engine.core.adaptive.contracts import (
    AdaptiveActionType,
)


class AdaptiveActionCatalog:
    """Central registry of adaptive action types and metadata."""

    _ACTIONS: frozenset[AdaptiveActionType] = frozenset(
        {
            AdaptiveActionType.RESPOND_DIRECTLY,
            AdaptiveActionType.ASK_CLARIFICATION,
            AdaptiveActionType.RETRIEVE_MEMORY,
            AdaptiveActionType.USE_TOOL,
            AdaptiveActionType.USE_WORKFLOW,
            AdaptiveActionType.USE_AGENT,
            AdaptiveActionType.USE_MULTI_AGENT,
            AdaptiveActionType.SUGGEST_ACTION,
            AdaptiveActionType.DO_NOTHING,
        }
    )

    _PROVIDER_SPECIFIC_ACTIONS: frozenset[str] = frozenset(
        {
            "use_vllm",
            "use_gpt",
            "use_anthropic",
            "use_gemini",
            "use_ollama",
            "use_lmstudio",
            "use_sglang",
        }
    )

    @classmethod
    def all_actions(cls) -> frozenset[AdaptiveActionType]:
        return cls._ACTIONS

    @classmethod
    def is_valid_action(cls, action: str) -> bool:
        try:
            return AdaptiveActionType(action) in cls._ACTIONS
        except ValueError:
            return False

    @classmethod
    def is_provider_specific(cls, action: str) -> bool:
        return action.lower() in cls._PROVIDER_SPECIFIC_ACTIONS

    @classmethod
    def default_candidates(cls) -> list[AdaptiveActionType]:
        return [
            AdaptiveActionType.RESPOND_DIRECTLY,
            AdaptiveActionType.RETRIEVE_MEMORY,
            AdaptiveActionType.ASK_CLARIFICATION,
        ]

    @classmethod
    def tool_adjacent_actions(cls) -> set[AdaptiveActionType]:
        return {
            AdaptiveActionType.USE_TOOL,
            AdaptiveActionType.USE_WORKFLOW,
            AdaptiveActionType.USE_AGENT,
            AdaptiveActionType.USE_MULTI_AGENT,
        }

    @classmethod
    def non_execution_actions(cls) -> set[AdaptiveActionType]:
        return {
            AdaptiveActionType.RESPOND_DIRECTLY,
            AdaptiveActionType.ASK_CLARIFICATION,
            AdaptiveActionType.RETRIEVE_MEMORY,
            AdaptiveActionType.SUGGEST_ACTION,
            AdaptiveActionType.DO_NOTHING,
        }

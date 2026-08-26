"""
TokenEstimator authority for PromptRuntime.

Provides a protocol for token estimation with pluggable implementations.
The default implementation uses a deterministic heuristic, but provider-specific
tokenizers can be injected when available.
"""

from __future__ import annotations

from typing import Dict, List, Protocol, runtime_checkable


@runtime_checkable
class TokenEstimator(Protocol):
    """Protocol for token estimation in prompt assembly."""

    def estimate_text(self, text: str) -> int:
        """Estimate token count for plain text."""
        ...

    def estimate_messages(self, messages: List[Dict[str, any]]) -> int:
        """Estimate token count for a list of messages."""
        ...


class DeterministicHeuristicTokenEstimator:
    """Deterministic heuristic token estimator as fallback implementation."""

    # Constants based on typical token-to-character ratios
    AVG_CHARS_PER_TOKEN = 4
    MIN_TOKENS = 1

    def estimate_text(self, text: str) -> int:
        """Estimate token count from text length using deterministic heuristic."""
        if not text:
            return 0
        return max(self.MIN_TOKENS, len(text) // self.AVG_CHARS_PER_TOKEN)

    def estimate_messages(self, messages: List[Dict[str, any]]) -> int:
        """Estimate token count for messages, accounting for message overhead."""
        total = 0
        
        # Base overhead per message (role markers, formatting)
        MESSAGE_OVERHEAD = 4
        
        for msg in messages:
            content = str(msg.get("content", ""))
            role_overhead = len(str(msg.get("role", "user"))) + 2  # role name + formatting
            
            total += MESSAGE_OVERHEAD
            total += role_overhead
            total += self.estimate_text(content)
        
        return total


# Default global estimator instance
_default_estimator: TokenEstimator = DeterministicHeuristicTokenEstimator()


def get_token_estimator() -> TokenEstimator:
    """Return the global token estimator instance."""
    return _default_estimator


def set_token_estimator(estimator: TokenEstimator) -> None:
    """Set the global token estimator instance."""
    global _default_estimator
    _default_estimator = estimator
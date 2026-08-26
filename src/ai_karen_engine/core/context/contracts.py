"""Canonical context-domain contract surface.

Context owns context-domain vocabulary only. Cross-domain scope and the
cognitive snapshot remain owned by their existing canonical modules so this
package does not create a second scope or cognitive-state authority.
"""

from __future__ import annotations

from ai_karen_engine.core.cognitive.state import ContextSnapshot
from ai_karen_engine.core.contracts.cognitive import CognitiveScope

# Context scope is the canonical cross-domain CognitiveScope. Keep the alias as
# identity, not a wrapper/subclass, so tenant semantics cannot drift.
ContextScope = CognitiveScope

__all__ = ["ContextScope", "ContextSnapshot"]

from __future__ import annotations

"""Sunset type alias for legacy graph constructors.

Concrete session-state implementations must be injected from the composition edge.
"""

from ai_karen_engine.core.runtime.session_state_port import SessionStatePort

SessionStateManager = SessionStatePort

__all__ = ["SessionStateManager"]

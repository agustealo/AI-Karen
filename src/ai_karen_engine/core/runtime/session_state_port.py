from __future__ import annotations

"""Session-state contract owned by Core runtime.

CopilotKit, Redis, database, or other session implementations live outside Core
and may be injected at the composition edge.
"""

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class SessionStatePort(Protocol):
    async def load_session_state(self, session_id: str) -> Mapping[str, Any] | None: ...

    async def save_session_state(
        self,
        session_id: str,
        state: Mapping[str, Any],
    ) -> None: ...

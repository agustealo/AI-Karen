"""Retired response execution adapter.

The public name remains import-compatible during the legacy caller audit.
ResponsePromptBuilder, ResponseValidator and ResponseSanitizer are independent
content-policy helpers; this facade must not grant model execution.
"""

from __future__ import annotations

from typing import Any

from .response_contracts import ResponseContract


class ResponseSynthesizer:
    """Compatibility boundary; use the authenticated ChatRuntime entrypoint.

    A ResponseContract and a router do not carry an issued execution plan,
    original meter, authenticated principal, or trusted evidence snapshot.
    Adapting these objects into an execution grant would bypass RuntimePolicy.
    """

    def __init__(self, llm_router: Any):
        # Retain the historical constructor shape, not a router or executor.
        pass

    async def synthesize(
        self,
        contract: ResponseContract,
        *,
        user_preferences: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        stream: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        # Neither caller-controlled preferences nor apparent tool receipts
        # can substitute for the live runtime authority. No canned response,
        # provider selection, retry, or emergency success is returned.
        raise PermissionError("legacy_response_synthesis_requires_chat_runtime")

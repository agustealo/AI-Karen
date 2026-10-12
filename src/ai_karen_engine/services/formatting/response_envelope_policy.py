"""Envelope-specific redaction and output limits, independent of text policy.

The LangGraph adapter delegates envelope cleanup here. This does not choose
models, synthesize content or alter the canonical runtime's evidence decisions.
"""
from __future__ import annotations

from typing import Any


class ResponseEnvelopePolicy:
    """Preserve the historical LangGraph envelope safety contract."""

    RESTRICTED_FIELDS = frozenset({
        "internal_state",
        "raw_llm_response",
        "intermediate_steps",
        "debug_info",
        "system_metrics",
    })
    MAX_RESPONSE_CHARS = 100000

    def enforce_policies(self, response_data: dict[str, Any]) -> dict[str, Any]:
        cleaned = {
            key: value
            for key, value in response_data.items()
            if key not in self.RESTRICTED_FIELDS
        }
        if "response" not in cleaned:
            cleaned["response"] = cleaned.get("content", "")
        if isinstance(cleaned["response"], str):
            if len(cleaned["response"]) > self.MAX_RESPONSE_CHARS:
                cleaned["response"] = (
                    cleaned["response"][: self.MAX_RESPONSE_CHARS]
                    + "... (truncated)"
                )
        return cleaned

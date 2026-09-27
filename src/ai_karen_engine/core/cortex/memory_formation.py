"""CORTEX memory-formation request policy.

This module decides whether an interaction should enter governed candidate
formation. It does not persist memory and does not authorize ``memory.write``.
RuntimePolicy remains the authorization owner; MemoryFormationEvaluator remains
the admission owner; NeuroVault remains the durable mutation boundary.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


def request_memory_formation(
    request: ChatExecutionRequest,
    decision: ExecutionDecision,
) -> ExecutionDecision:
    """Request governed candidate formation for an eligible user interaction.

    Ordinary interaction is the observation source from which KAREN may learn.
    Requesting candidate formation is intentionally broader than memory recall:
    Formation still has to extract a worthy signal, privacy/consent guards must
    admit it, RuntimePolicy must authorize ``memory.write``, and NeuroVault must
    accept the scoped write before anything becomes durable.
    """

    user_text = _latest_user_text(request).strip()
    if not user_text:
        return decision

    constraints = dict(decision.policy_constraints or {})
    if bool(constraints.get("memory_write_denied", False)):
        return decision

    requested = list(decision.required_capabilities)
    if "memory.write" not in requested:
        requested.append("memory.write")

    constraints.update(
        {
            "memory_formation_requested": True,
            # Compatibility bridge consumed by RuntimeDecisionPipeline until
            # ExecutionDecision grows a dedicated formation-request field.
            "memory_write_requested": True,
            "memory_formation_source": "user_interaction",
        }
    )

    reason_codes = list(decision.reason_codes)
    if "memory_formation_requested" not in reason_codes:
        reason_codes.append("memory_formation_requested")

    return replace(
        decision,
        required_capabilities=requested,
        policy_constraints=constraints,
        reason_codes=reason_codes,
    )


def _latest_user_text(request: ChatExecutionRequest) -> str:
    for message in reversed(request.messages or []):
        if str(message.get("role") or "").casefold() == "user":
            return str(message.get("content") or "")
    return ""


__all__ = ["request_memory_formation"]

"""Canonical task-definition adapter for ChatRuntime execution.

Task definitions are product concepts, not an alternate AI runtime. This module
converts an authenticated task invocation into the canonical
``ChatExecutionRequest`` contract and delegates execution to ``ChatRuntime``.
It deliberately performs no provider selection, policy authorization, plugin
execution, or fallback handling; those remain owned by ChatRuntime/CORTEX and
RuntimePolicy.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping, Optional

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionResult,
)

TASK_EXECUTION_PROMPT_VERSION = "task-definition.v1"


def _task_message(task: Mapping[str, Any]) -> str:
    """Render the versioned task contract as the user message for ChatRuntime."""
    sub_agents = task.get("subAgents") or []
    parts = [
        "Execute the following saved task definition.",
        f"Task name: {str(task.get('name') or '').strip()}",
        f"Task type: {str(task.get('taskType') or 'saved_task').strip()}",
        f"Requested primary agent: {str(task.get('primaryAgent') or '').strip()}",
        f"Task description: {str(task.get('description') or '').strip()}",
    ]

    primary_instructions = str(task.get("primaryAgentInstructions") or "").strip()
    if primary_instructions:
        parts.append(f"Task instructions: {primary_instructions}")

    if sub_agents:
        parts.append(
            "Delegation requirements: "
            + json.dumps(sub_agents, ensure_ascii=False, sort_keys=True)
        )

    return "\n".join(parts)


def _requested_agents(task: Mapping[str, Any]) -> list[str]:
    """Return the ordered unique agents explicitly requested by the task."""
    requested: list[str] = []

    primary = str(task.get("primaryAgent") or "").strip()
    if primary:
        requested.append(primary)

    for sub_agent in task.get("subAgents") or []:
        if not isinstance(sub_agent, Mapping):
            continue
        agent_id = str(sub_agent.get("agentId") or "").strip()
        if agent_id and agent_id not in requested:
            requested.append(agent_id)

    return requested


async def execute_task_definition(
    task: Mapping[str, Any],
    *,
    user: UserData,
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> ChatExecutionResult:
    """Execute a saved task through the single authoritative ChatRuntime."""
    user_id = str(user.user_id or "").strip()
    tenant_id = str(user.tenant_id or "").strip()
    if not user_id:
        raise ValueError("Authenticated user_id is required for task execution")
    if not tenant_id or tenant_id == "default":
        raise ValueError("Explicit tenant_id is required for task execution")

    task_id = str(task.get("id") or "").strip()
    resolved_request_id = str(request_id or "").strip() or str(uuid.uuid4())
    resolved_correlation_id = (
        str(correlation_id or "").strip() or resolved_request_id
    )
    requested_agents = _requested_agents(task)

    context = ChatExecutionContext(
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=f"task:{task_id}" if task_id else None,
        conversation_id=f"task:{task_id}" if task_id else None,
        request_id=resolved_request_id,
        correlation_id=resolved_correlation_id,
        roles=list(user.roles or []),
    )
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": _task_message(task)}],
        context=context,
        metadata={
            "source": "saved_task",
            "task_definition_id": task_id,
            "task_type": str(task.get("taskType") or "saved_task"),
            "primary_agent": str(task.get("primaryAgent") or ""),
            "requested_agents": requested_agents,
            "agent_delegation": bool(requested_agents),
            "force_graph": bool(requested_agents),
            "prompt_contract": TASK_EXECUTION_PROMPT_VERSION,
        },
    )
    return await get_chat_runtime().execute(request)


__all__ = [
    "TASK_EXECUTION_PROMPT_VERSION",
    "execute_task_definition",
]

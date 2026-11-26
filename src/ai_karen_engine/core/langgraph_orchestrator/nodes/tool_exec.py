"""Tool execution node for LangGraph orchestration."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ai_karen_engine.services.tooling.tool_service import ToolOutput, ToolService

from ..contracts.orchestration_state import LangGraphOrchestrationState

logger = logging.getLogger(__name__)


@dataclass
class ToolExecutionConfig:
    """Configuration for tool execution."""

    include_metadata: bool = True
    allow_unknown_tools: bool = False
    default_user_context: Dict[str, Any] = field(default_factory=dict)


class ToolExecutionNode:
    """Fail closed on graph tool calls until a governed receipt adapter is wired."""

    def __init__(
        self,
        config: Optional[ToolExecutionConfig] = None,
        tool_service: Optional[ToolService] = None,
    ):
        self.config = config or ToolExecutionConfig()
        # Retain the constructor contract while the shared governed tool
        # receipt owner is migrated. Do not initialize or invoke raw tooling.
        self._tool_service = tool_service

    async def __call__(
        self, state: LangGraphOrchestrationState
    ) -> LangGraphOrchestrationState:
        logger.info("Tool execution processing")
        try:
            tool_calls = state.get("tool_calls") or []
            if not tool_calls:
                state["tool_results"] = []
                state["tool_execution_metadata"] = {
                    "executed_tools": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                }
                return state

            state = await self.execute_tools(state, tool_calls)
            state["execution_summary"] = self._build_execution_summary(
                state.get("tool_results") or []
            )
            logger.info("Tool execution completed")
        except PermissionError:
            raise
        except Exception as e:
            logger.error("Tool execution error: %s", e)
            state.setdefault("errors", []).append(f"Tool execution error: {e}")

        return state

    async def execute_tools(
        self, state: LangGraphOrchestrationState, tool_calls: List[Dict[str, Any]]
    ) -> LangGraphOrchestrationState:
        # Raw graph ToolService calls have neither the original shared
        # budget nor a durable governed invocation receipt. No serialized
        # plan, cached result, or tool name can substitute for that grant.
        if tool_calls:
            raise PermissionError("workflow_tool_execution_receipt_required")
        state["tool_results"] = []
        state["tool_execution_metadata"] = self._build_execution_summary([])
        state["execution_summary"] = state["tool_execution_metadata"]
        return state

    def _build_user_context(self, state: LangGraphOrchestrationState) -> Dict[str, Any]:
        context = dict(self.config.default_user_context)
        context.update(
            {
                "user_id": state.get("user_id"),
                "session_id": state.get("session_id"),
                "conversation_id": state.get("conversation_id"),
                "selected_provider": state.get("selected_provider"),
                "selected_model": state.get("selected_model"),
                "runtime_level": state.get("runtime_level", "FULL"),
            }
        )
        return context

    def _build_execution_summary(
        self, tool_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        executed = len(tool_results)
        successful = len([result for result in tool_results if result.get("success")])
        failed = executed - successful
        return {
            "executed_tools": executed,
            "successful_executions": successful,
            "failed_executions": failed,
        }

    def _result_to_dict(self, result: ToolOutput) -> Dict[str, Any]:
        metadata = result.metadata or {}
        payload = {
            "tool_name": metadata.get("tool_name"),
            "success": result.success,
            "status": "success" if result.success else "failed",
            "output": result.result,
            "error": result.error,
            "execution_time_ms": int(result.execution_time * 1000),
            "metadata": metadata,
            "request_id": result.request_id,
        }
        if self.config.include_metadata:
            payload["cached"] = bool(metadata.get("cached", False))
        return payload


async def tool_exec_node(
    state: LangGraphOrchestrationState,
    tool_service: Optional[ToolService] = None,
) -> LangGraphOrchestrationState:
    """Convenience wrapper for LangGraph orchestration."""
    node = ToolExecutionNode(tool_service=tool_service)
    return await node(state)

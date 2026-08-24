"""
LangChain adapter for AgentMedusa.

Executes Medusa specialists through LangChain's AgentExecutor while
respecting the AuthorizedExecutionPlan and using Medusa's bridges for
model and tool access.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ...contracts.runtime_request import RuntimeRequest
from ...contracts.runtime_response import RuntimeResponse, ResponseStatus
from ...specialists.bridges import GenerationBridge, ToolBridge

logger = logging.getLogger(__name__)


class LangChainAdapter:
    """LangChain execution adapter for Medusa specialists.

    Provides a bridge between Medusa's contract-driven execution and
    LangChain's AgentExecutor, using GenerationBridge for LLM access
    and ToolBridge for tool side effects.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    async def execute(
        self,
        request: RuntimeRequest,
        agent_id: str,
        plan: Optional[AuthorizedExecutionPlan] = None,
    ) -> RuntimeResponse:
        """Execute a specialist via LangChain AgentExecutor."""
        try:
            from langchain.agents import AgentExecutor
            from langchain.agents.conversational_chat.base import (
                ConversationalChatAgent,
            )
        except ImportError as exc:
            logger.error("LangChain is required but not installed: %s", exc)
            return RuntimeResponse(
                request_id=request.request_id,
                status=ResponseStatus.ERROR,
                content="LangChain is not installed",
                metadata={"error": "langchain_not_installed"},
            )

        plan_data = self._plan_to_dict(plan) if plan else {}
        allowed_tools = plan_data.get("allowed_tools", [])

        tools = await self._build_tools(allowed_tools, request, plan_data)
        llm = await self._build_llm(request, plan_data)

        agent = ConversationalChatAgent.from_llm_and_tools(
            llm=llm,
            tools=tools,
            verbose=self.config.get("verbose", False),
        )

        agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=self.config.get("verbose", False),
            max_execution_time=self.config.get("max_execution_time", 60),
            handle_parsing_errors=True,
        )

        messages = request.context.get("messages") or [request.query]
        input_text = messages[-1] if messages else request.query

        try:
            result = await agent_executor.ainvoke({"input": input_text})
            content = result.get("output") if isinstance(result, dict) else str(result)
            return RuntimeResponse(
                request_id=request.request_id,
                status=ResponseStatus.SUCCESS,
                content=content,
                metadata={"agent_id": agent_id, "framework": "langchain"},
            )
        except Exception as exc:
            logger.error("LangChain execution failed for %s: %s", agent_id, exc)
            return RuntimeResponse(
                request_id=request.request_id,
                status=ResponseStatus.ERROR,
                content=str(exc),
                metadata={"error": str(exc), "agent_id": agent_id},
            )

    async def _build_tools(
        self,
        allowed_tools: List[str],
        request: RuntimeRequest,
        plan_data: Dict[str, Any],
    ) -> List[Any]:
        tools: List[Any] = []
        for tool_name in allowed_tools:
            tool = await self._create_tool(tool_name, request, plan_data)
            if tool is not None:
                tools.append(tool)
        return tools

    async def _create_tool(
        self, tool_name: str, request: RuntimeRequest, plan_data: Dict[str, Any]
    ) -> Optional[Any]:
        try:
            from langchain.tools import BaseTool
        except ImportError:
            return None

        async def _run(*args: Any, **kwargs: Any) -> str:
            tool_bridge = ToolBridge()
            result = await tool_bridge.execute(
                tool_name=tool_name,
                arguments=kwargs or {"args": args},
                execution_context=request.context.get("execution_context"),
            )
            return str(result)

        class _DynamicTool(BaseTool):
            name: str = tool_name
            description: str = f"Tool {tool_name}"

            def _run(self, *args: Any, **kwargs: Any) -> str:
                import asyncio

                return asyncio.get_event_loop().run_until_complete(
                    _run(*args, **kwargs)
                )

            async def _arun(self, *args: Any, **kwargs: Any) -> str:
                return await _run(*args, **kwargs)

        return _DynamicTool()

    async def _build_llm(
        self, request: RuntimeRequest, plan_data: Dict[str, Any]
    ) -> Any:
        generation_bridge = GenerationBridge()
        generation_request = {
            "query": request.query,
            "context": request.context,
            "policy_decision_id": plan_data.get("policy_decision_id"),
            "provider_constraints": plan_data.get("provider_constraints", {}),
        }
        return _LangChainLLMWrapper(generation_bridge, generation_request)


class _LangChainLLMWrapper:
    """Wraps Medusa GenerationBridge as a LangChain-compatible LLM."""

    def __init__(
        self, generation_bridge: GenerationBridge, request: Dict[str, Any]
    ) -> None:
        self._bridge = generation_bridge
        self._request = request

    async def ainvoke(self, prompt: Any, **kwargs: Any) -> Any:
        from langchain_core.messages import AIMessage
        result = await self._bridge.invoke(
            {
                "query": str(prompt),
                "context": self._request.get("context", {}),
                "policy_decision_id": self._request.get("policy_decision_id"),
            }
        )
        return AIMessage(content=str(result))

    def invoke(self, prompt: Any, **kwargs: Any) -> Any:
        import asyncio

        return asyncio.get_event_loop().run_until_complete(
            self.ainvoke(prompt, **kwargs)
        )

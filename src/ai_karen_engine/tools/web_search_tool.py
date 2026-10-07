"""
Web Search Tool for AI-Karen
Production-ready web search tool using InternetCapabilityService.
"""

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.services.tooling.tool_service import BaseTool, ToolMetadata, ToolCategory, ToolParameter, List
from ai_karen_engine.services.tooling.internet_capability_service import InternetCapabilityService
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionContext,
)
from ai_karen_engine.tools.http_client_tool import HTTPClientTool
from ai_karen_engine.tools.filesystem_tool import FileSystemTool
from ai_karen_engine.tools.text_processing_tool import TextProcessingTool
from ai_karen_engine.tools.data_analysis_tool import DataAnalysisTool
from ai_karen_engine.tools.system_resources_tool import SystemResourcesTool

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Web search and internet intelligence tool plugin."""

    def __init__(self):
        super().__init__()
        self._service = None

    def _get_service(self):
        if self._service is None:
            self._service = InternetCapabilityService()
        return self._service

    def _create_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="web_search",
            description="Search the live internet for information, news, documentation, and data.",
            category=ToolCategory.CORE,
            version="1.0.0",
            author="AI Karen",
            parameters=[
                ToolParameter(
                    name="query",
                    type=str,
                    description="The search query or question to research",
                    required=True
                ),
                ToolParameter(
                    name="mode",
                    type=str,
                    description="Search mode: general, news, docs, deep_research, weather, stock_market",
                    required=False,
                    default="general"
                ),
                ToolParameter(
                    name="max_urls",
                    type=int,
                    description="Maximum number of sources to crawl",
                    required=False,
                    default=5
                )
            ],
            return_type=dict,
            examples=[
                {
                    "description": "General search",
                    "parameters": {"query": "latest news about SpaceX Starship"}
                },
                {
                    "description": "Documentation search",
                    "parameters": {"query": "FastAPI background tasks", "mode": "docs"}
                }
            ],
            tags=["search", "internet", "web", "research", "news"],
            timeout=60
        )

    async def _execute(self, parameters: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Any:
        query = parameters["query"]
        mode = parameters.get("mode", "general")
        max_urls = parameters.get("max_urls", 5)

        raw_context = dict(context or {})
        authorized_plan = raw_context.get("authorized_plan")
        if not isinstance(authorized_plan, AuthorizedExecutionPlan):
            authorized_plan = None

        execution_context = ExecutionContext(
            request_id=str(raw_context.get("request_id") or ""),
            correlation_id=str(raw_context.get("correlation_id") or ""),
            user_id=str(raw_context.get("user_id") or ""),
            tenant_id=str(raw_context.get("tenant_id") or ""),
            session_id=raw_context.get("session_id"),
            conversation_id=raw_context.get("conversation_id"),
            policy_decision_id=(
                authorized_plan.policy_decision_id
                if authorized_plan is not None
                else raw_context.get("policy_decision_id")
            ),
            allowed_capabilities=list(
                raw_context.get("allowed_capabilities") or []
            ),
            budget=(
                authorized_plan.budget
                if authorized_plan is not None
                else None
            ),
        )

        service = self._get_service()
        result = await service.execute(
            query,
            config_override={
                "mode": mode,
                "max_urls": max_urls,
            },
            context=execution_context,
            authorized_plan=authorized_plan,
        )

        return result


def get_production_tools() -> List[BaseTool]:
    return [
        WebSearchTool(),
        HTTPClientTool(),
        FileSystemTool(),
        TextProcessingTool(),
        DataAnalysisTool(),
        SystemResourcesTool()
    ]


def register_production_tools(tool_registry):
    tools = get_production_tools()
    registered_count = 0

    for tool in tools:
        try:
            tool_registry.register_tool(tool)
            registered_count += 1
            logger.info(f"Registered production tool: {tool.metadata.name}")
        except Exception as e:
            logger.error(f"Failed to register tool {tool.metadata.name}: {e}")

    logger.info(f"Registered {registered_count}/{len(tools)} production tools")
    return registered_count

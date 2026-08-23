"""
Web Search Tool for AI-Karen
Production-ready web search tool using InternetCapabilityService.
"""

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.services.tooling.tool_service import BaseTool, ToolMetadata, ToolCategory, ToolParameter, List
from ai_karen_engine.services.tooling.internet_capability_service import InternetCapabilityService
from ai_karen_engine.tools.http_client_tool import HTTPClientTool
from ai_karen_engine.tools.filesystem_tool import FileSystemTool
from ai_karen_engine.tools.text_processing_tool import TextProcessingTool
from ai_karen_engine.tools.data_analysis_tool import DataAnalysisTool

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

        service = self._get_service()
        result = await service.execute(query, config_override={
            "mode": mode,
            "max_urls": max_urls
        })

        return result


def get_production_tools() -> List[BaseTool]:
    return [
        WebSearchTool(),
        HTTPClientTool(),
        FileSystemTool(),
        TextProcessingTool(),
        DataAnalysisTool()
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

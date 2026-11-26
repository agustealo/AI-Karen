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
    ExecutionBudgetMeter,
)
# Compatibility exports; the package catalog owns production discovery.
from ai_karen_engine.tools import get_production_tools, register_production_tools  # noqa: F401

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
                ),
                ToolParameter(
                    name="allowed_domains",
                    type=list,
                    description="Restrict results to these domains",
                    required=False,
                    validation_rules={"min_length": 1, "max_length": 50},
                ),
                ToolParameter(
                    name="blocked_domains",
                    type=list,
                    description="Exclude these domains",
                    required=False,
                    validation_rules={"min_length": 1, "max_length": 50},
                ),
                ToolParameter(
                    name="time_range",
                    type=str,
                    description="Provider search time range",
                    required=False,
                    validation_rules={"min_length": 1, "max_length": 32},
                ),
                ToolParameter(
                    name="prefer_recent",
                    type=bool,
                    description="Prefer recently published sources",
                    required=False,
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
        config_override = {"mode": mode, "max_urls": max_urls}
        for key in ("allowed_domains", "blocked_domains"):
            if key not in parameters:
                continue
            domains = parameters[key]
            if not isinstance(domains, list) or not 1 <= len(domains) <= 50 or any(
                not isinstance(domain, str) or not domain.strip() or len(domain) > 253
                for domain in domains
            ):
                raise ValueError(f"Invalid {key} restriction")
            config_override[key] = domains
        for key in ("time_range", "prefer_recent"):
            if key in parameters:
                config_override[key] = parameters[key]
        if mode == "weather" and any(
            key in config_override
            for key in ("allowed_domains", "blocked_domains", "time_range", "prefer_recent")
        ):
            raise ValueError("Weather observations do not support web source restrictions")

        raw_context = dict(context or {})
        authorized_plan = raw_context.get("authorized_plan")
        if not isinstance(authorized_plan, AuthorizedExecutionPlan):
            authorized_plan = None

        meter = raw_context.get("execution_meter")
        runtime_context = raw_context.get("runtime_search_context")
        if meter is not None or runtime_context is not None:
            from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext

            if (
                not isinstance(meter, ExecutionBudgetMeter)
                or not isinstance(runtime_context, ChatExecutionContext)
                or authorized_plan is None
                or not runtime_context.is_runtime_model_plan_authorized(authorized_plan, meter)
                or "web_search" not in authorized_plan.allowed_tools
                or any(
                    raw_context.get(key) != getattr(runtime_context, key)
                    for key in ("user_id", "tenant_id", "session_id", "correlation_id")
                )
            ):
                raise PermissionError("Invalid runtime search execution authority")

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
            config_override=config_override,
            context=execution_context,
            authorized_plan=authorized_plan,
            **({"execution_meter": meter} if meter is not None else {}),
        )

        return result

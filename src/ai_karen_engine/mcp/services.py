"""Wrapper services exposing internal tools via MCP."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ai_karen_engine.mcp.registry import ServiceRegistry
from ai_karen_engine.mcp.base import AuthorizationError
from ai_karen_engine.services.knowledge import KnowledgeGraphUnavailableError
from ai_karen_engine.integrations.llm_utils import LLMUtils


class KnowledgeGraphService:
    """Retired MCP adapter: raw Cypher is not a governed memory tool."""

    def __init__(
        self,
        kg_client: Any,
        registry: ServiceRegistry,
        name: str = "knowledge_graph",
    ) -> None:
        # Reject before registry registration; even a caller-injected database
        # client cannot bypass tenant, source-consent or tool permissions.
        raise KnowledgeGraphUnavailableError(
            "Raw graph MCP execution is disabled; use runtime-authorized recall"
        )

class LLMService:
    """Expose LLMUtils via MCP."""

    def __init__(self, llm: LLMUtils, registry: ServiceRegistry, name: str = "llm"):
        self.llm = llm
        self.registry = registry
        self.registry.register(name, "local", "local", roles=["admin", "user"])
        self.name = name

    def generate_text(self, prompt: str, provider: Optional[str] = None, rbac_ctx: Optional[Dict[str, Any]] = None) -> str:
        roles = rbac_ctx.get("roles") if rbac_ctx else []
        if "admin" not in roles and "user" not in roles:
            raise AuthorizationError("RBAC denied")
        return self.llm.generate_text(prompt, provider=provider)


from __future__ import annotations

"""Read-only system resource tool backed by the canonical platform snapshot."""

from typing import Any, Dict, Optional

from ai_karen_engine.core.runtime.platform_resource_service import (
    get_platform_resource_service,
)
from ai_karen_engine.services.tooling.tool_service import (
    BaseTool,
    ToolCategory,
    ToolMetadata,
)


class SystemResourcesTool(BaseTool):
    """Inspect current local CPU, memory, GPU, VRAM, and disk availability."""

    def _create_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="system_resources",
            description=(
                "Inspect Karen's current local machine resources including CPU, "
                "RAM, GPU, VRAM, and disk capacity."
            ),
            category=ToolCategory.SYSTEM,
            version="1.0.0",
            author="AI Karen",
            parameters=[],
            return_type=dict,
            examples=[
                {"description": "Check current system resources", "parameters": {}},
                {"description": "See remaining RAM, VRAM, and disk", "parameters": {}},
            ],
            tags=[
                "system",
                "resources",
                "cpu",
                "ram",
                "memory",
                "gpu",
                "vram",
                "disk",
                "local-runtime",
            ],
            requires_auth=True,
            timeout=5,
        )

    async def _execute(
        self,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        del parameters, context
        return get_platform_resource_service().snapshot().as_dict()


__all__ = ["SystemResourcesTool"]

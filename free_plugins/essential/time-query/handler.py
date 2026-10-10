import logging
from typing import Any, Dict, Optional
from ai_karen_engine.extensions.platform.core.host.base import (
    ExtensionBase,
    ExtensionContext,
    HookContext,
    HookPoint,
)

from .handlers import (
    handle_current_time,
    handle_world_time,
    handle_multi_clock,
    handle_stopwatch,
    handle_alarm,
    handle_timezone_conversion
)

logger = logging.getLogger(__name__)

SUPPORTED_MODES = {
    "datetime", "date", "time", "timestamp", "timezone", 
    "iso", "utc", "external_time", "sync_status", "validate_time_source",
    "world_time", "multi_clock", "stopwatch", "alarm", "convert_timezone"
}

class TimeQueryExtension(ExtensionBase):
    """Extension for date and time queries."""
    
    def __init__(self, manifest, context: ExtensionContext):
        super().__init__(manifest, context)

    async def initialize(self) -> None:
        """Initialize the extension."""
        self.logger.info(f"Initializing {self.manifest.name} extension")

    async def shutdown(self) -> None:
        """Shutdown the extension."""
        self.logger.info(f"Shutting down {self.manifest.name} extension")

    def get_status(self) -> Dict[str, Any]:
        """Return the current status of the extension."""
        return {
            "status": "healthy",
            "initialized": True,
            "version": self.manifest.version,
        }

    async def execute_hook(
        self, hook_point: HookPoint, context: HookContext
    ) -> Dict[str, Any]:
        """Execute a hook point."""
        # Simple implementation for time query hooks
        params = context.data if hasattr(context, "data") else {}
        return await self.run(params)

    async def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Provide time features based on mode requests."""
        mode = params.get("mode", "datetime")
        
        if mode not in SUPPORTED_MODES:
            return {"error": f"Unsupported mode: {mode}"}
            
        try:
            if mode in ["datetime", "date", "time", "timestamp", "timezone", "iso", "utc", "external_time", "sync_status", "validate_time_source"]:
                result = await handle_current_time(mode, params)
            elif mode == "world_time":
                result = await handle_world_time(params)
            elif mode == "multi_clock":
                result = await handle_multi_clock(params)
            elif mode == "stopwatch":
                result = await handle_stopwatch(params)
            elif mode == "alarm":
                result = await handle_alarm(params)
            elif mode == "convert_timezone":
                result = await handle_timezone_conversion(params)
            else:
                result = {"error": f"Unhandled mode mapping: {mode}"}
                
            return {**result, "status": "success"} if "error" not in result else {**result, "status": "error"}
            
        except Exception as e:
            logger.exception(f"Error executing time_query mode {mode}")
            return {"error": str(e), "status": "error"}

class MainExtension(TimeQueryExtension):
    """Entry point for ExtensionLoader."""
    pass

async def run(params: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy entrypoint (optional)."""
    result = await handle_current_time("datetime", params)
    return {"formatted": result.get("formatted", ""), "status": "success"}
import asyncio
import json
from ai_karen_engine.core.runtime.chat_runtime_control_plane import get_chat_runtime_control_plane
from ai_karen_engine.core.services.service_registry import initialize_services

async def check_status():
    # Populate service registry first
    await initialize_services()
    
    plane = await get_chat_runtime_control_plane()
    # Force a health check
    await plane._run_health_checks()
    await plane.reconcile_mode("Diagnostic check")
    
    status = await plane.get_runtime_authority_status()
    print(json.dumps(status, indent=2, default=str))

if __name__ == "__main__":
    asyncio.run(check_status())

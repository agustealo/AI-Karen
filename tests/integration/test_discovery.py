import asyncio
import os
from ai_karen_engine.core.model_runtime.model_discovery_service import ModelDiscoveryService

async def main():
    service = ModelDiscoveryService()
    # Ensure it scans
    models = await service.discover_all_models()
    print(f"Total discovered: {len(models)}")
    
    for rt in ["builtin_vllm", "builtin_transformers", "openai"]:
        rt_models = service.get_models(runtime=rt)
        print(f"Runtime '{rt}': {len(rt_models)} models")
        for m in rt_models:
            print(f"  - {m.model_id} (runtimes: {m.compatible_runtimes})")

asyncio.run(main())

import asyncio
import json
import logging
import sys

# Suppress noisy logs
logging.basicConfig(level=logging.INFO)

async def main():
    try:
        from ai_karen_engine.core.services.service_registry import initialize_services, get_service_registry
        await initialize_services()
        registry = get_service_registry()
        report = registry.get_initialization_report()
        
        # Convert to string to avoid complex objects in json.dumps
        def sanitize(obj):
            if isinstance(obj, dict):
                return {k: sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [sanitize(v) for v in obj]
            if hasattr(obj, '__name__'):
                return obj.__name__
            return str(obj)

        print(json.dumps(sanitize(report), indent=2))
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

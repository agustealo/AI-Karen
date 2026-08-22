import asyncio
from ai_karen_engine.config.runtime_provider_manager import get_runtime_provider_manager
from ai_karen_engine.config.settings_manager import get_settings_manager

async def main():
    manager = get_runtime_provider_manager()
    print("Health:", manager.get_all_provider_health())
    settings = get_settings_manager()
    print("Active Provider:", settings.get_setting("provider"))
    print("Active Model:", settings.get_setting("model"))

if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
# mypy: ignore-errors
"""
Root entrypoint for Kari AI Assistant Server.
This is the new modular entry point that replaces main.py.
"""

import sys
import os
import logging
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Add src early so composition-root imports resolve deterministically.
src_path = os.path.join(os.path.dirname(__file__), "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Import the modular server components
from server.app import create_app
from server.run import run_server, parse_args, configure_logging
from server.config import Settings

# Initialize PerformanceAdaptiveRouter
logger = logging.getLogger(__name__)

try:
    # Try to import and initialize PerformanceAdaptiveRouter
    import importlib.util

    # Try to locate the module
    spec = importlib.util.spec_from_file_location(
        "performance_router_init",
        os.path.join(src_path, "ai_karen_engine/integrations/performance_router_init.py"),
    )

    if spec is not None and spec.loader is not None:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        initialize_performance_router_sync = getattr(
            module,
            "initialize_performance_router_sync",
            None,
        )

        if initialize_performance_router_sync is not None:
            initialize_performance_router_sync()
            logger.info("PerformanceAdaptiveRouter initialized during system startup")
        else:
            logger.warning("initialize_performance_router_sync function not found in module")
    else:
        logger.warning("Could not locate PerformanceAdaptiveRouter module")

except Exception as e:
    logger.warning("Failed to initialize PerformanceAdaptiveRouter: %s", e)

logger = logging.getLogger("kari")


def main():
    """Main entry point for the Kari server."""
    try:
        # Application composition happens here, outside the Core AI machine.
        # Core selects providers; integrations only supply concrete constructors.
        from ai_karen_engine.integrations.provider_execution_bridge import (
            register_provider_execution_bridge,
        )

        register_provider_execution_bridge()

        # Load settings first to ensure environment validation happens early
        settings = Settings()

        # Configure logging according to settings/environment
        configure_logging(settings.log_level)

        # Parse command line arguments with settings-aware defaults
        args = parse_args(settings=settings)

        # Create the FastAPI app using the factory to fail fast on startup issues
        app = create_app()

        # Run the server
        run_server(args=args, settings=settings)

    except KeyboardInterrupt:
        logger.info("Server shutdown requested by user")
        sys.exit(0)
    except ValueError as e:
        logger.error("Invalid startup configuration: %s", e)
        sys.exit(2)
    except Exception as e:
        logger.exception("Failed to start server: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()

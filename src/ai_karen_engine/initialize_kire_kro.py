"""
KIRE-KRO Production Initialization - RETIRED

This script is retired. The canonical initialization path is through
ChatRuntime, ReasoningExecutor, WorkflowRuntime, and Medusa directly.

Previous behavior:
- KIRE routing initialization
- KRO orchestrator initialization
- Model discovery initialization
- CUDA acceleration initialization
- Content optimization initialization

All of these now have canonical owners.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)


async def initialize_production_system(
    enable_cuda: bool = True,
    enable_optimization: bool = True,
    enable_model_discovery: bool = True,
    verbose: bool = True,
) -> bool:
    """Retired initializer. Raises to prevent silent fallback."""
    raise RuntimeError(
        "initialize_production_system is retired. "
        "Use canonical runtime initialization: "
        "ChatRuntime, ReasoningExecutor, WorkflowRuntime, Medusa."
    )


async def test_system() -> bool:
    """Retired test function."""
    raise RuntimeError("test_system is retired.")


def main() -> None:
    """Retired CLI entry point."""
    raise RuntimeError(
        "initialize_kire_kro main is retired. "
        "Use canonical runtime initialization."
    )


if __name__ == "__main__":
    main()

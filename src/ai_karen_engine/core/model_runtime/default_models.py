import logging
import os
from pathlib import Path

from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager

embedding_manager: EmbeddingManager | None = None

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)

async def load_default_models() -> None:
    """Initialize default models if they haven't been loaded."""
    global embedding_manager

    eco_mode = os.getenv("KARI_ECO_MODE", "false").lower() in {"1", "true", "yes"}

    if embedding_manager is None:
        embedding_manager = EmbeddingManager()
        if not eco_mode:
            await embedding_manager.initialize()
        logger.info(
            "Default embedding model loaded: %s",
            embedding_manager.model_loaded,
        )


def get_embedding_manager() -> EmbeddingManager:
    if embedding_manager is None:
        raise RuntimeError("Default models not loaded")
    return embedding_manager

"""Platform composition for durable personalization."""

from ai_karen_engine.core.personalization.runtime import UserModelRuntime

from .repository import PostgresPersonalizationRepository


def build_user_model_runtime() -> UserModelRuntime:
    """Build the canonical durable personalization runtime."""

    return UserModelRuntime(repository=PostgresPersonalizationRepository())


__all__ = ["PostgresPersonalizationRepository", "build_user_model_runtime"]

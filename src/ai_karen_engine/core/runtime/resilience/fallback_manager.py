"""
Fallback Manager for AI Karen Resilience Layer.

Provides structured fallbacks when a stage fails or trips the circuit breaker.
Emits observability events for fallback activations.
Separates fallback semantics from retry semantics:
- Fallback: switching to an alternative stage/model/provider on failure
- Retry: retrying the same stage/model/provider (handled by SafeStageRunner)
"""

from typing import Dict, Any, Callable, Optional
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.logging.events import ProviderEvents

logger = get_logger(__name__)


def _emit_fallback_event(stage_name: str, fallback_type: str, reason: Optional[str] = None):
    """Emit a fallback observability event using structured logging."""
    logger.event(
        ProviderEvents.FALLBACK,
        stage_name=stage_name,
        fallback_type=fallback_type,
        reason=reason
    )


class FallbackManager:
    """Manages fallback strategies for optional stages.

    Fallback semantics: when a stage fails or is unavailable, execute
    an alternative strategy. This is separate from retry semantics,
    which re-attempt the same stage.
    """

    def __init__(self):
        self._fallbacks: Dict[str, Callable] = {}
        self._initialize_default_fallbacks()

    def _initialize_default_fallbacks(self):
        self.register_fallback("spacy", self._spacy_fallback)
        self.register_fallback("distilbert", self._distilbert_fallback)
        self.register_fallback("milvus_retrieval", self._empty_list_fallback)
        self.register_fallback("elasticsearch", self._empty_list_fallback)
        self.register_fallback("leangraph_projection", self._boolean_false_fallback)
        self.register_fallback("profile_synthesis", self._empty_dict_fallback)
        self.register_fallback("echocore_batch", self._boolean_false_fallback)

    def register_fallback(self, stage_name: str, fallback_func: Callable):
        self._fallbacks[stage_name] = fallback_func

    def get_fallback(self, stage_name: str, *args, **kwargs) -> Any:
        if stage_name in self._fallbacks:
            logger.info(f"Executing fallback strategy for stage: {stage_name}")
            _emit_fallback_event(stage_name, "stage_fallback")
            return self._fallbacks[stage_name](*args, **kwargs)

        logger.warning(f"No specific fallback registered for stage: {stage_name}. Returning None.")
        _emit_fallback_event(stage_name, "no_fallback_registered")
        return None

    # Default fallback strategies
    def _spacy_fallback(self, *args, **kwargs) -> Dict[str, Any]:
        """Fallback rule-based extraction when spaCy fails."""
        # Simple heuristic fallback or empty signals
        return {"entities": [], "keywords": [], "status": "degraded"}

    def _distilbert_fallback(self, *args, **kwargs) -> float:
        """Heuristic scoring fallback when DistilBERT fails."""
        # Return a neutral heuristic score
        return 0.5

    def _empty_list_fallback(self, *args, **kwargs) -> list:
        return []

    def _empty_dict_fallback(self, *args, **kwargs) -> dict:
        return {}

    def _boolean_false_fallback(self, *args, **kwargs) -> bool:
        return False


fallback_manager = FallbackManager()


def get_fallback_manager() -> FallbackManager:
    return fallback_manager

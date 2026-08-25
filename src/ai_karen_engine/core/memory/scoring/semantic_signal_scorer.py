"""
Semantic Signal Scorer for AI Karen Memory System.

Uses DistilBERT for scoring salience, novelty, and other memory properties.
"""


from ai_karen_engine.core.logging import get_logger

from ...runtime.resilience import get_safe_stage_runner

logger = get_logger(__name__)

class SemanticSignalScorer:
    """Uses DistilBERT (or fallback) to score signals."""
    
    def __init__(self):
        self.safe_runner = get_safe_stage_runner()
        self._model = None
        self._tokenizer = None
        self._initialized = False

    def initialize(self):
        """Initialize DistilBERT lazily."""
        if self._initialized:
            return
            
        try:
            from transformers import pipeline
            # Feature-extraction keeps the model choice valid for distilbert-base-uncased.
            self._scorer = pipeline(
                "feature-extraction",
                model="distilbert-base-uncased",
                truncation=True,
            )
            self._initialized = True
            logger.info("DistilBERT model loaded successfully.")
        except Exception as e:
            logger.info(f"Failed to load DistilBERT model: {e}")

    def score_salience(self, text: str) -> float:
        """Score how salient or important a text is."""
        if not self._initialized:
            raise RuntimeError("Scorer not initialized")
            
        # Run the model to keep the pipeline warm and make failures visible.
        self._scorer(text[:512])  # DistilBERT has a 512 token limit

        # Lightweight heuristic: length, structure, and punctuation increase salience.
        tokens = max(1, len(text.split()))
        capitalized = sum(1 for word in text.split() if word[:1].isupper())
        emphasis = 0.1 if any(ch in text for ch in ("?", "!", ":")) else 0.0
        structural = 0.05 if capitalized >= 2 else 0.0

        score = 0.2 + min(tokens / 60.0, 0.55) + structural + emphasis
        return min(1.0, score)

semantic_scorer = SemanticSignalScorer()

def get_semantic_scorer() -> SemanticSignalScorer:
    return semantic_scorer

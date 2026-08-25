"""
Memory Worthiness Scorer for AI Karen.

Determines if a signal should be admitted to durable memory.
"""

from typing import Any

from ai_karen_engine.core.logging import get_logger

from ...runtime.resilience import get_safe_stage_runner
from .semantic_signal_scorer import get_semantic_scorer

logger = get_logger(__name__)

class MemoryWorthinessScorer:
    """Evaluates if a signal meets the threshold for durable storage."""
    
    def __init__(self):
        self.scorer = get_semantic_scorer()
        self.safe_runner = get_safe_stage_runner()
        
        try:
            self.scorer.initialize()
        except Exception:
            pass

    async def evaluate(self, text: str, signal_type: str) -> dict[str, Any]:
        """Evaluate memory worthiness."""
        
        def distilbert_wrapper(t: str):
            return self.scorer.score_salience(t)
            
        salience_score = await self.safe_runner.run_stage(
            stage_name="distilbert",
            flag_name="distilbert_enabled",
            func=distilbert_wrapper,
            t=text
        )
        
        # Adjust threshold based on signal type
        base_threshold = 0.6
        if signal_type in ["preference", "directive"]:
            base_threshold = 0.4 # More likely to keep explicit preferences
            
        is_worthy = salience_score >= base_threshold
        
        return {
            "is_worthy": is_worthy,
            "score": salience_score,
            "threshold": base_threshold,
            "reason": "Meets salience threshold" if is_worthy else "Below salience threshold"
        }

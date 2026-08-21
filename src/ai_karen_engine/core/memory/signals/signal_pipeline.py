"""
Signal Pipeline for AI Karen Memory System.

Coordinates extraction through the Safe Stage Runner.
"""

import time
import logging
from typing import Optional

from .signal_models import ExtractionResult
from .extraction_service import SpacyExtractionService
from .signal_rules import RuleBasedExtractor
from ...runtime.resilience import get_safe_stage_runner

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)

class SignalPipeline:
    """Manages the memory signal extraction process with resilience."""
    
    def __init__(self):
        self.safe_runner = get_safe_stage_runner()
        self.spacy_service = SpacyExtractionService()
        self.rule_extractor = RuleBasedExtractor()
        
        # Attempt to initialize spaCy
        try:
            self.spacy_service.initialize()
        except Exception as e:
            logger.info(f"Could not initialize spaCy, pipeline will degrade to rule-based fallback. Error: {e}")
            
    async def process_text(
        self, 
        text: str,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> ExtractionResult:
        """Process text through the resilient extraction pipeline."""
        start_time = time.time()
        result = ExtractionResult()
        
        try:
            # Run the primary spaCy extraction via Safe Stage Runner
            # The runner handles timeouts, breakers, and fallbacks
            def spacy_wrapper(t: str):
                return self.spacy_service.extract(t)

            extracted_data = await self.safe_runner.run_stage(
                stage_name="spacy",
                flag_name="spacy_enabled",
                func=spacy_wrapper,
                t=text,
                tenant_id=tenant_id,
                user_id=user_id
            )
            
            # Check if we got a degraded fallback result (dict) or the actual List[MemorySignal]
            if isinstance(extracted_data, dict) and "status" in extracted_data and extracted_data["status"] == "degraded":
                logger.info("Applying rule-based fallback extraction.")
                result.signals = self.rule_extractor.extract(text)
                result.status = "degraded"
            elif isinstance(extracted_data, list):
                result.signals = extracted_data
                result.status = "success"
            else:
                 result.status = "degraded"
                 result.errors.append("Unknown extraction output format")
                 
        except Exception as e:
            logger.error(f"Pipeline processing failed: {e}")
            result.status = "failed"
            result.errors.append(str(e))
            
        result.processing_time_ms = (time.time() - start_time) * 1000
        return result

# Singleton instance
signal_pipeline = SignalPipeline()

def get_signal_pipeline() -> SignalPipeline:
    return signal_pipeline

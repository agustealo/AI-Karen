"""
Extraction Service for AI Karen Memory System.

Uses spaCy for structured signal extraction: entities, preferences, workflows.
"""

import logging
from typing import List

from .signal_models import MemorySignal

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)

class SpacyExtractionService:
    """spaCy-based memory signal extractor."""
    
    def __init__(self):
        self._nlp = None
        self._initialized = False
        
    def initialize(self):
        """Initialize spaCy model lazily."""
        if self._initialized:
            return
            
        try:
            import spacy
            # Load small English model. In production, consider en_core_web_md or trf.
            self._nlp = spacy.load("en_core_web_sm")
            self._initialized = True
            logger.info("spaCy NLP model loaded successfully.")
        except Exception as e:
            logger.info(f"Failed to load spaCy model: {e}")
            raise

    def extract(self, text: str) -> List[MemorySignal]:
        """Extract signals using spaCy."""
        if not self._initialized or not self._nlp:
            raise RuntimeError("spaCy model not initialized")
            
        doc = self._nlp(text)
        signals = []
        
        # 1. Entity Extraction
        entities = [{"text": ent.text, "label": ent.label_} for ent in doc.ents]
        if entities:
             signals.append(
                 MemorySignal(
                     text=text,
                     signal_type="entity",
                     confidence=0.8,
                     entities=entities,
                     scope="user",
                     metadata={"source": "spacy_ner"}
                 )
             )
             
        # 2. Preference and Workflow Cues (Dependency Parsing)
        # Look for SUBJECT-VERB-OBJECT structures indicating preferences or directives
        for token in doc:
            if token.pos_ == "VERB" and token.lemma_ in ["prefer", "like", "want", "need", "require", "always", "never"]:
                # Simple extraction of the subtree around the verb
                clause = "".join([t.text_with_ws for t in token.subtree]).strip()
                signals.append(
                     MemorySignal(
                         text=clause,
                         signal_type="preference",
                         confidence=0.75,
                         scope="user",
                         metadata={"source": "spacy_dep"}
                     )
                 )
                
        return signals

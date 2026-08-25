"""
Signal Rules for AI Karen Memory System.

Heuristic and pattern-based fallback extraction rules when spaCy is unavailable.
"""

import re

from .signal_models import MemorySignal


class RuleBasedExtractor:
    """Extracts memory signals using regular expressions and heuristics."""
    
    def __init__(self):
        self.preference_patterns = [
            re.compile(r"(?i)(i (like|prefer|love|hate|dislike) .+)"),
            re.compile(r"(?i)(always (use|do) .+)"),
            re.compile(r"(?i)(never (use|do) .+)")
        ]
        
    def extract(self, text: str) -> list[MemorySignal]:
        """Apply fallback rules to extract signals."""
        signals = []
        
        # Simple preference extraction
        for pattern in self.preference_patterns:
            match = pattern.search(text)
            if match:
                signals.append(
                    MemorySignal(
                        text=match.group(1),
                        signal_type="preference",
                        confidence=0.6, # Lower confidence for rule-based
                        scope="user",
                        metadata={"source": "rule_based"}
                    )
                )
                
        # Basic entity extraction via capitalization heuristics (very naive fallback)
        words = text.split()
        entities = []
        for word in words:
            if word.istitle() and len(word) > 2:
                # Exclude start of sentence if possible, but keep simple for fallback
                entities.append({"text": word, "label": "PROPN"})
                
        if entities:
             signals.append(
                 MemorySignal(
                     text=text,
                     signal_type="entity",
                     confidence=0.4,
                     entities=entities,
                     scope="user",
                     metadata={"source": "rule_based_entity"}
                 )
             )
             
        return signals

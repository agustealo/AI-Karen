"""Compatibility surface for historical adaptive evaluation imports.

Canonical evaluation datasets, contracts, metrics, and runners live under
``ai_karen_engine.core.intelligence.ml.evaluation``. New code must import that
package directly.
"""

from __future__ import annotations

from ai_karen_engine.core.adaptive.evaluation.corpus import EvaluationCorpus

__all__ = ["EvaluationCorpus"]

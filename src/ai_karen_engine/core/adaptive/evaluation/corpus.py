"""Compatibility view over the canonical Intelligence/ML evaluation corpus.

The historical adaptive corpus encoded execution-policy actions such as
``use_tool`` and ``use_multi_agent`` directly in evaluation fixtures. Those
labels duplicated CORTEX/RuntimePolicy authority and made evaluation data act
like a second router.

Canonical evaluation ownership now lives in
``ai_karen_engine.core.intelligence.ml.evaluation``. This module preserves the
legacy ``EvaluationCorpus`` import path while exposing neutral prediction-task
cases only.
"""

from __future__ import annotations

from typing import Any

from ai_karen_engine.core.intelligence.ml.evaluation import CanonicalEvaluationCorpus
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import EvaluationCase


def _legacy_view(case: EvaluationCase) -> dict[str, Any]:
    """Return a stable dictionary view without reintroducing routing labels."""

    return {
        "name": case.case_id,
        "case_id": case.case_id,
        "task": case.task.value,
        "input_text": case.input_text,
        "expected_label": case.expected_label,
        "expected_value": case.expected_value,
        "tags": list(case.tags),
        "difficulty": case.difficulty,
        "source": case.source,
        "dataset_version": case.dataset_version,
        "features": dict(case.features),
    }


class EvaluationCorpus:
    """Legacy facade over :class:`CanonicalEvaluationCorpus`.

    The class intentionally does not expose ``expected_top_actions`` or any
    execution-topology decision. Consumers needing typed cases should migrate
    to ``CanonicalEvaluationCorpus`` directly.
    """

    def list_cases(self) -> list[dict[str, Any]]:
        return [_legacy_view(case) for case in CanonicalEvaluationCorpus.all_cases()]

    def get_case(self, name: str) -> dict[str, Any] | None:
        for case in CanonicalEvaluationCorpus.all_cases():
            if case.case_id == name:
                return _legacy_view(case)
        return None


__all__ = ["EvaluationCorpus"]

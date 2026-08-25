from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.adaptive.salience.contracts import (
    SalienceAssessment,
    SalienceDimension,
)


@dataclass(slots=True)
class SalienceAggregationResult:
    """Aggregated salience across multiple signals."""
    primary_dimension: str = ""
    peak_value: float = 0.0
    mean_value: float = 0.0
    variance: float = 0.0
    dominant_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SalienceAggregator:
    """Aggregates multiple salience assessments into a coherent view."""

    def aggregate(self, assessments: list[SalienceAssessment]) -> SalienceAggregationResult:
        if not assessments:
            return SalienceAggregationResult()

        dims: dict[SalienceDimension, list[float]] = {dim: [] for dim in SalienceDimension}
        for a in assessments:
            for dim in SalienceDimension:
                val = getattr(a, dim.value, 0.0)
                dims[dim].append(val)

        primary_dimension = max(dims, key=lambda d: sum(dims[d]) / len(dims[d]) if dims[d] else 0.0)
        values = [sum(v) / len(v) if v else 0.0 for v in dims.values()]
        peak = max(values)
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)

        reason_counts: dict[str, int] = {}
        for a in assessments:
            for rc in a.reason_codes:
                reason_counts[rc.value] = reason_counts.get(rc.value, 0) + 1

        dominant = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:3]

        return SalienceAggregationResult(
            primary_dimension=primary_dimension.value,
            peak_value=peak,
            mean_value=mean,
            variance=variance,
            dominant_reasons=[r for r, _ in dominant],
        )

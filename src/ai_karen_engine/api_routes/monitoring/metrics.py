from __future__ import annotations

import math
import os
from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import APIKeyHeader

from ai_karen_engine.platform.observability.metrics import get_metrics_collector


PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
_api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)
router = APIRouter(tags=["monitoring"])


def _escape_help(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n")


def _escape_label(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def _labels(label_names: Iterable[str], label_values: tuple[str, ...]) -> str:
    pairs = [
        f'{name}="{_escape_label(value)}"'
        for name, value in zip(label_names, label_values, strict=True)
    ]
    return "{" + ",".join(pairs) + "}" if pairs else ""


def _labels_with_extra(
    label_names: Iterable[str],
    label_values: tuple[str, ...],
    extra_name: str,
    extra_value: str,
) -> str:
    pairs = [
        f'{name}="{_escape_label(value)}"'
        for name, value in zip(label_names, label_values, strict=True)
    ]
    pairs.append(f'{extra_name}="{_escape_label(extra_value)}"')
    return "{" + ",".join(pairs) + "}"


def _format_number(value: float | int) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "+Inf" if value > 0 else "-Inf"
    return format(value, ".17g") if isinstance(value, float) else str(value)


def render_prometheus_text() -> str:
    """Render the canonical in-process collector using Prometheus text format."""

    snapshot = get_metrics_collector().snapshot()
    lines: list[str] = []

    for metric_name, metric in sorted(snapshot["counters"].items()):
        lines.append(f"# HELP {metric_name} {_escape_help(metric['description'])}")
        lines.append(f"# TYPE {metric_name} counter")
        for label_values, value in sorted(metric["values"].items()):
            labels = _labels(metric["label_names"], label_values)
            lines.append(f"{metric_name}{labels} {_format_number(value)}")

    for metric_name, metric in sorted(snapshot["gauges"].items()):
        lines.append(f"# HELP {metric_name} {_escape_help(metric['description'])}")
        lines.append(f"# TYPE {metric_name} gauge")
        for label_values, value in sorted(metric["values"].items()):
            labels = _labels(metric["label_names"], label_values)
            lines.append(f"{metric_name}{labels} {_format_number(value)}")

    for metric_name, metric in sorted(snapshot["histograms"].items()):
        lines.append(f"# HELP {metric_name} {_escape_help(metric['description'])}")
        lines.append(f"# TYPE {metric_name} histogram")
        label_names = metric["label_names"]
        buckets = tuple(float(bucket) for bucket in metric["buckets"])
        for label_values, observations in sorted(metric["values"].items()):
            ordered = [float(value) for value in observations]
            for bucket in buckets:
                count = sum(1 for value in ordered if value <= bucket)
                labels = _labels_with_extra(
                    label_names,
                    label_values,
                    "le",
                    _format_number(bucket),
                )
                lines.append(f"{metric_name}_bucket{labels} {count}")
            inf_labels = _labels_with_extra(label_names, label_values, "le", "+Inf")
            lines.append(f"{metric_name}_bucket{inf_labels} {len(ordered)}")
            labels = _labels(label_names, label_values)
            lines.append(f"{metric_name}_sum{labels} {_format_number(sum(ordered))}")
            lines.append(f"{metric_name}_count{labels} {len(ordered)}")

    return "\n".join(lines) + "\n"


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(
    request: Request,
    api_key: str | None = Depends(_api_key_header),
) -> Response:
    """Expose canonical metrics while preserving the existing scrape policy."""

    public_metrics = os.getenv("KARI_PUBLIC_METRICS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    settings: Any = getattr(request.app.state, "settings", None)
    expected_api_key = getattr(settings, "secret_key", None)

    if not public_metrics and (not expected_api_key or api_key != expected_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return Response(content=render_prometheus_text(), media_type=PROMETHEUS_CONTENT_TYPE)


__all__ = ["PROMETHEUS_CONTENT_TYPE", "render_prometheus_text", "router"]

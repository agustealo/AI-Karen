from __future__ import annotations

from typing import Any, Dict, Iterable


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _pct(part: int, total: int) -> float:
    return round((part / total) * 100.0, 1) if total > 0 else 0.0


def build_prompt_token_insight(
    prompt_telemetry: Dict[str, Any] | None,
    provider_usage: Dict[str, Any] | None,
) -> Dict[str, Any]:
    prompt = dict(prompt_telemetry or {})
    usage = dict(provider_usage or {})
    breakdown = dict(prompt.get("breakdown") or {})
    context = dict(prompt.get("context_policy") or {})

    estimated_input = _safe_int(prompt.get("estimated_input_tokens"))
    if estimated_input is None:
        estimated_input = _safe_int(context.get("final_tokens"))

    provider_input = _safe_int(usage.get("prompt_tokens"))
    provider_output = _safe_int(usage.get("completion_tokens"))
    provider_total = _safe_int(usage.get("total_tokens"))
    prompt_budget = _safe_int(prompt.get("token_budget"))
    if prompt_budget is None:
        prompt_budget = _safe_int(context.get("token_budget"))

    model_context_window = _safe_int(prompt.get("model_context_window_tokens"))
    model_context_source = str(prompt.get("model_context_source") or "").strip() or None

    input_tokens = provider_input if provider_input is not None else estimated_input
    output_tokens = provider_output
    consumed = provider_total
    if consumed is None and input_tokens is not None:
        consumed = input_tokens + (output_tokens or 0)

    prompt_budget_headroom = None
    if prompt_budget is not None and input_tokens is not None:
        prompt_budget_headroom = max(0, prompt_budget - input_tokens)

    model_context_headroom = None
    if model_context_window is not None and consumed is not None:
        model_context_headroom = max(0, model_context_window - consumed)

    source = "provider_reported" if provider_input is not None else "prompt_estimate"
    available = input_tokens is not None and prompt_budget is not None

    total_breakdown = sum(
        max(0, _safe_int(breakdown.get(key)) or 0)
        for key in ("system", "memory", "tools", "messages", "overhead")
    )
    decomposition = {
        key: {
            "tokens": max(0, _safe_int(breakdown.get(key)) or 0),
            "percent": _pct(max(0, _safe_int(breakdown.get(key)) or 0), total_breakdown),
        }
        for key in ("system", "memory", "tools", "messages", "overhead")
    }

    return {
        "available": available,
        "source": source if available else "unavailable",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": consumed,
        "prompt_budget_tokens": prompt_budget,
        "prompt_budget_headroom_tokens": prompt_budget_headroom,
        "prompt_budget_used_percent": (
            round((input_tokens / prompt_budget) * 100.0, 1)
            if available and prompt_budget
            else None
        ),
        "model_context_available": (
            model_context_window is not None and consumed is not None
        ),
        "model_context_window_tokens": model_context_window,
        "model_context_headroom_tokens": model_context_headroom,
        "model_context_used_percent": (
            round((consumed / model_context_window) * 100.0, 1)
            if model_context_window and consumed is not None
            else None
        ),
        "model_context_source": model_context_source or "unavailable",
        "truncation_count": _safe_int(context.get("truncation_count")) or 0,
        "decomposition": decomposition,
    }


def build_execution_waterfall(
    spans: Iterable[Dict[str, Any]] | None,
    total_latency_ms: float | None,
) -> Dict[str, Any]:
    normalized = []
    for span in spans or []:
        duration = _safe_float(span.get("duration_ms"))
        name = str(span.get("name") or "").strip()
        if not name or duration is None or duration < 0:
            continue
        normalized.append(
            {
                "name": name,
                "duration_ms": round(duration, 2),
                "source": str(span.get("source") or "runtime_observed"),
            }
        )
    return {
        "available": bool(normalized),
        "total_latency_ms": round(float(total_latency_ms), 2)
        if total_latency_ms is not None
        else None,
        "spans": normalized,
        "unavailable_reason": None if normalized else "no_observed_spans_reported",
    }


def build_optional_insight(
    payload: Any,
    *,
    unavailable_reason: str,
) -> Dict[str, Any]:
    if isinstance(payload, dict) and payload:
        result = dict(payload)
        result.setdefault("available", True)
        return result
    return {
        "available": False,
        "unavailable_reason": unavailable_reason,
    }


def build_consumer_insights(
    *,
    prompt_telemetry: Dict[str, Any] | None = None,
    provider_usage: Dict[str, Any] | None = None,
    execution_spans: Iterable[Dict[str, Any]] | None = None,
    total_latency_ms: float | None = None,
    vector_health: Dict[str, Any] | None = None,
    counterfactuals: Dict[str, Any] | None = None,
    agent_consensus: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    token = build_prompt_token_insight(prompt_telemetry, provider_usage)
    return {
        "token_window": token,
        "prompt_decomposition": {
            "available": token["available"],
            "source": token["source"],
            "sections": token["decomposition"],
            "estimated_input_tokens": token["input_tokens"],
        },
        "vector_health": build_optional_insight(
            vector_health,
            unavailable_reason="vector_backend_health_not_reported_for_turn",
        ),
        "counterfactuals": build_optional_insight(
            counterfactuals,
            unavailable_reason="no_counterfactual_scenarios_evaluated",
        ),
        "agent_consensus": build_optional_insight(
            agent_consensus,
            unavailable_reason="no_multi_agent_consensus_reported",
        ),
        "execution_waterfall": build_execution_waterfall(
            execution_spans,
            total_latency_ms,
        ),
    }

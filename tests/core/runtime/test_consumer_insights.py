from __future__ import annotations

from ai_karen_engine.core.runtime.consumer_insights import (
    build_consumer_insights,
    build_prompt_token_insight,
)


def test_prompt_token_insight_prefers_provider_usage_over_estimate() -> None:
    insight = build_prompt_token_insight(
        {
            "estimated_input_tokens": 1000,
            "token_budget": 4096,
            "breakdown": {
                "system": 200,
                "memory": 100,
                "tools": 100,
                "messages": 500,
                "overhead": 100,
            },
            "context_policy": {"truncation_count": 1},
        },
        {
            "prompt_tokens": 1200,
            "completion_tokens": 300,
            "total_tokens": 1500,
        },
    )

    assert insight["available"] is True
    assert insight["source"] == "provider_reported"
    assert insight["input_tokens"] == 1200
    assert insight["output_tokens"] == 300
    assert insight["total_tokens"] == 1500
    assert insight["context_headroom_tokens"] == 2896
    assert insight["truncation_count"] == 1
    assert insight["decomposition"]["messages"]["percent"] == 50.0


def test_prompt_token_insight_labels_estimates_truthfully() -> None:
    insight = build_prompt_token_insight(
        {
            "estimated_input_tokens": 512,
            "token_budget": 2048,
            "breakdown": {"messages": 412, "overhead": 100},
        },
        None,
    )

    assert insight["available"] is True
    assert insight["source"] == "prompt_estimate"
    assert insight["input_tokens"] == 512
    assert insight["output_tokens"] is None
    assert insight["context_headroom_tokens"] == 1536


def test_optional_advanced_insights_fail_closed_when_not_reported() -> None:
    insights = build_consumer_insights(total_latency_ms=42.0)

    assert insights["vector_health"] == {
        "available": False,
        "unavailable_reason": "vector_backend_health_not_reported_for_turn",
    }
    assert insights["counterfactuals"]["available"] is False
    assert insights["agent_consensus"]["available"] is False
    assert insights["execution_waterfall"]["available"] is False


def test_execution_waterfall_only_accepts_observed_nonnegative_spans() -> None:
    insights = build_consumer_insights(
        execution_spans=[
            {"name": "prompt_assembly", "duration_ms": 5.25},
            {"name": "provider_generation", "duration_ms": 21.5, "source": "expression_gateway"},
            {"name": "bad", "duration_ms": -3},
        ],
        total_latency_ms=30.0,
    )

    waterfall = insights["execution_waterfall"]
    assert waterfall["available"] is True
    assert waterfall["total_latency_ms"] == 30.0
    assert waterfall["spans"] == [
        {"name": "prompt_assembly", "duration_ms": 5.25, "source": "runtime_observed"},
        {"name": "provider_generation", "duration_ms": 21.5, "source": "expression_gateway"},
    ]

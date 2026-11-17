"""CORTEX must preserve established capability routing before plugin fallback."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.cortex.routing_intents import (
    parse_plugin_inspection_request,
    resolve_capability_decision,
)


@pytest.mark.parametrize(
    ("query", "expected_intent", "expected_capability"),
    (
        ("Set up a daily task to stretch", "automation.create", "automation.create"),
        (
            "Set up a task to stretch every day",
            "automation.create", "automation.create",
        ),
        (
            "Please schedule a recurring automation to check the news daily",
            "automation.create", "automation.create",
        ),
        ("Start a 10 minute timer", "timer.manage", "timer.schedule"),
        ("What time is it?", "time.current", "time_query"),
        ("What's the weather in Detroit?", "search.weather", "web.search"),
    ),
)
def test_registered_capability_patterns_outrank_broad_plugin_setup(
    query: str, expected_intent: str, expected_capability: str,
) -> None:
    decision = resolve_capability_decision(query)
    assert decision.intent == expected_intent
    assert decision.capability == expected_capability
    assert decision.requires_live_data
    assert not decision.allow_llm_only


@pytest.mark.parametrize(
    ("query", "expected_target"),
    (
        ("Set up my Telegram", "Telegram"),
        ("Configure my Time Query plugin", "Time Query"),
        ("Is my Telegram connected?", "Telegram"),
        ("Use my Time Query plugin to tell me the time", "Time Query"),
    ),
)
def test_explicit_plugin_request_still_routes_after_registered_specializations(
    query: str, expected_target: str,
) -> None:
    parsed = parse_plugin_inspection_request(query)
    assert parsed is not None
    assert parsed.target == expected_target
    decision = resolve_capability_decision(query)
    assert decision.intent == "plugin.inspect"
    assert decision.capability == "plugin.inspect"
    assert decision.requires_live_data is True
    assert decision.allow_llm_only is False
    assert decision.preferred_plugin is None
    assert decision.handler is None


@pytest.mark.parametrize(
    ("query", "operation"),
    (
        ("Which installed plugins can I use to search the web?", "discover"),
        ("Use my Weather plugin to get weather in Detroit", "use"),
        ("Use my Time Query plugin to tell me the time", "use"),
        ("Enable my Pocket TTS plugin", "manage"),
        ("Configure my Time Query plugin", "setup"),
        ("List my plugins", "list"),
    ),
)
def test_explicit_plugin_intent_precedes_unanchored_specialist_match(
    query: str, operation: str,
) -> None:
    parsed = parse_plugin_inspection_request(query)
    assert parsed is not None
    assert parsed.operation == operation
    decision = resolve_capability_decision(query)
    assert decision.intent == "plugin.inspect"
    assert decision.subtype == operation
    assert decision.capability == "plugin.inspect"
    assert decision.requires_live_data is True
    assert decision.requires_tool is True
    assert decision.allow_llm_only is False
    assert decision.preferred_plugin is None


def test_plugin_use_keeps_declared_goal_for_governed_preflight() -> None:
    parsed = parse_plugin_inspection_request(
        "Use my Weather plugin to get weather in Detroit"
    )
    assert parsed is not None
    assert parsed.operation == "use"
    assert parsed.target == "Weather"
    assert parsed.requested_action == "execute"
    assert parsed.goal == "get weather in Detroit"


def test_existing_automation_route_is_not_downgraded_to_plugin_catalog_lookup() -> None:
    query = "Set up a daily task to stretch"
    assert parse_plugin_inspection_request(query) is not None
    decision = resolve_capability_decision(query)
    assert decision.intent == "automation.create"
    assert decision.capability != "plugin.inspect"

"""
Architecture proof tests for INTELLIGENCE-3: Semantic Consumption Closure.

Validates that CORTEX consumes IntelligenceRuntime signals directly instead of
reconstructing decisions from hardcoded intent maps.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from ai_karen_engine.core.intelligence.contracts import (
    IntelligenceAnalysisResult,
)
from ai_karen_engine.core.runtime.cortex_execution_decider import CortexExecutionDecider
from ai_karen_engine.core.runtime.execution_decision import RiskLevel


class _StubIntelligenceRuntime:
    """Stub intelligence runtime that returns controlled analysis results."""

    def __init__(self, analysis: IntelligenceAnalysisResult) -> None:
        self._analysis = analysis

    async def analyze(self, text: str, context: Dict[str, Any] | None = None) -> IntelligenceAnalysisResult:
        return self._analysis


def _make_decider(analysis: IntelligenceAnalysisResult) -> CortexExecutionDecider:
    decider = CortexExecutionDecider.__new__(CortexExecutionDecider)
    decider._force_graph = False
    decider._intelligence = _StubIntelligenceRuntime(analysis)
    return decider


def test_topology_signals_drive_tool_requirements() -> None:
    """CORTEX must derive tool_requirements from topology_signals, not hardcoded intents."""
    analysis = IntelligenceAnalysisResult(
        intent="general_assist",
        intent_confidence=0.9,
        topology_signals={
            "external_lookup": True,
            "code_execution": True,
            "filesystem_operation": False,
            "multiple_actions": False,
            "dependency_chain": False,
            "parallelizable": False,
            "requires_followup": False,
        },
        capability_hints={},
        memory_relevance=0.0,
        risk_signals={"categories": [], "score": 0.0},
    )

    decider = _make_decider(analysis)
    result = decider._analyze_request("run a search and execute the script", None)

    assert "search" in result["tool_requirements"]
    assert "code_execution" in result["tool_requirements"]
    assert "filesystem_operation" not in result["tool_requirements"]


def test_capability_hints_drive_required_capabilities() -> None:
    """CORTEX must derive required_capabilities from capability_hints, not hardcoded intents."""
    analysis = IntelligenceAnalysisResult(
        intent="general_assist",
        intent_confidence=0.9,
        topology_signals={},
        capability_hints={
            "web_search": True,
            "code_execution": False,
            "filesystem_read": True,
            "filesystem_write": False,
            "structured_output": True,
            "deep_reasoning": False,
        },
        memory_relevance=0.0,
        risk_signals={"categories": [], "score": 0.0},
    )

    decider = _make_decider(analysis)
    result = decider._analyze_request("read this file and show me a json table", None)

    assert "web" in result["required_capabilities"]
    assert "filesystem_read" in result["required_capabilities"]
    assert "structured_output" in result["required_capabilities"]
    assert "admin" not in result["required_capabilities"]


def test_memory_relevance_drives_recall_policy() -> None:
    """CORTEX must derive memory recall from memory_relevance, not hardcoded intent sets."""
    analysis = IntelligenceAnalysisResult(
        intent="general_assist",
        intent_confidence=0.9,
        topology_signals={},
        capability_hints={},
        memory_relevance=0.75,
        risk_signals={"categories": [], "score": 0.0},
    )

    decider = _make_decider(analysis)
    result = decider._analyze_request("remember what we discussed yesterday", None)

    assert result["memory_recall_required"] is True
    assert result["memory_scope"] == "user"
    assert result["memory_top_k"] == 15


def test_low_memory_relevance_does_not_force_recall() -> None:
    """Low memory_relevance must not trigger recall just because confidence is low."""
    analysis = IntelligenceAnalysisResult(
        intent="general_assist",
        intent_confidence=0.2,
        topology_signals={},
        capability_hints={},
        memory_relevance=0.0,
        risk_signals={"categories": [], "score": 0.0},
    )

    decider = _make_decider(analysis)
    result = decider._analyze_request("what color is copper?", None)

    assert result["memory_recall_required"] is False
    assert result["memory_scope"] == "session"


def test_risk_signals_drive_risk_level() -> None:
    """CORTEX must derive risk_level from risk_signals, not only tool/plugin counts."""
    analysis = IntelligenceAnalysisResult(
        intent="general_assist",
        intent_confidence=0.9,
        topology_signals={},
        capability_hints={},
        memory_relevance=0.0,
        risk_signals={
            "categories": ["destructive_action", "credential_access"],
            "score": 0.6,
        },
    )

    decider = _make_decider(analysis)
    result = decider._analyze_request("delete the admin password", None)

    assert result["risk_level"] in {RiskLevel.HIGH.value, RiskLevel.CRITICAL.value}
    assert "destructive_action" in result["risk_categories"]
    assert "credential_access" in result["risk_categories"]


def test_topology_drives_graph_requirement() -> None:
    """CORTEX must require graph execution when topology_signals indicate multi-step work."""
    analysis = IntelligenceAnalysisResult(
        intent="general_assist",
        intent_confidence=0.9,
        task_complexity="complex",
        topology_signals={
            "dependency_chain": True,
            "multiple_actions": True,
            "parallelizable": True,
            "requires_followup": False,
        },
        capability_hints={},
        memory_relevance=0.0,
        risk_signals={"categories": [], "score": 0.0},
    )

    decider = _make_decider(analysis)
    result = decider._analyze_request("build, test, and deploy the service", None)

    assert result["requires_resumability"] is True
    assert result["requires_parallel_execution"] is True
    assert result["reasoning_depth"] == "deep"


def test_intent_is_preserved_but_not_overused() -> None:
    """Intent should be preserved for observability, but not drive policy alone."""
    analysis = IntelligenceAnalysisResult(
        intent="unknown_rare_intent",
        intent_confidence=0.1,
        topology_signals={},
        capability_hints={},
        memory_relevance=0.0,
        risk_signals={"categories": [], "score": 0.0},
    )

    decider = _make_decider(analysis)
    result = decider._analyze_request("unknown rare intent query", None)

    assert result["intent"] == "unknown_rare_intent"
    assert result["requires_resumability"] is False
    assert result["tool_requirements"] == []

"""Offline evaluation corpus.

Synthetic test cases for adaptive policy evaluation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EvaluationCorpus:
    """Collection of synthetic evaluation cases."""

    def __init__(self) -> None:
        self._cases: list[dict[str, Any]] = []
        self._load_default_cases()

    def _load_default_cases(self) -> None:
        self._cases = [
            {
                "name": "simple_greeting",
                "expected_top_actions": ["respond_directly"],
                "task_complexity": "simple",
                "ambiguity": "clear",
                "risk": "low",
            },
            {
                "name": "memory_dependent_query",
                "expected_top_actions": ["retrieve_memory", "respond_directly"],
                "task_complexity": "simple",
                "ambiguity": "clear",
                "risk": "low",
            },
            {
                "name": "ambiguous_request",
                "expected_top_actions": ["ask_clarification", "respond_directly"],
                "task_complexity": "simple",
                "ambiguity": "ambiguous",
                "risk": "low",
            },
            {
                "name": "repo_audit",
                "expected_top_actions": ["use_tool", "use_workflow"],
                "task_complexity": "complex",
                "ambiguity": "clear",
                "risk": "low",
            },
            {
                "name": "calendar_lookup",
                "expected_top_actions": ["use_tool", "respond_directly"],
                "task_complexity": "moderate",
                "ambiguity": "clear",
                "risk": "low",
            },
            {
                "name": "multi_step_workflow",
                "expected_top_actions": ["use_workflow", "use_multi_agent"],
                "task_complexity": "complex",
                "ambiguity": "moderate",
                "risk": "medium",
            },
            {
                "name": "high_risk_mutation",
                "expected_top_actions": ["suggest_action", "ask_clarification"],
                "task_complexity": "moderate",
                "ambiguity": "clear",
                "risk": "critical",
            },
            {
                "name": "local_only_task",
                "expected_top_actions": ["respond_directly", "retrieve_memory"],
                "task_complexity": "simple",
                "ambiguity": "clear",
                "risk": "low",
            },
            {
                "name": "repeated_workflow_suggestion",
                "expected_top_actions": ["respond_directly", "suggest_action"],
                "task_complexity": "moderate",
                "ambiguity": "clear",
                "risk": "low",
            },
            {
                "name": "tool_outage",
                "expected_top_actions": ["respond_directly", "ask_clarification"],
                "task_complexity": "moderate",
                "ambiguity": "clear",
                "risk": "low",
            },
            {
                "name": "agent_unavailable",
                "expected_top_actions": ["use_tool", "use_workflow"],
                "task_complexity": "complex",
                "ambiguity": "moderate",
                "risk": "medium",
            },
        ]

    def list_cases(self) -> list[dict[str, Any]]:
        return list(self._cases)

    def get_case(self, name: str) -> dict[str, Any] | None:
        for case in self._cases:
            if case["name"] == name:
                return case
        return None

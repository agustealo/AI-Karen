"""Orchestration Node Exports.

Keep this package side-effect light. Individual node modules are imported
on-demand so the orchestration graph can assemble without bootstrapping every
node dependency at package import time.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    # Node classes
    "AuthGateNode",
    "SafetyGateNode",
    "MemoryFetchNode",
    "IntentDetectNode",
    "PlannerNode",
    "RouterSelectNode",
    "ReasoningNode",
    "ToolExecutionNode",
    "ResponseSynthesisNode",
    "MemoryWriteNode",
    # Convenience functions
    "auth_gate_node",
    "safety_gate_node",
    "memory_fetch_node",
    "intent_detect_node",
    "planner_node",
    "router_select_node",
    "reasoning_node",
    "select_reasoning_branch",
    "tool_exec_node",
    "response_synth_node",
    "memory_write_node",
    "stream_process_node",
    # Data classes
    "ToolExecutionConfig",
    "SynthesisConfig",
    "MemoryWriteRequest",
    "MemoryWriteResult",
]

_EXPORTS = {
    "AuthGateNode": ("ai_karen_engine.core.langgraph_orchestrator.nodes.auth_gate", "AuthGateNode"),
    "auth_gate_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.auth_gate", "auth_gate_node"),
    "SafetyGateNode": ("ai_karen_engine.core.langgraph_orchestrator.nodes.safety_gate", "SafetyGateNode"),
    "safety_gate_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.safety_gate", "safety_gate_node"),
    "MemoryFetchNode": ("ai_karen_engine.core.langgraph_orchestrator.nodes.memory_fetch", "MemoryFetchNode"),
    "memory_fetch_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.memory_fetch", "memory_fetch_node"),
    "IntentDetectNode": ("ai_karen_engine.core.langgraph_orchestrator.nodes.intent_detect", "IntentDetectNode"),
    "intent_detect_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.intent_detect", "intent_detect_node"),
    "PlannerNode": ("ai_karen_engine.core.langgraph_orchestrator.nodes.planner", "PlannerNode"),
    "planner_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.planner", "planner_node"),
    "RouterSelectNode": ("ai_karen_engine.core.langgraph_orchestrator.nodes.router_select", "RouterSelectNode"),
    "router_select_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.router_select", "router_select_node"),
    "ReasoningNode": ("ai_karen_engine.core.langgraph_orchestrator.nodes.reasoning", "ReasoningNode"),
    "reasoning_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.reasoning", "reasoning_node"),
    "select_reasoning_branch": ("ai_karen_engine.core.langgraph_orchestrator.nodes.reasoning", "select_reasoning_branch"),
    "ToolExecutionNode": ("ai_karen_engine.core.langgraph_orchestrator.nodes.tool_exec", "ToolExecutionNode"),
    "ToolExecutionConfig": ("ai_karen_engine.core.langgraph_orchestrator.nodes.tool_exec", "ToolExecutionConfig"),
    "tool_exec_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.tool_exec", "tool_exec_node"),
    "ResponseSynthesisNode": ("ai_karen_engine.core.langgraph_orchestrator.nodes.response_synth", "ResponseSynthesisNode"),
    "SynthesisConfig": ("ai_karen_engine.core.langgraph_orchestrator.nodes.response_synth", "SynthesisConfig"),
    "response_synth_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.response_synth", "response_synth_node"),
    "MemoryWriteNode": ("ai_karen_engine.core.langgraph_orchestrator.nodes.memory_write", "MemoryWriteNode"),
    "MemoryWriteRequest": ("ai_karen_engine.core.langgraph_orchestrator.nodes.memory_write", "MemoryWriteRequest"),
    "MemoryWriteResult": ("ai_karen_engine.core.langgraph_orchestrator.nodes.memory_write", "MemoryWriteResult"),
    "memory_write_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.memory_write", "memory_write_node"),
    "stream_process_node": ("ai_karen_engine.core.langgraph_orchestrator.nodes.stream_process", "stream_process_node"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attr_name)

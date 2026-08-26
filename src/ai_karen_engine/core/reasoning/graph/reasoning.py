from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Optional

from ai_karen_engine.core.reasoning.synthesis.ice_wrapper import (
    PremiumICEWrapper,
    ICEWritebackPolicy,
    ReasoningTrace,
)
from ai_karen_engine.core.reasoning.soft_reasoning.engine import (
    SoftReasoningEngine,
    RecallConfig,
    WritebackConfig,
)
from ai_karen_engine.core.reasoning.graph.capsule import CapsuleGraph
from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils
from ai_karen_engine.core.model_runtime.runtime_registry_adapter import get_registry

logger = logging.getLogger("ai_karen.reasoning.graph")


def _stable_node_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}::{digest}"


class ReasoningGraph:
    """ICE façade with optional CapsuleGraph mirroring for explainability."""

    def __init__(
        self,
        *,
        engine: Optional[SoftReasoningEngine] = None,
        llm: Optional[LLMUtils] = None,
        policy: Optional[ICEWritebackPolicy] = None,
        enable_graph_mirroring: bool = True,
    ) -> None:
        self.engine = engine or SoftReasoningEngine(
            ttl_seconds=3600,
            recall=RecallConfig(
                fast_top_k=24,
                final_top_k=5,
                recency_alpha=0.65,
                min_score=0.0,
                use_dual_embedding=True,
            ),
            writeback=WritebackConfig(
                novelty_gate=0.18,
                importance_gate=0.30,
                default_ttl_seconds=3600,
                long_ttl_seconds=86400,
                max_len_chars=5000,
            ),
        )
        self.llm = llm or (get_registry().get_active() or LLMUtils())  # type: ignore[attr-defined]
        self.policy = policy or ICEWritebackPolicy()
        self._ice = PremiumICEWrapper(sr=None, subengine=None, llm=self.llm, policy=self.policy)
        self._capsule_graph = CapsuleGraph() if enable_graph_mirroring else None

    def run(
        self,
        text: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        policy_overrides: Optional[Dict[str, Any]] = None,
    ) -> ReasoningTrace:
        trace = self._run_internal(text, metadata=metadata, policy_overrides=policy_overrides)
        self._mirror_to_graph(text, trace)
        return trace

    async def arun(
        self,
        text: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        policy_overrides: Optional[Dict[str, Any]] = None,
    ) -> ReasoningTrace:
        import asyncio

        trace = await asyncio.to_thread(self._run_internal, text, metadata, policy_overrides)
        self._mirror_to_graph(text, trace)
        return trace

    @property
    def capsule_graph(self) -> Optional[CapsuleGraph]:
        return self._capsule_graph

    def visualize_capsule_cli(self) -> Optional[str]:
        if not self._capsule_graph:
            return None
        return self._capsule_graph.visualize_cli()

    def capsule_dot(self) -> Optional[str]:
        if not self._capsule_graph:
            return None
        return self._capsule_graph.to_dot()

    def _run_internal(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]],
        policy_overrides: Optional[Dict[str, Any]],
    ) -> ReasoningTrace:
        if policy_overrides:
            policy = ICEWritebackPolicy(**{**self.policy.__dict__, **policy_overrides})
            wrapper = PremiumICEWrapper(sr=None, subengine=None, llm=self.llm, policy=policy)
            return wrapper.process(text, metadata=metadata)
        return self._ice.process(text, metadata=metadata)

    def _mirror_to_graph(self, text: str, trace: ReasoningTrace) -> None:
        if not self._capsule_graph:
            return

        query_node = _stable_node_id("query", text)
        self._capsule_graph.upsert_node(
            query_node,
            type="query",
            entropy=trace.entropy,
            top_score=trace.top_score,
        )
        for idx, match in enumerate(trace.memory_matches):
            payload = match.get("payload", {})
            memory_text = payload.get("text", "")
            if not memory_text:
                continue
            memory_node = _stable_node_id("mem", memory_text)
            self._capsule_graph.upsert_node(
                memory_node,
                type="memory",
                ts=payload.get("timestamp"),
                score=match.get("score", 0.0),
            )
            weight = max(0.001, 1.0 - float(match.get("score", 0.0)))
            self._capsule_graph.upsert_edge(query_node, memory_node, weight=weight, rank=idx)

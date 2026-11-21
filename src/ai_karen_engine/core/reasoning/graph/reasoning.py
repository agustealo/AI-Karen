from __future__ import annotations

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

logger = logging.getLogger("ai_karen.reasoning.graph")


class ReasoningGraph:
    """ICE facade without an independent memory-graph presentation path.

    Only NeuroRecall's selected, source-authorized evidence may be projected
    through `project_selected_memory_graph`. Legacy CapsuleGraph mirroring
    retained raw memory-match fingerprints across calls without tenant scope
    or revocation checks, so it must not be enabled.
    """

    def __init__(
        self,
        *,
        llm: LLMUtils,
        engine: Optional[SoftReasoningEngine] = None,
        policy: Optional[ICEWritebackPolicy] = None,
        enable_graph_mirroring: bool = False,
    ) -> None:
        if llm is None:
            raise ValueError("ReasoningGraph requires a runtime-injected generation client")
        if enable_graph_mirroring:
            raise ValueError(
                "Legacy reasoning graph mirroring is disabled: use authorized "
                "NeuroRecall selection and project_selected_memory_graph"
            )

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
        self.llm = llm
        self.policy = policy or ICEWritebackPolicy()
        self._ice = PremiumICEWrapper(sr=None, subengine=None, llm=self.llm, policy=self.policy)

    def run(
        self,
        text: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        policy_overrides: Optional[Dict[str, Any]] = None,
    ) -> ReasoningTrace:
        trace = self._run_internal(text, metadata=metadata, policy_overrides=policy_overrides)
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
        return trace

    @property
    def capsule_graph(self) -> Optional[CapsuleGraph]:
        """Compatibility reader; never expose ungoverned memory evidence."""
        return None

    def visualize_capsule_cli(self) -> Optional[str]:
        """Legacy graph display is disabled until canonical authorization."""
        return None

    def capsule_dot(self) -> Optional[str]:
        """Legacy graph export is disabled until canonical authorization."""
        return None

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


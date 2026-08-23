"""
Pipeline Policy for AI Karen Resilience Layer.

Defines timeout budgets, retry configurations, and sensitivities.
"""

from typing import Dict
from dataclasses import dataclass

@dataclass
class StagePolicy:
    timeout_seconds: float
    max_retries: int
    sensitivity_class: str

class PipelinePolicy:
    """Defines operational policies for execution stages."""
    
    def __init__(self):
        self._policies: Dict[str, StagePolicy] = {
            "spacy": StagePolicy(timeout_seconds=2.0, max_retries=1, sensitivity_class="normal"),
            "distilbert": StagePolicy(timeout_seconds=3.0, max_retries=1, sensitivity_class="normal"),
            "leangraph_projection": StagePolicy(timeout_seconds=5.0, max_retries=3, sensitivity_class="high"),
            "profile_synthesis": StagePolicy(timeout_seconds=10.0, max_retries=1, sensitivity_class="high"),
            "echocore_batch": StagePolicy(timeout_seconds=300.0, max_retries=0, sensitivity_class="high"),
            "reasoning_retrieval": StagePolicy(timeout_seconds=4.0, max_retries=1, sensitivity_class="high"),
            "reasoning_causal": StagePolicy(timeout_seconds=6.0, max_retries=1, sensitivity_class="high"),
            "reasoning_graph": StagePolicy(timeout_seconds=6.0, max_retries=1, sensitivity_class="high"),
            "reasoning_soft": StagePolicy(timeout_seconds=4.0, max_retries=1, sensitivity_class="high"),
            "reasoning_synthesis": StagePolicy(timeout_seconds=8.0, max_retries=1, sensitivity_class="high"),
            "kro_orchestrator": StagePolicy(timeout_seconds=12.0, max_retries=0, sensitivity_class="high"),
        }
        
    def get_policy(self, stage_name: str) -> StagePolicy:
        """Get policy for a stage, returning a safe default if not found."""
        return self._policies.get(
            stage_name, 
            StagePolicy(timeout_seconds=5.0, max_retries=1, sensitivity_class="normal")
        )

pipeline_policy = PipelinePolicy()

def get_pipeline_policy() -> PipelinePolicy:
    return pipeline_policy

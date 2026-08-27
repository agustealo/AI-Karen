from __future__ import annotations

import inspect

from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.runtime.composition import build_runtime_composition
from ai_karen_engine.core.runtime.decision_pipeline import RuntimeDecisionPipeline
from ai_karen_engine.core.runtime.policy import RuntimePolicyEnforcer


def test_cortex_does_not_construct_or_import_runtime_policy() -> None:
    source = inspect.getsource(CortexExecutionDecider)
    assert "RuntimePolicyEnforcer" not in source
    assert "PolicyEvaluationRequest" not in source
    assert "_policy_enforcer" not in source


def test_runtime_composition_owns_cortex_policy_sequence() -> None:
    composition = build_runtime_composition()
    assert isinstance(composition.decision_pipeline, RuntimeDecisionPipeline)
    assert isinstance(composition.runtime_policy, RuntimePolicyEnforcer)
    assert composition.decision_pipeline.cortex is composition.cognitive_cortex
    assert composition.decision_pipeline.policy is composition.runtime_policy
    assert composition.cortex is composition.decision_pipeline

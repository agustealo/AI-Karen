from ai_karen_engine.core.memory.neuro import decide_activation_mode


def test_graph_query_escalation_uses_activation_authority():
    decision = decide_activation_mode(query="why did we choose that relation")
    assert decision.mode.value == "graph"
    assert "selected_mode:graph" in decision.reasons

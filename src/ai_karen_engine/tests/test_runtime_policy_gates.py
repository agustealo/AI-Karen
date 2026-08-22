from ai_karen_engine.core.cortex.runtime_policy import RuntimePolicyDecision


def test_runtime_policy_decision_defaults():
    decision = RuntimePolicyDecision.from_cortex({})
    assert decision.requires_deep_reasoning is False
    assert decision.requires_medusa is False
    assert decision.policy_token


def test_runtime_policy_decision_from_cortex_flags():
    decision = RuntimePolicyDecision.from_cortex(
        {"requires_deep_reasoning": True, "requires_medusa": True}
    )
    assert decision.requires_deep_reasoning is True
    assert decision.requires_medusa is True


def test_reasoning_executor_is_single_owner():
    """ReasoningExecutor is the single execution owner for core/reasoning."""
    from ai_karen_engine.core.reasoning.executor import ReasoningExecutor

    executor = ReasoningExecutor()
    assert executor is not None


def test_kire_kro_integration_is_retired():
    """KIREKROIntegration must raise on any operation."""
    from ai_karen_engine.core.cortex.kire_kro_integration import KIREKROIntegration

    integration = KIREKROIntegration()
    import asyncio

    async def _check() -> None:
        try:
            await integration.initialize()
        except RuntimeError as exc:
            assert "retired" in str(exc).lower()
            return
        raise AssertionError("KIREKROIntegration.initialize() did not raise")

    asyncio.run(_check())

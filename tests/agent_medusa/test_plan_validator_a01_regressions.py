"""Regression coverage for Medusa's pure plan-validation authority."""

from ai_karen_engine.agent_medusa.contracts.deep_execution_plan import (
    DeepExecutionPlan,
    PlanStep,
    StepInputContract,
    StepOutputContract,
)
from ai_karen_engine.agent_medusa.planning.plan_validator import PlanValidator


def _plan(*steps: PlanStep) -> DeepExecutionPlan:
    return DeepExecutionPlan(request_id="validation-regression", steps=list(steps))


def test_independent_step_followed_by_dependent_step_terminates() -> None:
    plan = _plan(
        PlanStep(id="research", agent_specialist="researcher"),
        PlanStep(
            id="analysis",
            agent_specialist="analyst",
            dependencies=["research"],
        ),
    )
    report = PlanValidator().validate(plan)
    assert report.valid, report.errors
    assert PlanValidator()._calculate_max_parallelism(plan) == 1


def test_parallel_frontier_is_bounded() -> None:
    plan = _plan(
        PlanStep(id="a", agent_specialist="researcher"),
        PlanStep(id="b", agent_specialist="analyst"),
        PlanStep(id="join", agent_specialist="analyst", dependencies=["a", "b"]),
    )
    report = PlanValidator().validate(plan, max_parallel_steps=1)
    assert not report.valid
    assert any("parallel steps" in error for error in report.errors)


def test_undeclared_dependency_fails_cleanly() -> None:
    plan = _plan(
        PlanStep(id="a", agent_specialist="analyst", dependencies=["missing"]),
    )
    report = PlanValidator().validate(plan)
    assert not report.valid
    assert any("unknown step" in error for error in report.errors)


def test_cycle_fails_cleanly() -> None:
    plan = _plan(
        PlanStep(id="a", agent_specialist="analyst", dependencies=["b"]),
        PlanStep(id="b", agent_specialist="researcher", dependencies=["a"]),
    )
    report = PlanValidator().validate(plan)
    assert not report.valid
    assert any("dependency cycle" in error for error in report.errors)


def test_downstream_or_unrelated_output_does_not_satisfy_input() -> None:
    plan = _plan(
        PlanStep(
            id="consumer",
            agent_specialist="analyst",
            input_contract=StepInputContract(required_inputs=["evidence"]),
        ),
        PlanStep(
            id="unrelated",
            agent_specialist="researcher",
            output_contract=StepOutputContract(outputs_provided=["evidence"]),
        ),
    )
    report = PlanValidator().validate(plan)
    assert not report.valid
    assert any("requires input 'evidence'" in error for error in report.errors)


def test_input_from_transitive_predecessor_is_valid() -> None:
    plan = _plan(
        PlanStep(
            id="research",
            agent_specialist="researcher",
            output_contract=StepOutputContract(outputs_provided=["evidence"]),
        ),
        PlanStep(id="normalize", agent_specialist="analyst", dependencies=["research"]),
        PlanStep(
            id="report",
            agent_specialist="analyst",
            dependencies=["normalize"],
            input_contract=StepInputContract(required_inputs=["evidence"]),
        ),
    )
    report = PlanValidator().validate(plan)
    assert report.valid, report.errors


def test_initial_input_satisfies_required_contract() -> None:
    plan = _plan(
        PlanStep(
            id="report",
            agent_specialist="analyst",
            input_data={"query": "summarize"},
            input_contract=StepInputContract(required_inputs=["query"]),
        ),
    )
    report = PlanValidator().validate(plan)
    assert report.valid, report.errors


def test_step_count_limit_is_respected() -> None:
    plan = _plan(
        PlanStep(id="a", agent_specialist="analyst"),
        PlanStep(id="b", agent_specialist="analyst", dependencies=["a"]),
    )
    report = PlanValidator().validate(plan, max_steps=1)
    assert not report.valid
    assert any("exceeds max" in error for error in report.errors)

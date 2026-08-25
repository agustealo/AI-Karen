import pytest

from benchmarks.cognitive.scenario_runner import load_scenarios, run_scenario, fixtures_dir


@pytest.mark.cognitive
def test_runner_all_scenarios():
    scenarios = load_scenarios()
    assert scenarios, "no scenarios loaded"
    for sc in scenarios:
        result = run_scenario(sc)
        assert result is not None
        assert result.scenario_id == sc.scenario_id
        assert result.kind == sc.kind
        print(f"{sc.kind.value:20s} {sc.scenario_id:45s} -> {result.verdict} conf={result.confidence:.3f} defs={len(result.defects)}")

"""KCON-772 verified Playwright evidence aggregation, without fake production runs."""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "analyze_karen_latency.py"
SPEC = importlib.util.spec_from_file_location("kcon772_analyzer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
analyzer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyzer)


def _attach(name: str, data: dict) -> dict:
    return {
        "name": name,
        "contentType": "application/json",
        "body": base64.b64encode(json.dumps(data).encode()).decode("ascii"),
    }


def _result(index: int, duration: float, *, mode: str = "model") -> dict:
    base = {
        "schema_version": 1,
        "scenario": "weather",
        "metric": "submit_to_visible_assertion_ms",
        "duration_ms": duration,
        "observation": "post_assertion_not_first_paint",
    }
    first = {**base, "clock": "browser_performance_now"}
    second = {
        **base,
        "correlation_id": f"corr-{index}",
        "assistant_message_id": f"assistant-{index}",
        "presentation_id": f"presentation-{index}",
        "model_execution_receipt_present": mode == "model",
    }
    return {
        "status": "passed",
        "retry": 0,
        "attachments": [
            _attach("kcon766-first-prompt-visible-timing", first),
            _attach("kcon767-correlated-first-prompt-timing", second),
        ],
    }


def _report(
    results: list[dict], *, scenarios: list[str] | None = None
) -> dict:
    # Match the actual Playwright JSON reporter: each repeat-each execution
    # creates its own spec with a distinct ID, and a test with one result.
    # The JSON reporter does not expose the runtime repeatEachIndex field.
    labels = scenarios if scenarios is not None else ["weather"] * len(results)
    assert len(labels) == len(results)
    return {
        "suites": [
            {"specs": [
                {
                    "id": f"first-prompt-{index}",
                    "ok": True,
                    "title": (
                        f"one first {scenario} prompt renders backend-attested UI "
                        "immediately and after reload"
                    ),
                    "tests": [{
                        "projectName": "chromium",
                        "expectedStatus": "passed",
                        "status": "expected",
                        "results": [result],
                    }],
                }
                for index, (result, scenario) in enumerate(zip(results, labels))
            ], "suites": []}
        ],
    }


REQUIRED_SCENARIOS = (
    "time", "weather", "search", "news",
    "current movies", "current movie source table",
)


def _complete_required_report() -> dict:
    """Test-only Playwright JSON inventory for six complete scenario cohorts."""
    results: list[dict] = []
    scenarios: list[str] = []
    for index, scenario in enumerate(REQUIRED_SCENARIOS):
        for sample in range(10):
            item = _result(index * 10 + sample, float(sample + 1))
            for attachment in item["attachments"]:
                payload = json.loads(base64.b64decode(attachment["body"]))
                payload["scenario"] = scenario
                attachment["body"] = base64.b64encode(
                    json.dumps(payload).encode()
                ).decode("ascii")
            results.append(item)
            scenarios.append(scenario)
    return _report(results, scenarios=scenarios)


def test_kcon772_nearest_rank_percentiles_require_ten_distinct_executions(tmp_path):
    report = _report([_result(i, float(i * 10)) for i in range(1, 11)])
    summary = analyzer.analyze(report, tmp_path)
    assert summary["status"] == "sufficient_observations"
    assert summary["cohort"] == "cold_warm_unclassified"
    assert summary["percentile_method"] == "nearest_rank"
    assert summary["groups"] == [{
        "scenario": "weather",
        "response_origin": "model",
        "sample_count": 10,
        "status": "sufficient",
        "p50_ms": 50.0,
        "p95_ms": 100.0,
    }]
    output = json.dumps(summary)
    assert "assistant-1" not in output
    assert "corr-1" not in output
    assert "presentation-1" not in output


def test_kcon772_under_sampled_browser_data_is_not_a_release_benchmark(tmp_path):
    report = _report([_result(i, float(i)) for i in range(9)])
    summary = analyzer.analyze(report, tmp_path)
    assert summary["status"] == "insufficient_evidence"
    assert summary["groups"][0]["p50_ms"] is None
    assert summary["groups"][0]["p95_ms"] is None
    path = tmp_path / "playwright.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        check=False, capture_output=True, text=True,
    )
    assert run.returncode == 2
    assert json.loads(run.stdout)["status"] == "insufficient_evidence"


def test_kcon772_never_merges_model_and_observation_samples(tmp_path):
    report = _report([
        *[_result(i, float(i), mode="model") for i in range(10)],
        *[_result(i + 10, float(i), mode="observation") for i in range(9)],
    ])
    summary = analyzer.analyze(report, tmp_path)
    assert summary["status"] == "insufficient_evidence"
    by_origin = {x["response_origin"]: x for x in summary["groups"]}
    assert by_origin["model"]["sample_count"] == 10
    assert by_origin["observation"]["sample_count"] == 9
    assert by_origin["observation"]["p95_ms"] is None


@pytest.mark.parametrize("case", ["duplicate", "mismatch", "negative", "failed", "unpaired"])
def test_kcon772_rejects_unverifiable_evidence(tmp_path, case):
    good = _result(1, 20.0)
    if case == "duplicate":
        results = [good, good]
    else:
        bad = json.loads(json.dumps(good))
        if case == "mismatch":
            payload = json.loads(base64.b64decode(bad["attachments"][1]["body"]))
            payload["duration_ms"] = 200
            bad["attachments"][1] = _attach("kcon767-correlated-first-prompt-timing", payload)
        elif case == "negative":
            payload = json.loads(base64.b64decode(bad["attachments"][0]["body"]))
            payload["duration_ms"] = -1
            bad["attachments"][0] = _attach("kcon766-first-prompt-visible-timing", payload)
        elif case == "failed":
            bad["status"] = "failed"
        else:
            bad["attachments"].pop()
        results = [bad]
    with pytest.raises(analyzer.EvidenceError):
        analyzer.analyze(_report(results), tmp_path)


def test_kcon772_rejects_attachment_path_escape(tmp_path):
    first = _result(0, 12.0)
    first["attachments"][0] = {
        "name": "kcon766-first-prompt-visible-timing",
        "contentType": "application/json",
        "path": "../outside.json",
    }
    with pytest.raises(analyzer.EvidenceError, match="outside_report_directory"):
        analyzer.analyze(_report([first]), tmp_path)


def test_kcon772_rejects_lowered_sample_requirement(tmp_path):
    with pytest.raises(analyzer.EvidenceError, match="at_least_ten"):
        analyzer.analyze(_report([]), tmp_path, min_samples=1)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("specs", "invalid_playwright_specs"),
        ("tests", "invalid_playwright_tests"),
        ("results", "invalid_playwright_results"),
        ("attachments", "invalid_playwright_attachments"),
    ],
)
def test_kcon772_malformed_report_shape_fails_closed(tmp_path, mutation, expected):
    report = _report([_result(1, 11.0)])
    suite = report["suites"][0]
    if mutation == "specs":
        suite["specs"] = None
    elif mutation == "tests":
        suite["specs"][0]["tests"] = None
    elif mutation == "results":
        suite["specs"][0]["tests"][0]["results"] = None
    else:
        suite["specs"][0]["tests"][0]["results"][0]["attachments"] = None
    with pytest.raises(analyzer.EvidenceError, match=expected):
        analyzer.analyze(report, tmp_path)


def test_kcon772_oversized_duration_fails_closed(tmp_path):
    report = _report([_result(1, 10.0)])
    sample = report["suites"][0]["specs"][0]["tests"][0]["results"][0]
    payload = json.loads(base64.b64decode(sample["attachments"][0]["body"]))
    payload["duration_ms"] = 10 ** 1000
    sample["attachments"][0] = _attach("kcon766-first-prompt-visible-timing", payload)
    with pytest.raises(analyzer.EvidenceError, match="duration_nonfinite_or_negative"):
        analyzer.analyze(report, tmp_path)


def test_kcon775_one_scenario_cannot_impersonate_complete_six_scenario_run(tmp_path):
    required = REQUIRED_SCENARIOS
    report = _report([_result(i, float(i * 10)) for i in range(1, 11)])
    summary = analyzer.analyze(report, tmp_path, required_scenarios=required)
    assert summary["status"] == "insufficient_evidence"
    assert summary["groups"][0]["status"] == "sufficient"
    assert summary["missing_scenarios"] == [
        "current movie source table", "current movies", "news", "search", "time",
    ]
    assert summary["required_scenarios"] == list(required)


def test_kcon775_rejects_unexpected_or_duplicate_scenario_requirements(tmp_path):
    report = _report([_result(i, float(i)) for i in range(10)])
    with pytest.raises(analyzer.EvidenceError, match="unexpected_benchmark_scenario"):
        analyzer.analyze(report, tmp_path, required_scenarios=("time",))
    with pytest.raises(analyzer.EvidenceError, match="invalid_required_scenarios"):
        analyzer.analyze(report, tmp_path, required_scenarios=("weather", "weather"))
    with pytest.raises(analyzer.EvidenceError, match="invalid_required_scenarios"):
        analyzer.analyze(report, tmp_path, required_scenarios=("",))


def test_kcon775_cli_rejects_missing_required_scenarios_even_with_ten_valid_results(tmp_path):
    report = _report([_result(i, float(i)) for i in range(10)])
    path = tmp_path / "playwright.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable, str(SCRIPT), str(path),
            "--require-scenarios=time,weather,search,news,current movies,current movie source table",
        ],
        check=False, capture_output=True, text=True,
    )
    assert run.returncode == 2
    parsed = json.loads(run.stdout)
    assert parsed["status"] == "insufficient_evidence"
    assert "weather" not in parsed["missing_scenarios"]
    assert len(parsed["missing_scenarios"]) == 5


def test_kcon775_complete_scenario_set_publishes_percentiles(tmp_path):
    summary = analyzer.analyze(
        _complete_required_report(), tmp_path, required_scenarios=REQUIRED_SCENARIOS,
    )
    assert summary["status"] == "sufficient_observations"
    assert summary["missing_scenarios"] == []
    assert len(summary["groups"]) == 6
    assert all(group["sample_count"] == 10 for group in summary["groups"])
    assert all(group["p50_ms"] == 5.0 for group in summary["groups"])
    assert all(group["p95_ms"] == 10.0 for group in summary["groups"])


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("retry", "retry_is_not_an_independent_execution"),
        ("missing_retry", "retry_is_not_an_independent_execution"),
        ("bool_retry", "retry_is_not_an_independent_execution"),
        ("multiple_results", "retried_or_multiple_benchmark_attempts"),
        ("duplicate_spec_id", "duplicate_benchmark_spec_id"),
        ("missing_spec_id", "missing_or_invalid_benchmark_spec_id"),
        ("negative_spec_id", "missing_or_invalid_benchmark_spec_id"),
        ("bool_spec_id", "missing_or_invalid_benchmark_spec_id"),
        ("wrong_spec_title", "mismatched_first_prompt_spec"),
        ("wrong_project", "unverified_benchmark_project_or_expectation"),
        ("expected_failure", "unverified_benchmark_project_or_expectation"),
    ],
)
def test_kcon772_rejects_retry_masking_and_non_independent_repeats(
    tmp_path, mutation, expected_error
):
    # A unique correlation/assistant/presentation ID is not proof of an
    # independent Playwright execution; verified spec IDs and retry records
    # must identify genuinely separate repeat-each iterations.
    report = _report([_result(1, 10.0), _result(2, 20.0)])
    specs = report["suites"][0]["specs"]
    first = specs[0]["tests"][0]
    second = specs[1]["tests"][0]
    if mutation == "retry":
        first["results"][0]["retry"] = 1
    elif mutation == "missing_retry":
        del first["results"][0]["retry"]
    elif mutation == "bool_retry":
        first["results"][0]["retry"] = False
    elif mutation == "multiple_results":
        first["results"].append(_result(3, 30.0))
    elif mutation == "duplicate_spec_id":
        specs[1]["id"] = specs[0]["id"]
    elif mutation == "missing_spec_id":
        del specs[0]["id"]
    elif mutation == "negative_spec_id":
        specs[0]["id"] = -1
    elif mutation == "bool_spec_id":
        specs[0]["id"] = True
    elif mutation == "wrong_spec_title":
        specs[0]["title"] = "a different test with copied measurements"
    elif mutation == "wrong_project":
        first["projectName"] = "firefox"
    elif mutation == "expected_failure":
        first["expectedStatus"] = "failed"
    with pytest.raises(analyzer.EvidenceError, match=expected_error):
        analyzer.analyze(report, tmp_path)


def test_kcon772_ten_attempts_of_one_test_cannot_publish_percentiles(tmp_path):
    attempts = [_result(index, float(index + 1)) for index in range(10)]
    report = _report([attempts[0]])
    report["suites"][0]["specs"][0]["tests"][0]["results"] = attempts
    with pytest.raises(
        analyzer.EvidenceError, match="retried_or_multiple_benchmark_attempts"
    ):
        analyzer.analyze(report, tmp_path)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing_attachments", "required_benchmark_sample_missing"),
        ("failed_without_attachments", "unverified_required_benchmark_spec"),
        ("skipped_without_attachments", "unverified_required_benchmark_spec"),
        ("unknown_without_attachments", "unexpected_benchmark_spec"),
        ("no_test", "incomplete_required_benchmark_spec"),
        ("two_tests", "incomplete_required_benchmark_spec"),
        ("no_result", "incomplete_required_benchmark_execution"),
        ("two_results", "incomplete_required_benchmark_execution"),
        ("unexpected_outcome", "unverified_required_benchmark_outcome"),
        ("missing_outcome", "unverified_required_benchmark_outcome"),
        ("failed_spec", "unverified_required_benchmark_spec"),
    ],
)
def test_kcon775_full_scenario_evidence_cannot_hide_unmeasured_executions(
    tmp_path, mutation, expected_error
):
    # All six scenarios already have 10 valid unique samples. A hidden failed,
    # skipped, unrecognized or unmeasured execution must never be ignored and
    # leave a false "sufficient" release-ready percentile report.
    report = _complete_required_report()
    specs = report["suites"][0]["specs"]
    first = specs[0]
    test = first["tests"][0]
    result = test["results"][0]

    if mutation == "missing_attachments":
        result["attachments"] = []
    elif mutation in {"failed_without_attachments", "skipped_without_attachments"}:
        first["ok"] = False
        test["status"] = "unexpected" if mutation.startswith("failed") else "skipped"
        result["status"] = "failed" if mutation.startswith("failed") else "skipped"
        result["attachments"] = []
    elif mutation == "unknown_without_attachments":
        first["title"] = "one first unauthorized prompt renders backend-attested UI immediately and after reload"
        result["attachments"] = []
    elif mutation == "no_test":
        first["tests"] = []
    elif mutation == "two_tests":
        first["tests"].append(dict(test))
    elif mutation == "no_result":
        test["results"] = []
    elif mutation == "two_results":
        test["results"].append(dict(result))
    elif mutation == "unexpected_outcome":
        test["status"] = "flaky"
    elif mutation == "missing_outcome":
        del test["status"]
    elif mutation == "failed_spec":
        first["ok"] = False

    with pytest.raises(analyzer.EvidenceError, match=expected_error):
        analyzer.analyze(report, tmp_path, required_scenarios=REQUIRED_SCENARIOS)


def test_kcon775_missing_evidence_remains_skippable_only_without_required_coverage(tmp_path):
    # Preserve the analyzer's generic read-only behavior: unmeasured unrelated
    # tests may appear in a generic report, but not in the explicit six-scenario
    # local benchmark that claims complete execution coverage.
    report = _report([_result(i, float(i + 1)) for i in range(10)])
    report["suites"][0]["specs"][0]["tests"][0]["results"][0]["attachments"] = []
    summary = analyzer.analyze(report, tmp_path)
    assert summary["status"] == "insufficient_evidence"
    assert summary["groups"][0]["sample_count"] == 9


def test_kcon775_reporter_test_title_must_match_measured_scenario(tmp_path):
    report = _complete_required_report()
    spec = report["suites"][0]["specs"][0]
    spec["title"] = (
        "one first weather prompt renders backend-attested UI immediately and after reload"
    )
    with pytest.raises(analyzer.EvidenceError, match="mismatched_first_prompt_spec"):
        analyzer.analyze(report, tmp_path, required_scenarios=REQUIRED_SCENARIOS)

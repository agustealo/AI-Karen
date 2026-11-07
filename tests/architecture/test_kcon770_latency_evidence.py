"""KCON-770 verified Playwright evidence aggregation, without fake production runs."""

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
SPEC = importlib.util.spec_from_file_location("kcon770_analyzer", SCRIPT)
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
        "attachments": [
            _attach("kcon766-first-prompt-visible-timing", first),
            _attach("kcon767-correlated-first-prompt-timing", second),
        ],
    }


def _report(results: list[dict]) -> dict:
    return {
        "suites": [
            {"specs": [{"tests": [{"results": results}]}], "suites": []}
        ],
    }


def test_kcon770_nearest_rank_percentiles_require_ten_distinct_executions(tmp_path):
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


def test_kcon770_under_sampled_browser_data_is_not_a_release_benchmark(tmp_path):
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


def test_kcon770_never_merges_model_and_observation_samples(tmp_path):
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
def test_kcon770_rejects_unverifiable_evidence(tmp_path, case):
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


def test_kcon770_rejects_attachment_path_escape(tmp_path):
    first = _result(0, 12.0)
    first["attachments"][0] = {
        "name": "kcon766-first-prompt-visible-timing",
        "contentType": "application/json",
        "path": "../outside.json",
    }
    with pytest.raises(analyzer.EvidenceError, match="outside_report_directory"):
        analyzer.analyze(_report([first]), tmp_path)


def test_kcon770_rejects_lowered_sample_requirement(tmp_path):
    with pytest.raises(analyzer.EvidenceError, match="at_least_ten"):
        analyzer.analyze(_report([]), tmp_path, min_samples=1)

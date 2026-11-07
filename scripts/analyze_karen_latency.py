#!/usr/bin/env python3
"""Summarize verified CopilotKit first-prompt Playwright measurements.

This is a read-only, local acceptance artifact analyzer, not runtime telemetry.
It never generates network traffic, runs a model, or labels a model warm/cold.
The input must be a Playwright JSON reporter file containing *paired* KCON-766
and KCON-767 attachments from the same real browser test result.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

FIRST_ATTACHMENT = "kcon766-first-prompt-visible-timing"
CORRELATED_ATTACHMENT = "kcon767-correlated-first-prompt-timing"
METRIC = "submit_to_visible_assertion_ms"
OBSERVATION = "post_assertion_not_first_paint"
_SAFE_ID = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}$")


class EvidenceError(ValueError):
    """Reject incomplete or non-correlatable release evidence."""


def _walk_test_results(nodes: Any) -> Iterator[Mapping[str, Any]]:
    if not isinstance(nodes, list):
        raise EvidenceError("invalid_playwright_suites")
    for node in nodes:
        if not isinstance(node, dict):
            raise EvidenceError("invalid_playwright_suite")
        specs = node.get("specs", [])
        if not isinstance(specs, list):
            raise EvidenceError("invalid_playwright_specs")
        for spec in specs:
            if not isinstance(spec, dict):
                raise EvidenceError("invalid_playwright_spec")
            tests = spec.get("tests", [])
            if not isinstance(tests, list):
                raise EvidenceError("invalid_playwright_tests")
            for test in tests:
                if not isinstance(test, dict):
                    raise EvidenceError("invalid_playwright_test")
                results = test.get("results", [])
                if not isinstance(results, list):
                    raise EvidenceError("invalid_playwright_results")
                for result in results:
                    if not isinstance(result, dict):
                        raise EvidenceError("invalid_playwright_result")
                    yield result
        yield from _walk_test_results(node.get("suites", []))


def _attachment(result: Mapping[str, Any], name: str, root: Path) -> dict[str, Any] | None:
    attachments = result.get("attachments", [])
    if not isinstance(attachments, list):
        raise EvidenceError("invalid_playwright_attachments")
    matches = [
        attachment
        for attachment in attachments
        if isinstance(attachment, dict) and attachment.get("name") == name
    ]
    if len(matches) > 1:
        raise EvidenceError("duplicate_timing_attachment")
    if not matches:
        return None
    item = matches[0]
    if item.get("contentType") != "application/json":
        raise EvidenceError("timing_attachment_wrong_content_type")
    if isinstance(item.get("body"), str):
        try:
            raw = base64.b64decode(item["body"], validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise EvidenceError("timing_attachment_invalid_base64") from exc
    elif isinstance(item.get("path"), str):
        # Playwright may store large attachments on disk. Never read outside
        # the supplied report's directory, even if the report is untrusted.
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise EvidenceError("timing_attachment_outside_report_directory")
        if not path.is_file() or path.stat().st_size > 65536:
            raise EvidenceError("timing_attachment_unavailable_or_oversized")
        raw = path.read_bytes()
    else:
        raise EvidenceError("timing_attachment_missing_data")
    if len(raw) > 65536:
        raise EvidenceError("timing_attachment_oversized")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("timing_attachment_invalid_json") from exc
    if not isinstance(payload, dict):
        raise EvidenceError("timing_attachment_not_object")
    return payload


def _duration(payload: Mapping[str, Any]) -> float:
    value = payload.get("duration_ms")
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise EvidenceError("duration_missing_or_invalid")
    try:
        measured = float(value)
    except OverflowError as exc:
        raise EvidenceError("duration_nonfinite_or_negative") from exc
    if not math.isfinite(measured) or measured < 0:
        raise EvidenceError("duration_nonfinite_or_negative")
    return measured


def _validated_sample(
    first: Mapping[str, Any], correlated: Mapping[str, Any]
) -> tuple[str, str, float, tuple[str, str, str]]:
    for payload in (first, correlated):
        if payload.get("schema_version") != 1:
            raise EvidenceError("unexpected_timing_schema")
        if payload.get("metric") != METRIC:
            raise EvidenceError("unexpected_timing_metric")
        if payload.get("observation") != OBSERVATION:
            raise EvidenceError("paint_timing_not_observed")
    if first.get("clock") != "browser_performance_now":
        raise EvidenceError("unverified_browser_clock")
    scenario = first.get("scenario")
    if not isinstance(scenario, str) or not re.fullmatch(r"[a-zA-Z0-9 _-]{1,64}", scenario):
        raise EvidenceError("invalid_scenario")
    if correlated.get("scenario") != scenario:
        raise EvidenceError("mismatched_scenarios")
    first_ms = _duration(first)
    correlated_ms = _duration(correlated)
    if first_ms != correlated_ms:
        raise EvidenceError("timing_pair_mismatch")
    identity = tuple(correlated.get(k) for k in (
        "correlation_id", "assistant_message_id", "presentation_id"
    ))
    if any(not isinstance(v, str) or not _SAFE_ID.fullmatch(v) for v in identity):
        raise EvidenceError("unverified_timing_identity")
    receipt = correlated.get("model_execution_receipt_present")
    if not isinstance(receipt, bool):
        raise EvidenceError("missing_model_receipt_classification")
    return scenario, "model" if receipt else "observation", first_ms, identity


def _nearest_rank(values: Sequence[float], percentile: int) -> float:
    index = max(0, math.ceil(len(values) * percentile / 100) - 1)
    return round(sorted(values)[index], 2)


def analyze(report: Mapping[str, Any], root: Path, min_samples: int = 10) -> dict[str, Any]:
    """Return sanitized summaries; no prompts, content, or IDs leave this function."""
    if min_samples < 10:
        raise EvidenceError("minimum_sample_count_must_be_at_least_ten")
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    identities: set[tuple[str, str, str]] = set()
    for result in _walk_test_results(report.get("suites", [])):
        first = _attachment(result, FIRST_ATTACHMENT, root)
        second = _attachment(result, CORRELATED_ATTACHMENT, root)
        if first is None and second is None:
            continue
        if first is None or second is None:
            raise EvidenceError("unpaired_first_prompt_evidence")
        if result.get("status") != "passed":
            raise EvidenceError("failed_or_incomplete_benchmark_run")
        scenario, origin, duration, identity = _validated_sample(first, second)
        if identity in identities:
            raise EvidenceError("duplicate_correlated_execution")
        identities.add(identity)
        groups[(scenario, origin)].append(duration)
    summary = []
    for (scenario, origin), samples in sorted(groups.items()):
        sufficient = len(samples) >= min_samples
        summary.append({
            "scenario": scenario,
            "response_origin": origin,
            "sample_count": len(samples),
            "status": "sufficient" if sufficient else "insufficient",
            "p50_ms": _nearest_rank(samples, 50) if sufficient else None,
            "p95_ms": _nearest_rank(samples, 95) if sufficient else None,
        })
    complete = bool(summary) and all(x["status"] == "sufficient" for x in summary)
    return {
        "schema_version": 1,
        "metric": METRIC,
        "observation": OBSERVATION,
        "cohort": "cold_warm_unclassified",
        "percentile_method": "nearest_rank",
        "required_samples_per_group": min_samples,
        "status": "sufficient_observations" if complete else "insufficient_evidence",
        "groups": summary,
        "limitations": [
            "Playwright visibility assertion includes automation and polling delay",
            "Browser observation is not verified first paint or model time to first token",
            "Cold/warm provider state is not observed by these attachments",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("playwright_json", type=Path, help="Actual Playwright JSON reporter file")
    parser.add_argument("--min-samples", type=int, default=10)
    parser.add_argument("--output", type=Path, help="Write sanitized JSON report to this file")
    args = parser.parse_args(argv)
    try:
        source = args.playwright_json.resolve()
        if not source.is_file():
            raise EvidenceError("playwright_report_not_found")
        report = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise EvidenceError("playwright_report_not_object")
        summary = analyze(report, source.parent, args.min_samples)
    except (EvidenceError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Never echo source contents, paths, or potentially sensitive exceptions.
        reason = str(exc) if isinstance(exc, EvidenceError) else "invalid_report"
        print(json.dumps({"status": "rejected", "reason": reason}), file=sys.stderr)
        return 2
    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output:
        try:
            args.output.write_text(rendered, encoding="utf-8")
        except OSError:
            print(json.dumps({"status": "rejected", "reason": "output_unavailable"}), file=sys.stderr)
            return 2
    else:
        print(rendered, end="")
    return 0 if summary["status"] == "sufficient_observations" else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""COG-EVAL-1 report and defect-registry test."""

from __future__ import annotations

import pytest
from benchmarks.cognitive.contracts import ScenarioKind
from benchmarks.cognitive.report import build_results, defects, format_report, summarize


@pytest.mark.cognitive
def test_report_builds_for_all_scenarios():
    rows = build_results()
    kinds_present = {sc.kind for sc, _, _ in rows}
    expected_kinds = set(ScenarioKind)
    assert kinds_present == expected_kinds


@pytest.mark.cognitive
def test_report_summary_totals():
    summary = summarize()
    assert summary["total"] == 17
    assert summary["passing"] == 17
    assert summary["failing"] == 0
    assert summary["defect_count"] == 0


@pytest.mark.cognitive
def test_report_text_is_deterministic_and_documents_clean_run():
    rows = build_results()
    text = format_report(rows)
    assert "COG-EVAL-1 Cognitive Benchmark Report" in text
    assert "Pass: 17" in text
    assert "No defects exposed." in text


@pytest.mark.cognitive
def test_defect_registry_is_empty_after_contract_update():
    assert defects() == []


@pytest.mark.cognitive
def test_report_group_covers_all_kinds():
    from benchmarks.cognitive.contracts import REPORT_GROUPS

    covered = set()
    for kinds in REPORT_GROUPS.values():
        covered.update(kinds)
    assert covered == set(ScenarioKind)

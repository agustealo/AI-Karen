"""Deterministic COG-EVAL-1 summary report.

Groups scenario outcomes by cognitive category (REPORT_GROUPS) and emits a
stable, reproducible text report so CI can diff regressions run-over-run.
"""

from __future__ import annotations

from typing import Any

from benchmarks.cognitive.contracts import (
    REPORT_GROUPS,
    CognitiveResult,
    DefectRecord,
    Scenario,
    ScenarioKind,
)
from benchmarks.cognitive.scenario_runner import check, run_scenario, scenarios_for


def build_results() -> list[tuple[Scenario, CognitiveResult, list[str]]]:
    rows: list[tuple[Scenario, CognitiveResult, list[str]]] = []
    for kind in ScenarioKind:
        for scenario in scenarios_for(kind):
            result = run_scenario(scenario)
            failures = check(scenario)
            rows.append((scenario, result, failures))
    return rows


def summarize(rows: list[tuple[Scenario, CognitiveResult, list[str]]] | None = None) -> dict[str, Any]:
    if rows is None:
        rows = build_results()
    total = len(rows)
    passing = sum(1 for _, _, f in rows if not f)
    failing = total - passing
    defect_count = sum(len(r.defects) for _, r, _ in rows)
    grouped: dict[str, dict[str, int]] = {}
    for group, kinds in REPORT_GROUPS.items():
        group_rows = [r for sc, r, _ in rows if sc.kind in kinds]
        grouped[group] = {
            "total": len(group_rows),
            "passing": sum(1 for sc, r, f in rows if sc.kind in kinds and not f),
            "failing": sum(1 for sc, r, f in rows if sc.kind in kinds and f),
            "defects": sum(len(r.defects) for sc, r, _ in rows if sc.kind in kinds),
        }
    return {
        "total": total,
        "passing": passing,
        "failing": failing,
        "defect_count": defect_count,
        "groups": grouped,
    }


def format_report(rows: list[tuple[Scenario, CognitiveResult, list[str]]] | None = None) -> str:
    if rows is None:
        rows = build_results()
    summary = summarize(rows)
    lines: list[str] = []
    lines.append("COG-EVAL-1 Cognitive Benchmark Report")
    lines.append("=" * 40)
    lines.append(
        f"Total: {summary['total']}  Pass: {summary['passing']}  "
        f"Fail: {summary['failing']}  Defects: {summary['defect_count']}"
    )
    lines.append("")
    for group in REPORT_GROUPS:
        stats = summary["groups"][group]
        lines.append(
            f"{group:24s} P={stats['passing']:<3d} F={stats['failing']:<3d} D={stats['defects']:<3d} "
            f"({stats['total']})"
        )
    lines.append("")
    lines.append("Per-scenario:")
    lines.append("-" * 40)
    for scenario, result, failures in rows:
        status = "PASS" if not failures else "FAIL"
        lines.append(
            f"[{status}] {scenario.kind.value:18s} {scenario.scenario_id:46s} "
            f"verdict={result.verdict:<10s} conf={result.confidence:.3f}"
        )
        if failures:
            for f in failures:
                lines.append(f"        - {f}")
        for d in result.defects:
            lines.append(
                f"        ! DEFECT[{d.severity.value}] {d.affected_owner}: {d.detail}"
            )
    if summary["defect_count"] == 0:
        lines.append("")
        lines.append("No defects exposed.")
    else:
        lines.append("")
        lines.append(f"{summary['defect_count']} defect(s) exposed (see DEFECTS.md):")
        for scenario, result, _ in rows:
            for d in result.defects:
                lines.append(
                    f"  - {d.scenario_id} [{d.severity.value}] {d.affected_owner}: "
                    f"{d.expected} -> {d.actual}"
                )
    lines.append("")
    return "\n".join(lines)


def defects() -> list[DefectRecord]:
    records: list[DefectRecord] = []
    for kind in ScenarioKind:
        for scenario in scenarios_for(kind):
            result = run_scenario(scenario)
            records.extend(result.defects)
    return records


if __name__ == "__main__":
    print(format_report())

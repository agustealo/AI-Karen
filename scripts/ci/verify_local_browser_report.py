"""Validate exact Playwright scenario evidence without exposing private report contents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPLORER_PREFIXES = (
    "KFILE-LIVE:",
    "KFILE-MUTATION-LOCAL:",
    "KFILE-ATTACHMENT-LOCAL:",
    "KFILE-ISOLATION-LOCAL:",
)
EXPLORER_SPEC = "file-explorer-real-acceptance.spec.ts"


def validate_report(
    report: dict, prefixes: tuple[str, ...], filename: str, *, list_only: bool = False
) -> None:
    """Require the exact scenario set; a discovery report is never a pass."""
    if not isinstance(report, dict) or report.get("errors") != []:
        raise ValueError("Missing or erroneous Playwright report")
    if not list_only:
        stats = report.get("stats")
        required = {"expected": len(prefixes), "unexpected": 0, "skipped": 0, "flaky": 0}
        if not isinstance(stats, dict) or any(
            type(stats.get(key)) is not int or stats[key] != value
            for key, value in required.items()
        ):
            raise ValueError("Browser statistics are incomplete or unsuccessful")

    observed = set()

    def collect(suites: list) -> None:
        if not isinstance(suites, list):
            raise ValueError("Invalid suite evidence")
        for suite in suites:
            if not isinstance(suite, dict):
                raise ValueError("Invalid suite evidence")
            specs = suite.get("specs", [])
            if not isinstance(specs, list):
                raise ValueError("Invalid scenario evidence")
            for spec in specs:
                if not isinstance(spec, dict):
                    raise ValueError("Invalid scenario evidence")
                title = spec.get("title")
                file = spec.get("file")
                matches = [
                    prefix for prefix in prefixes
                    if isinstance(title, str) and title.startswith(prefix)
                ]
                if (
                    len(matches) != 1 or matches[0] in observed
                    or not isinstance(file, str) or Path(file).name != filename
                ):
                    raise ValueError("Unexpected or duplicate scenario")
                tests = spec.get("tests")
                if not isinstance(tests, list) or len(tests) != 1:
                    raise ValueError("Expected one Chromium test per scenario")
                entry = tests[0]
                if (
                    not isinstance(entry, dict)
                    or entry.get("projectName") != "chromium"
                    or entry.get("expectedStatus") != "passed"
                ):
                    raise ValueError("Incorrect project or expected result")
                attempts = entry.get("results")
                if list_only:
                    if attempts != []:
                        raise ValueError("Discovery report contains execution attempts")
                elif (
                    entry.get("status") != "expected"
                    or not isinstance(attempts, list) or len(attempts) != 1
                    or not isinstance(attempts[0], dict)
                    or attempts[0].get("status") != "passed"
                    or type(attempts[0].get("retry")) is not int
                    or attempts[0]["retry"] != 0
                ):
                    raise ValueError("Scenario did not pass exactly once")
                observed.add(matches[0])
            collect(suite.get("suites", []))

    collect(report.get("suites"))
    if observed != set(prefixes):
        raise ValueError("Required scenario set is incomplete")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        validate_report(report, EXPLORER_PREFIXES, EXPLORER_SPEC, list_only=args.list_only)
    except (OSError, ValueError):
        # Reports may include private metadata and request or assertion details.
        print("FILE_EXPLORER_BROWSER_EVIDENCE_REJECTED")
        return 1
    if args.list_only:
        print("Four intended Explorer scenarios discovered; NOT_RUN")
    else:
        print("Four Explorer scenarios passed exactly once; zero skips, retries or failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

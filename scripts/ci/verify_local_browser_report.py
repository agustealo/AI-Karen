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
CONTENT_INTELLIGENCE_PREFIXES = (
    "KCONTENT-LIVE:",
    "KCONTENT-DENY-LIVE:",
    "KCONTENT-REVOKED-LIVE:",
)


def validate_report(
    report: dict, prefixes: tuple[str, ...], filename: str, *, list_only: bool = False,
    owner_text: bool = False,
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

    if owner_text and prefixes != EXPLORER_PREFIXES:
        raise ValueError("Owner text proof belongs only to Explorer")

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
                if owner_text and not list_only:
                    attachments = attempts[0].get("attachments", [])
                    if not isinstance(attachments, list) or any(
                        not isinstance(item, dict) for item in attachments
                    ):
                        raise ValueError("Invalid owner text evidence")
                    markers = [
                        item for item in attachments if item.get("name") == "karen.owner_text.v1"
                    ]
                    if matches[0] == "KFILE-ISOLATION-LOCAL:":
                        if markers != [{
                            "name": "karen.owner_text.v1",
                            "contentType": "text/plain",
                            "body": "cGFzc2Vk",
                        }]:
                            raise ValueError("Missing exact owner text proof marker")
                    elif markers:
                        raise ValueError("Owner text evidence on unrelated scenario")
                observed.add(matches[0])
            collect(suite.get("suites", []))

    collect(report.get("suites"))
    if observed != set(prefixes):
        raise ValueError("Required scenario set is incomplete")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--list-only", action="store_true")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--content-intelligence", action="store_true")
    modes.add_argument("--owner-text", action="store_true")
    args = parser.parse_args()
    prefixes = CONTENT_INTELLIGENCE_PREFIXES if args.content_intelligence else EXPLORER_PREFIXES
    name = "Content Intelligence" if args.content_intelligence else "Explorer"
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        validate_report(report, prefixes, EXPLORER_SPEC, list_only=args.list_only, owner_text=args.owner_text)
    except (OSError, ValueError):
        # Reports may include private metadata and request or assertion details.
        print("CONTENT_INTELLIGENCE_BROWSER_EVIDENCE_REJECTED" if args.content_intelligence
              else "FILE_EXPLORER_BROWSER_EVIDENCE_REJECTED")
        return 1
    if args.list_only:
        print(f"{len(prefixes)} intended {name} scenarios discovered; NOT_RUN")
    else:
        print(f"{len(prefixes)} {name} scenarios passed exactly once; zero skips, retries or failures")
        if args.owner_text:
            print("Owner text acceptance marker verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

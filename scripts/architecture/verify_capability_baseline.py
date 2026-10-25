"""Validate the evidence-backed capability baseline without executing application code.

This is a static contract guard, not evidence of runtime availability.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs/capabilities/baseline.v1.json"
CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
VALID_STATES = {
    "planned",
    "implemented_unverified",
    "partially_implemented",
    "legacy_under_audit",
    "verified",
    "consumer_ready",
    "retired",
}


def verify_baseline(path: Path = BASELINE, root: Path = ROOT) -> list[str]:
    """Return actionable contract violations; never infer runtime success."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"Cannot read capability baseline: {exc}"]

    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return ["Capability baseline must declare schema_version=1"]
    records = raw.get("capabilities")
    if not isinstance(records, list) or not records:
        return ["Capability baseline must contain a nonempty capabilities array"]

    errors: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"capabilities[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix}: expected object")
            continue
        capability_id = record.get("id")
        if not isinstance(capability_id, str) or not CAPABILITY_ID.fullmatch(capability_id):
            errors.append(f"{prefix}: invalid stable capability id")
            continue
        if capability_id in seen:
            errors.append(f"{prefix}: duplicate capability id {capability_id}")
        seen.add(capability_id)

        for key in ("intent", "owner"):
            value = record.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{capability_id}: missing {key}")

        if record.get("status") not in VALID_STATES:
            errors.append(f"{capability_id}: invalid status")

        proof = record.get("proof_required")
        if not isinstance(proof, list) or not proof or any(
            not isinstance(item, str) or not item.strip() for item in proof
        ):
            errors.append(f"{capability_id}: proof_required must be nonempty")

        evidence = record.get("evidence", [])
        if not isinstance(evidence, list):
            errors.append(f"{capability_id}: evidence must be a list")
            continue
        for relative in evidence:
            if not isinstance(relative, str) or not relative:
                errors.append(f"{capability_id}: invalid evidence path")
                continue
            candidate = root / relative
            if candidate.is_absolute() and (
                Path(relative).is_absolute() or ".." in Path(relative).parts
            ):
                errors.append(f"{capability_id}: evidence escapes repository: {relative}")
            elif not candidate.is_file():
                errors.append(f"{capability_id}: missing evidence file: {relative}")

        if record.get("status") in {"verified", "consumer_ready"}:
            errors.append(
                f"{capability_id}: live verification cannot be asserted by static baseline alone"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    violations = verify_baseline(args.baseline)
    for violation in violations:
        print(violation)
    if violations:
        return 1
    print("Capability baseline contract valid; runtime execution remains unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

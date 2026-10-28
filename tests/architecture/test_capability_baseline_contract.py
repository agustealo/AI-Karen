"""Regression contracts for the versioned capability baseline."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/architecture/verify_capability_baseline.py"
SPEC = importlib.util.spec_from_file_location("verify_capability_baseline", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_live_baseline_is_well_formed() -> None:
    assert MODULE.verify_baseline() == []


def test_duplicate_ids_and_missing_evidence_fail(tmp_path: Path) -> None:
    record = {
        "id": "chat.transport",
        "owner": "ChatRuntime",
        "intent": "Preserve capability.",
        "status": "implemented_unverified",
        "evidence": ["nonexistent.py"],
        "proof_required": ["Live test"],
    }
    fixture = tmp_path / "registry.json"
    fixture.write_text(
        json.dumps({"schema_version": 1, "capabilities": [record, record]}),
        encoding="utf-8",
    )
    result = MODULE.verify_baseline(fixture, tmp_path)
    assert any("duplicate capability" in item for item in result)
    assert any("missing evidence file" in item for item in result)


def test_static_registry_cannot_assert_consumer_readiness(tmp_path: Path) -> None:
    fixture = tmp_path / "registry.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "capabilities": [
                    {
                        "id": "chat.transport",
                        "owner": "ChatRuntime",
                        "intent": "Preserve behavior.",
                        "status": "consumer_ready",
                        "proof_required": ["Live proof"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert any(
        "live verification cannot be asserted" in item
        for item in MODULE.verify_baseline(fixture, tmp_path)
    )


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    fixture = tmp_path / "registry.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "capabilities": [
                    {
                        "id": "chat.transport",
                        "owner": "ChatRuntime",
                        "intent": "Preserve behavior.",
                        "status": "implemented_unverified",
                        "evidence": ["../../etc/passwd"],
                        "proof_required": ["Live proof"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert any("escapes repository" in item for item in MODULE.verify_baseline(fixture, tmp_path))

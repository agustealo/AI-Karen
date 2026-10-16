"""MI-11: only real structured runtime output may pass schema checks."""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_karen_engine.core.runtime.task_output_verification import (
    OutputVerificationContractError, assess_structured_output, validate_contract,
)


CONTRACT = {
    "version": "structured-output.v1",
    "schema": {
        "type": "object",
        "required": ["summary", "count"],
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            "count": {"type": "integer", "minimum": 1},
        },
        "additionalProperties": False,
    },
}


def test_verified_structured_payload_has_machine_only_evidence_and_digest():
    response = assess_structured_output(
        CONTRACT, {"summary": "Completed", "count": 2},
        runtime_status="ok", degraded=False,
    )
    assert response["status"] == "passed"
    assert response["contract_version"] == "structured-output.v1"
    assert len(response["contract_sha256"]) == 64
    assert len(response["output_sha256"]) == 64
    assert response["independently_verified"] is False
    assert response["scope"] == "runtime_structured_content_only"
    assert "summary" not in response


@pytest.mark.parametrize(("payload", "reason"), [
    ({}, "structured_output_missing"),
    ({"summary": "a", "count": 0}, "schema_mismatch"),
    ({"summary": "a", "count": True}, "schema_mismatch"),
    ({"summary": "a", "count": 3, "extra": "untrusted"}, "schema_mismatch"),
    ("the agent says the work is complete", "structured_output_missing"),
    ({"summary": "a", "count": 3}, "runtime_not_healthy"),
])
def test_machine_checks_fail_closed_without_model_trust(payload, reason):
    is_bad_runtime = reason == "runtime_not_healthy"
    result = assess_structured_output(
        CONTRACT, payload, runtime_status="degraded" if is_bad_runtime else "ok",
        degraded=is_bad_runtime,
    )
    assert result["status"] == "failed"
    assert result["reason"] == reason
    assert result["independently_verified"] is False


def test_no_contract_never_invents_machine_verification():
    assert assess_structured_output(
        {}, {"summary": "works", "count": 3},
        runtime_status="ok", degraded=False,
    ) == {"status": "not_configured", "independently_verified": False}


@pytest.mark.parametrize("contract", [
    {"version": "structured-output.v2", "schema": {"type": "object"}},
    {"version": "structured-output.v1", "schema": {"$ref": "https://example.com/evil"}},
    {"version": "structured-output.v1", "schema": {"type": "object", "properties": {"foo": {"pattern": ".*"}}}},
    {"version": "structured-output.v1", "schema": {"type": "object", "properties": {"foo": {"$ref": "#/definitions/x"}}}},
    {"version": "structured-output.v1", "schema": {"type": "object", "properties": {"foo": {"type": "wrong"}}}},
    {"version": "structured-output.v1", "schema": {"type": "object"}, "autoApprove": True},
    {"version": "structured-output.v1", "schema": {"type": "string"}},
    {"version": "structured-output.v1", "schema": {"type": "object", "properties": {str(n): {"type": "string"} for n in range(70)}}},
])
def test_unbounded_or_untrusted_schema_is_rejected_at_definition_time(contract):
    with pytest.raises(OutputVerificationContractError):
        validate_contract(contract)


def test_canonical_sql_owner_retains_machine_guard_and_never_autocompletes():
    root = Path(__file__).resolve().parents[3]
    repo = (root / "src/ai_karen_engine/persistence/repositories/automation_repository.py").read_text()
    execution = (root / "src/ai_karen_engine/services/automation/execution.py").read_text()
    schema = (root / "supabase/migrations/20261016030000_30_saved_task_structured_output_verification.sql").read_text()
    assert "verification_contract" in repo
    assert "result_receipt #>> '{machine_verification,status}' = 'passed'" in repo
    assert "automation_tasks_verified_machine_contract_check" in schema
    assert '"machine_verification": assess_structured_output(' in execution
    assert 'status="ReviewRequired" if successful else "Failed"' in execution
    assert "status=\"Success\"" not in execution

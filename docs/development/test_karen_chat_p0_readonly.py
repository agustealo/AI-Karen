"""Unit tests for the safe read-only diagnostic's pure reporting contract.

This suite does NOT make a database or model call. Real DB and authenticated
browser execution remain separate mandatory acceptance gates.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).with_name("karen_chat_p0_readonly.py")
SPEC = importlib.util.spec_from_file_location("karen_chat_p0_readonly", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_report_counts_and_data_contract() -> None:
    report = MODULE.Report()
    report.add("db", "pass", "canonical read succeeded")
    report.add("bridge", "fail", "disabled")
    report.add("durable", "warning", "not enabled")
    report.add("model", "not_tested", "requires live test")
    payload = report.to_dict()
    assert payload["contract"] == "karen_chat_p0_readonly_v1"
    assert payload["summary"] == {
        "pass": 1, "fail": 1, "warning": 1, "not_tested": 1,
    }
    assert payload["checks"][1] == {
        "id": "bridge", "status": "fail", "detail": "disabled",
    }


def test_report_does_not_accept_fabricated_status() -> None:
    with pytest.raises(ValueError, match="Invalid audit status"):
        MODULE.Report().add("x", "success_without_proof", "no")


@pytest.mark.parametrize("enabled, expected", [(True, "pass"), (False, "fail")])
def test_status_of(enabled: bool, expected: str) -> None:
    assert MODULE.status_of(enabled) == expected


def test_safe_sqlstate_from_wrapped_error() -> None:
    class DatabaseError(Exception):
        sqlstate = "42P01"

    class Wrapper(Exception):
        orig = DatabaseError("PRIVATE DB MESSAGE SHOULD NOT BE PRINTED")

    assert MODULE.safe_sqlstate(Wrapper()) == "42P01"


def test_safe_sqlstate_rejects_untrusted_error_strings() -> None:
    exc = RuntimeError("password=secret; host=private; prompt=private")
    assert MODULE.safe_sqlstate(exc) is None


def test_safe_sqlstate_rejects_malformed_codes() -> None:
    class ExceptionWithBadCode(Exception):
        sqlstate = "secret-unauthorized"

    assert MODULE.safe_sqlstate(ExceptionWithBadCode()) is None

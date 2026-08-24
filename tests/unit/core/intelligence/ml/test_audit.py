from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_karen_engine.core.intelligence.ml.audit import AuditEvent, AuditLogger


def test_audit_logger_writes_event(tmp_path):
    audit_dir = tmp_path / "audit"
    logger = AuditLogger(audit_dir=str(audit_dir))
    event = AuditEvent(
        event_id="evt-1",
        event_type="ml.model.registered",
        model_id="m1",
        model_version="v1",
        purpose="intent",
        actor="admin",
    )
    logger.log_event(event)
    files = list(audit_dir.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["event_type"] == "ml.model.registered"
    assert data["model_id"] == "m1"
    assert data["actor"] == "admin"
    assert "timestamp" in data


def test_audit_logger_helper_methods(tmp_path):
    audit_dir = tmp_path / "audit"
    logger = AuditLogger(audit_dir=str(audit_dir))
    logger.log_registered("m1", "v1", "intent", actor="admin")
    logger.log_shadow_started("m1", "v1", "intent", actor="admin")
    logger.log_shadow_completed("m1", "v1", "intent", {"f1": 0.9}, actor="admin")
    logger.log_promotion_evaluated("m1", "v1", "intent", "PROMOTION_ELIGIBLE", ["gain"], actor="admin")
    logger.log_promoted("m1", "v1", "intent", actor="admin")
    logger.log_retired("m1", "v1", "intent", actor="admin")
    logger.log_calibration_created("m1", "v1", "calib-v1", actor="admin")
    logger.log_evaluation_completed("m1", "v1", "intent", "ml-eval-v1", {"f1": 0.9}, actor="admin")
    files = list(audit_dir.glob("*.json"))
    assert len(files) == 8


def test_audit_logger_atomic_write(tmp_path):
    audit_dir = tmp_path / "audit"
    AuditLogger(audit_dir=str(audit_dir))
    event = AuditEvent(
        event_id="evt-2",
        event_type="ml.model.registered",
        model_id="m2",
        model_version="v1",
        purpose="domain",
    )
    logger = AuditLogger(audit_dir=str(audit_dir))
    logger.log_event(event)
    files = list(audit_dir.glob("*.json"))
    assert len(files) == 1
    tmp_files = list(audit_dir.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_audit_event_default_timestamp():
    event = AuditEvent(
        event_id="evt-3",
        event_type="ml.model.registered",
        model_id="m3",
        model_version="v1",
        purpose="intent",
    )
    assert event.timestamp == ""

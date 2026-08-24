from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_karen_engine.config.config_manager import get_ml_registry_dir

logger = logging.getLogger(__name__)


@dataclass
class AuditEvent:
    event_id: str
    event_type: str
    model_id: str
    model_version: str
    purpose: str
    dataset_version: str = "ml-eval-v1"
    metrics: dict[str, Any] = field(default_factory=dict)
    actor: str = "system"
    tenant_id: str = "default"
    correlation_id: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    calibration_version: str = ""


class AuditLogger:
    def __init__(self, audit_dir: str | None = None) -> None:
        self._audit_dir = Path(audit_dir or get_ml_registry_dir()).parent / "audit"
        self._audit_dir.mkdir(parents=True, exist_ok=True)

    def log_event(self, event: AuditEvent) -> None:
        event.timestamp = event.timestamp or datetime.now(timezone.utc).isoformat()
        payload = json.dumps(event.__dict__, indent=2, sort_keys=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(self._audit_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            filename = f"{event.event_id}.json"
            dest = self._audit_dir / filename
            os.replace(tmp_path, dest)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def log_registered(self, model_id: str, model_version: str, purpose: str, actor: str = "system") -> None:
        self.log_event(AuditEvent(
            event_id=f"registered-{model_id}-{datetime.now(timezone.utc).timestamp()}",
            event_type="ml.model.registered",
            model_id=model_id,
            model_version=model_version,
            purpose=purpose,
            actor=actor,
        ))

    def log_shadow_started(self, model_id: str, model_version: str, purpose: str, actor: str = "system") -> None:
        self.log_event(AuditEvent(
            event_id=f"shadow-started-{model_id}-{datetime.now(timezone.utc).timestamp()}",
            event_type="ml.model.shadow_started",
            model_id=model_id,
            model_version=model_version,
            purpose=purpose,
            actor=actor,
        ))

    def log_shadow_completed(self, model_id: str, model_version: str, purpose: str, metrics: dict[str, Any], actor: str = "system") -> None:
        self.log_event(AuditEvent(
            event_id=f"shadow-completed-{model_id}-{datetime.now(timezone.utc).timestamp()}",
            event_type="ml.model.shadow_completed",
            model_id=model_id,
            model_version=model_version,
            purpose=purpose,
            metrics=metrics,
            actor=actor,
        ))

    def log_promotion_evaluated(self, model_id: str, model_version: str, purpose: str, decision: str, reasons: list[str], actor: str = "system") -> None:
        self.log_event(AuditEvent(
            event_id=f"promotion-evaluated-{model_id}-{datetime.now(timezone.utc).timestamp()}",
            event_type="ml.model.promotion_evaluated",
            model_id=model_id,
            model_version=model_version,
            purpose=purpose,
            metrics={"decision": decision, "reasons": reasons},
            actor=actor,
        ))

    def log_promoted(self, model_id: str, model_version: str, purpose: str, actor: str = "system") -> None:
        self.log_event(AuditEvent(
            event_id=f"promoted-{model_id}-{datetime.now(timezone.utc).timestamp()}",
            event_type="ml.model.promoted",
            model_id=model_id,
            model_version=model_version,
            purpose=purpose,
            actor=actor,
        ))

    def log_retired(self, model_id: str, model_version: str, purpose: str, actor: str = "system") -> None:
        self.log_event(AuditEvent(
            event_id=f"retired-{model_id}-{datetime.now(timezone.utc).timestamp()}",
            event_type="ml.model.retired",
            model_id=model_id,
            model_version=model_version,
            purpose=purpose,
            actor=actor,
        ))

    def log_calibration_created(self, model_id: str, model_version: str, calibration_version: str, actor: str = "system") -> None:
        self.log_event(AuditEvent(
            event_id=f"calibration-created-{model_id}-{datetime.now(timezone.utc).timestamp()}",
            event_type="ml.calibration.created",
            model_id=model_id,
            model_version=model_version,
            purpose="",
            calibration_version=calibration_version,
            actor=actor,
        ))

    def log_evaluation_completed(self, model_id: str, model_version: str, purpose: str, dataset_version: str, metrics: dict[str, Any], actor: str = "system") -> None:
        self.log_event(AuditEvent(
            event_id=f"evaluation-completed-{model_id}-{datetime.now(timezone.utc).timestamp()}",
            event_type="ml.evaluation.completed",
            model_id=model_id,
            model_version=model_version,
            purpose=purpose,
            dataset_version=dataset_version,
            metrics=metrics,
            actor=actor,
        ))

"""Conservative, evidence-based lifecycle projection for durable model acquisitions.

This is a read model, not a second installer or readiness authority. Installation
completion cannot establish model verification, registry admission, or inference
health without independent runtime evidence.
"""
from __future__ import annotations

from typing import Any, Mapping


def project_model_download_lifecycle(job: Mapping[str, Any]) -> dict[str, Any]:
    """Project a durable job status without claiming unsupported runtime readiness."""
    status = str(job.get("status") or "").strip().lower()
    stages = {
        "queued": ("acquiring", "queued"),
        "running": ("acquiring", "transferring"),
        "pause_requested": ("acquiring", "pause_requested"),
        "paused": ("acquiring", "paused"),
        "promoting": ("publishing", "publishing"),
        "completed": ("acquired", "publication_completed"),
        "completed_with_warnings": ("acquired", "publication_completed_with_warnings"),
        "success": ("acquired", "publication_completed"),
        "failed": ("failed", "failed"),
        "cancelled": ("cancelled", "cancelled"),
        "canceled": ("cancelled", "cancelled"),
    }
    phase, reason = stages.get(status, ("unknown", "unrecognized_job_status"))
    return {
        "phase": phase,
        "reason_code": reason,
        "artifact_published": phase == "acquired",
        "artifact_verified": None,
        "runtime_registered": None,
        "runtime_loadable": None,
        "runtime_healthy": None,
        "selectable_in_chat": None,
        "readiness_authority": "runtime_registry_and_health_probe",
    }


__all__ = ["project_model_download_lifecycle"]

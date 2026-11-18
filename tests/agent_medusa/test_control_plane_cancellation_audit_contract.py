"""Governed Medusa cancellation audit and durable-linkage contract tests.

The audit logger here is an injected recording test double, not an assertion of
independently durable audit storage. Host-level audit readback is separate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ai_karen_engine.agent_medusa.control_plane import AgentMedusaControlPlane
from ai_karen_engine.agent_medusa.execution.run_manager import RunNotFoundError


@dataclass
class RecordingRunManager:
    result: dict[str, Any] = field(default_factory=lambda: {
        "run_id": "run-42",
        "status": "cancelling",
        "correlation_id": "corr-42",
        "distributed_control": {"supported": True},
    })
    fail_cancel: bool = False
    cancellations: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)

    async def cancel(self, *, run_id: str, tenant_id: str, audit_event_ref: str) -> dict[str, Any]:
        self.cancellations.append({
            "run_id": run_id,
            "tenant_id": tenant_id,
            "audit_event_ref": audit_event_ref,
        })
        if self.fail_cancel:
            raise RunNotFoundError(run_id)
        return dict(self.result)

    async def link_audit_event(self, *, run_id: str, tenant_id: str, audit_event_ref: str) -> None:
        self.links.append({
            "run_id": run_id,
            "tenant_id": tenant_id,
            "audit_event_ref": audit_event_ref,
        })


@dataclass
class RecordingAuditLogger:
    events: list[Any] = field(default_factory=list)

    def log_audit_event(self, event: Any) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_successful_cancellation_emits_correlated_audit_and_links_same_reference() -> None:
    manager = RecordingRunManager()
    audit = RecordingAuditLogger()
    control = AgentMedusaControlPlane(run_manager=manager, audit_logger=audit)

    result = await control.cancel_run(
        run_id="run-42",
        tenant_id="tenant-a",
        actor_user_id="operator-a",
        session_id="session-a",
    )

    assert result["status"] == "cancelling"
    assert len(manager.cancellations) == len(manager.links) == len(audit.events) == 1
    call, link, event = manager.cancellations[0], manager.links[0], audit.events[0]
    assert call["tenant_id"] == link["tenant_id"] == event.tenant_id == "tenant-a"
    assert call["run_id"] == link["run_id"] == event.metadata["run_id"] == "run-42"
    assert call["audit_event_ref"] == link["audit_event_ref"] == event.metadata["audit_event_ref"]
    assert event.user_id == "operator-a"
    assert event.session_id == "session-a"
    assert event.correlation_id == "corr-42"
    assert event.message == "medusa_run_cancel_requested"
    assert event.metadata["resulting_status"] == "cancelling"
    assert event.metadata["distributed_control_supported"] is True


@pytest.mark.asyncio
async def test_rejected_cancellation_emits_no_success_audit_or_link() -> None:
    manager = RecordingRunManager(fail_cancel=True)
    audit = RecordingAuditLogger()
    control = AgentMedusaControlPlane(run_manager=manager, audit_logger=audit)

    with pytest.raises(RunNotFoundError):
        await control.cancel_run(
            run_id="missing",
            tenant_id="tenant-a",
            actor_user_id="operator-a",
        )

    assert len(manager.cancellations) == 1
    assert manager.links == []
    assert audit.events == []


@pytest.mark.asyncio
async def test_cancellation_audit_records_missing_distributed_support_without_inventing_it() -> None:
    manager = RecordingRunManager(result={
        "run_id": "run-42", "status": "cancelling",
        "correlation_id": None, "distributed_control": None,
    })
    audit = RecordingAuditLogger()
    control = AgentMedusaControlPlane(run_manager=manager, audit_logger=audit)

    await control.cancel_run(run_id="run-42", tenant_id="tenant-a")

    event = audit.events[0]
    assert event.correlation_id == "run-42"
    assert event.metadata["distributed_control_supported"] is False
    assert event.user_id is None
    assert event.session_id is None

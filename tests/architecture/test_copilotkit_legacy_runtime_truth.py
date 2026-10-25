"""Preserve the historical Copilot contract without inventing AI execution."""

from __future__ import annotations

import asyncio

from ai_karen_engine.copilotkit.agent_ui_service import AgentUIService
from ai_karen_engine.copilotkit.models import (
    CreateDeepTaskRequest,
    SendMessageRequest,
    TaskStatus,
)


class RuntimeAdapter:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    async def execute_task(self, _task: object) -> object:
        self.calls += 1
        return self.result


def test_unconfigured_legacy_message_cannot_claim_runtime_success() -> None:
    service = AgentUIService()
    result = asyncio.run(
        service.send_message(SendMessageRequest(session_id="session-one", content="Hello"))
    )
    assert result.success is False
    assert "captured" not in result.content.lower()
    assert "successfully" not in result.content.lower()
    assert result.execution_metadata["error_code"] == "COPILOT_RUNTIME_EXECUTION_FAILED"
    assert result.task_id is not None
    assert service._tasks[result.task_id].status is TaskStatus.FAILED
    assert service._task_progress[result.task_id].status is TaskStatus.FAILED


def test_unconfigured_legacy_deep_task_is_not_falsely_queued() -> None:
    service = AgentUIService()
    result = asyncio.run(
        service.create_deep_task(
            CreateDeepTaskRequest(session_id="session-one", content="Research subject")
        )
    )
    assert result.success is False
    assert result.status is TaskStatus.FAILED
    assert not service._tasks
    assert not service._running_tasks
    assert result.execution_metadata["error_code"] == "COPILOT_RUNTIME_EXECUTION_FAILED"


def test_empty_runtime_result_rejected_before_marking_complete() -> None:
    adapter = RuntimeAdapter({"metadata": {"response_source": "runtime"}})
    service = AgentUIService(runtime_adapter=adapter)
    result = asyncio.run(
        service.send_message(SendMessageRequest(session_id="session-one", content="Hello"))
    )
    assert adapter.calls == 1
    assert result.success is False
    assert service._tasks[result.task_id].status is TaskStatus.FAILED


def test_runtime_errors_are_redacted_from_legacy_response() -> None:
    adapter = RuntimeAdapter({"success": False, "error": "api_key=should-never-leak"})
    service = AgentUIService(runtime_adapter=adapter)
    result = asyncio.run(
        service.send_message(SendMessageRequest(session_id="session-one", content="Hello"))
    )
    assert result.success is False
    assert "should-never-leak" not in result.content
    assert "should-never-leak" not in str(result.execution_metadata)


def test_success_requires_real_adapter_content_and_preserves_metadata() -> None:
    adapter = RuntimeAdapter({
        "content": "The runtime actually answered.",
        "metadata": {
            "actual_provider": "local",
            "response_source": "model",
            "degraded_mode": False,
        },
    })
    service = AgentUIService(runtime_adapter=adapter)
    result = asyncio.run(
        service.send_message(SendMessageRequest(session_id="session-one", content="Hello"))
    )
    assert result.success is True
    assert result.content == "The runtime actually answered."
    assert result.execution_metadata == adapter.result["metadata"]
    assert service._tasks[result.task_id].status is TaskStatus.COMPLETED

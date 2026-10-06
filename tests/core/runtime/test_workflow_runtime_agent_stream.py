from __future__ import annotations

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatStreamEventType
from ai_karen_engine.core.runtime.workflow_runtime import WorkflowRuntime


def test_medusa_plan_is_projected_into_canonical_agent_stream_events() -> None:
    runtime = WorkflowRuntime()
    chunks = runtime._extract_agent_activity_chunks(
        {
            "medusa_node": {
                "response_metadata": {
                    "execution_topology": "multi_agent",
                    "policy_decision_id": "policy-1",
                    "plan": {
                        "steps": [
                            {
                                "id": "step-1",
                                "description": "Research the request",
                                "agent_specialist": "researcher",
                                "status": "completed",
                                "required_tools": ["web_search"],
                                "required_plugins": [],
                            },
                            {
                                "id": "step-2",
                                "description": "Analyze evidence",
                                "agent_specialist": "analyst",
                                "status": "failed",
                                "required_tools": [],
                                "required_plugins": [],
                            },
                        ]
                    },
                }
            }
        },
        correlation_id="corr-1",
    )

    assert len(chunks) == 2
    assert all(chunk.type == ChatStreamEventType.AGENT_STEP for chunk in chunks)

    first = chunks[0]
    assert first.content == "Research the request"
    assert first.metadata["event_type"] == "agent_step_completed"
    assert first.metadata["agent_id"] == "researcher"
    assert first.metadata["required_tools"] == ["web_search"]
    assert first.metadata["policy_decision_id"] == "policy-1"

    second = chunks[1]
    assert second.metadata["event_type"] == "agent_step_failed"
    assert second.metadata["status"] == "failed"


def test_non_medusa_updates_do_not_fabricate_agent_activity() -> None:
    runtime = WorkflowRuntime()

    chunks = runtime._extract_agent_activity_chunks(
        {
            "response_synth": {
                "response_metadata": {
                    "execution_topology": "workflow",
                    "plan": {"steps": [{"id": "step-1", "status": "completed"}]},
                }
            }
        },
        correlation_id="corr-1",
    )

    assert chunks == []


def test_formatted_response_preserves_declared_rich_result_fields() -> None:
    runtime = WorkflowRuntime()
    text, metadata = runtime._extract_payload(
        {
            "formatted_response": {
                "data": {
                    "response": "Done",
                    "structured_content": {"table": {"rows": 2}},
                    "actions": [{"type": "continue", "description": "Continue"}],
                    "citations": [{"id": "c1", "url": "https://example.com"}],
                    "sources": [{"id": "s1", "url": "https://example.com/source"}],
                    "attachments": [{"id": "a1", "name": "report.pdf"}],
                    "artifacts": [{"id": "r1", "title": "Report", "type": "document"}],
                },
                "metadata": {"actual_provider": "builtin_vllm"},
            }
        }
    )

    assert text == "Done"
    assert metadata["structured_content"]["table"]["rows"] == 2
    assert metadata["actions"][0]["type"] == "continue"
    assert metadata["citations"][0]["id"] == "c1"
    assert metadata["sources"][0]["id"] == "s1"
    assert metadata["attachments"][0]["name"] == "report.pdf"
    assert metadata["artifacts"][0]["title"] == "Report"


def test_rich_result_extraction_does_not_copy_internal_graph_state() -> None:
    runtime = WorkflowRuntime()
    _, metadata = runtime._extract_payload(
        {
            "formatted_response": {
                "data": {
                    "response": "Done",
                    "artifacts": [{"id": "r1"}],
                    "internal_state": {"secret": True},
                },
                "metadata": {},
            },
            "internal_state": {"secret": True},
        }
    )

    assert metadata["artifacts"] == [{"id": "r1"}]
    assert "internal_state" not in metadata

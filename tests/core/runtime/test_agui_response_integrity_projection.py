"""Only verified, non-sensitive runtime facts may reach AG-UI presentation."""
from types import SimpleNamespace

from ai_karen_engine.core.runtime.ag_ui_event_projection import AGUIEventProjection


def _terminal(metadata):
    projection = AGUIEventProjection(thread_id="thread-1", run_id="run-1")
    projection.begin()
    return projection.project(SimpleNamespace(type="complete", content="", metadata=metadata))


def test_authorized_recall_receipt_and_truncation():
    events = _terminal({
        "cortex_intent": "memory.recall",
        "response_source": "authorized_memory_evidence",
        "output_truncated": True,
        "secret": "must-not-leak",
    })
    receipt = next(event["value"] for event in events if event.get("name") == "karen.response_integrity.v1")
    assert receipt == {
        "output_truncated": True,
        "cortex_intent": "memory.recall",
        "personal_recall_grounded": True,
        "evidence_source": "authorized_memory_evidence",
    }
    assert "must-not-leak" not in str(events)


def test_unverified_recall_does_not_claim_grounding():
    events = _terminal({"cortex_intent": "memory.recall", "response_source": "model"})
    receipt = next(event["value"] for event in events if event.get("name") == "karen.response_integrity.v1")
    assert receipt["personal_recall_grounded"] is False
    assert "evidence_source" not in receipt


def test_normal_completion_has_no_integrity_badge():
    events = _terminal({"response_source": "model", "output_truncated": False})
    assert not any(event.get("name") == "karen.response_integrity.v1" for event in events)
    assert events[-1]["type"] == "RUN_FINISHED"

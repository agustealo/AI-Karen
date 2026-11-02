"""CK-27C source contract for explicit approval review before mutation."""
from pathlib import Path

AGENTS = (
    Path(__file__).resolve().parents[2]
    / "src/ui_launchers/Karen-AI-Theme/src/components/automation/AgentsPage.tsx"
)


def test_approval_requires_confirmation_before_backend_decision() -> None:
    text = AGENTS.read_text(encoding="utf-8")
    assert "setPendingApprovalDecision({ approvalId: approval.approval_id" in text
    assert 'aria-label="Confirm approval decision"' in text
    assert "onClick={() => void decideApproval(approval.approval_id, pendingApprovalDecision.decision)}" in text
    assert "onClick={() => setPendingApprovalDecision(null)}>Back" in text
    assert 'onClick={() => void decideApproval(approval.approval_id, "approved")}' not in text
    assert 'onClick={() => void decideApproval(approval.approval_id, "rejected")}' not in text


def test_approval_rechecks_expiry_and_does_not_claim_execution() -> None:
    text = AGENTS.read_text(encoding="utf-8")
    assert "Date.parse(approval.expires_at) <= Date.now()" in text
    assert "if (decidingApprovalId !== null) return;" in text
    assert "Karen must separately revalidate authorization and execution state." in text
    assert "Karen must still revalidate and resume the original request." in text

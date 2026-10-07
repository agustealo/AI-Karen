from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime_contract.py"
EXECUTION_IDENTITY = ROOT / "src/ai_karen_engine/api_routes/chat/execution_identity.py"
APPROVALS = ROOT / "src/ai_karen_engine/services/approvals.py"


def test_chat_execution_context_never_synthesizes_default_tenant() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")

    assert 'tenant_id: str = ""' in contract
    assert 'tenant_id: str = "default"' not in contract
    assert 'str(self.tenant_id or "default")' not in contract


def test_chat_ingress_and_approval_resume_supply_authoritative_tenant() -> None:
    ingress = EXECUTION_IDENTITY.read_text(encoding="utf-8")
    approvals = APPROVALS.read_text(encoding="utf-8")

    assert 'if tenant_id.lower() == "default":' in ingress
    assert "tenant_id=tenant_id" in ingress
    assert 'tenant_id == "default"' in approvals
    assert "tenant_id=tenant_id" in approvals

"""WS-04A9E: generic approval cannot be forged into document author consent."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.approvals import (
    ApprovalScopeError,
    _require_lifecycle_scope,
)


@pytest.mark.parametrize("intent", [
    "writing_style.document_consent.issue",
    "writing_style.document_consent.revoke",
    "writing_style.document_consent.renew",
])
def test_general_approval_rejects_document_consent_intent(intent: str) -> None:
    decision = SimpleNamespace(intent=intent)
    with pytest.raises(ApprovalScopeError, match="source-scoped authenticated"):
        _require_lifecycle_scope(
            request=SimpleNamespace(),
            decision=decision,
            scope=None,
        )


def test_unrelated_general_approval_not_overblocked() -> None:
    _require_lifecycle_scope(
        request=SimpleNamespace(),
        decision=SimpleNamespace(intent="general_assist"),
        scope=None,
    )

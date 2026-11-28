"""Bounded canonical reference contract, independent of storage availability."""
from __future__ import annotations

import pytest

from ai_karen_engine.services.database.repositories.conversation_repository import (
    Message,
    build_completed_attachment_receipt,
    canonical_message_digest,
    draft_attachment_selection_digest,
    validate_draft_attachment_references,
    verify_completed_attachment_receipt,
)

SOURCE = "11111111-1111-4111-8111-111111111111"
REFERENCE = {"source_id": SOURCE, "revision": "a" * 64}


def test_accepts_empty_and_canonical_references():
    assert validate_draft_attachment_references([]) == []
    result = validate_draft_attachment_references([REFERENCE])
    assert result == [REFERENCE]
    assert result[0] is not REFERENCE


@pytest.mark.parametrize("invalid", [
    None, {}, [None], [REFERENCE, REFERENCE], [REFERENCE] * 13,
    [{"source_id": SOURCE, "revision": "invalid"}],
    [{"source_id": "not-uuid", "revision": "a" * 64}],
    [{"source_id": SOURCE, "revision": "A" * 64}],
    [{**REFERENCE, "storage_uri": "untrusted"}],
])
def test_rejects_malformed_duplicate_and_untrusted_references(invalid):
    with pytest.raises(ValueError, match="composer_attachment_invalid"):
        validate_draft_attachment_references(invalid)



def test_completed_receipt_binds_original_user_and_ordered_selection():
    other = {"source_id": "22222222-2222-4222-8222-222222222222", "revision": "b" * 64}
    refs = [REFERENCE, other]
    user = Message("user", "conversation", "tenant", "user", "question", metadata={"request_id": "request"})
    submission = "draft-v2-4-" + draft_attachment_selection_digest(refs)
    receipt = build_completed_attachment_receipt(user, submission, refs)
    assert receipt == {
        "schema_version": 1, "submission_id": submission, "user_message_id": user.id,
        "user_message_digest": canonical_message_digest(user), "references": refs,
    }
    assert verify_completed_attachment_receipt(receipt, user, submission, refs)
    for changed in (
        {**receipt, "schema_version": True},
        {**receipt, "user_message_id": "other"},
        {**receipt, "user_message_digest": "0" * 64},
        {**receipt, "references": list(reversed(refs))},
        {**receipt, "references": [REFERENCE]},
        {**receipt, "url": "untrusted"},
    ):
        assert not verify_completed_attachment_receipt(changed, user, submission, refs)
    assert not verify_completed_attachment_receipt(receipt, user, submission, list(reversed(refs)))
    assert not verify_completed_attachment_receipt(receipt, user, "draft-v1-4", refs)
    user.metadata["request_id"] = "different"
    assert not verify_completed_attachment_receipt(receipt, user, submission, refs)

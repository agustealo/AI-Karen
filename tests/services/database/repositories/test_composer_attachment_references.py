"""Bounded canonical reference contract, independent of storage availability."""
from __future__ import annotations

import pytest

from ai_karen_engine.services.database.repositories.conversation_repository import (
    validate_draft_attachment_references,
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

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime_contract.py"


def test_canonical_chat_request_metadata_defaults_to_mapping() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")

    assert (
        'metadata: Dict[str, Any] = Field(default_factory=dict, '
        'description="Additional request-specific metadata")'
    ) in contract
    assert (
        'metadata: Dict[str, Any] = Field(default_factory=list, '
        'description="Additional request-specific metadata")'
    ) not in contract


def test_collection_defaults_match_declared_container_types() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")

    assert (
        'attachments: List[Dict[str, Any]] = Field(default_factory=list'
    ) in contract
    assert (
        'actions: List[Dict[str, Any]] = Field(default_factory=list'
    ) in contract

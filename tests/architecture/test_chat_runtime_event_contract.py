from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHAT_RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py"
EVENTS = ROOT / "src/ai_karen_engine/platform/observability/contracts.py"


def test_chat_runtime_only_emits_declared_runtime_event_types() -> None:
    chat = CHAT_RUNTIME.read_text(encoding="utf-8")
    events = EVENTS.read_text(encoding="utf-8")

    emitted = set(re.findall(r"RuntimeEventType\.([A-Z0-9_]+)", chat))
    declared = set(re.findall(r"^\s+([A-Z0-9_]+)\s*=\s*\"", events, re.MULTILINE))

    missing = sorted(emitted - declared)
    assert missing == [], f"undeclared RuntimeEventType members: {missing}"


def test_learning_recording_failure_is_canonical_observability_event() -> None:
    events = EVENTS.read_text(encoding="utf-8")

    assert 'LEARNING_RECORDING_FAILED = "learning.recording.failed"' in events

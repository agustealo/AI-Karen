from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOGGER = ROOT / "src/ai_karen_engine/core/logging/logger.py"
CHAT_ROUTE = ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py"


def test_runtime_logger_exposes_structured_transport_helpers() -> None:
    source = LOGGER.read_text(encoding="utf-8")

    assert "def log_event(" in source
    assert "def log_response(" in source
    assert "def log_error(" in source
    assert 'self.info("runtime_response", extra=payload)' in source
    assert 'self.error("runtime_error", extra=payload)' in source


def test_chat_route_only_calls_logger_methods_owned_by_runtime_logger() -> None:
    logger = LOGGER.read_text(encoding="utf-8")
    chat = CHAT_ROUTE.read_text(encoding="utf-8")

    for method in ("log_event", "log_response", "log_error"):
        assert f"def {method}(" in logger
        assert f"structured_logger.{method}(" in chat

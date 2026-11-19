"""Streaming compatibility package.

Canonical chat execution does not use the retired AsyncStreamProcessor. Import
it only for explicit legacy callers. Eager loading that module pulls the
formatting metrics stack (including optional psutil) into otherwise lean
WebSocket/SSE/NDJSON route imports and can prevent HTTP startup or test
collection when the optional metrics dependency is absent.
"""

__all__ = ["AsyncStreamProcessor"]


def __getattr__(name: str):
    """Preserve only the explicit legacy import, without eager side effects."""
    if name == "AsyncStreamProcessor":
        from .stream_processor import AsyncStreamProcessor

        return AsyncStreamProcessor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

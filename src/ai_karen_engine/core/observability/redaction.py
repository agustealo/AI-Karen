"""Compatibility facade for observability redaction.

Canonical redaction implementation lives in
``ai_karen_engine.platform.observability.redaction``.

This module remains temporarily so legacy imports keep working while callers
migrate. Do not add redaction rules here.
"""

from __future__ import annotations

from ai_karen_engine.platform.observability.redaction import (
    redact_data,
    redact_text,
    redact_url,
)


class RedactionError(Exception):
    """Legacy compatibility exception retained for import stability."""


__all__ = ["RedactionError", "redact_data", "redact_text", "redact_url"]

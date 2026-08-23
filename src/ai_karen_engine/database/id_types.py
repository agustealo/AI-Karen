"""
Canonical ID types for KAREN's data layer.

All durable identifiers in the Supabase/PostgreSQL data plane are UUIDs.
This module provides type aliases, normalization helpers, and validation
to keep the contract consistent across SQL, repositories, and runtime.
"""

from __future__ import annotations

import uuid
from typing import Union

# Canonical scalar types for database identifiers.
# These are runtime-represented as UUIDs; callers may pass UUID objects
# or UUID-formatted strings, but the canonical storage type is UUID.
TenantId = uuid.UUID
UserId = uuid.UUID
ConversationId = uuid.UUID
MessageId = uuid.UUID
MemoryId = uuid.UUID
ArtifactId = uuid.UUID
ExecutionId = uuid.UUID


def coerce_id(value: Union[str, uuid.UUID]) -> uuid.UUID:
    """Normalize an identifier to a UUID.

    Accepts:
    - UUID instances (returned as-is)
    - UUID-formatted strings (parsed)
    - None-like values (raise ValueError)

    This is the single point of conversion for all ID entry paths.
    """
    if value is None:
        raise ValueError("Identifier cannot be None")
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid identifier: {value!r}") from exc


def coerce_tenant_id(value: Union[str, uuid.UUID]) -> TenantId:
    return coerce_id(value)


def coerce_user_id(value: Union[str, uuid.UUID]) -> UserId:
    """Normalize a user identifier to a UUID.

    Accepts UUID instances, UUID-formatted strings, or arbitrary user IDs.
    Non-UUID values are deterministically mapped to a UUID via uuid5 so the
    same input always yields the same UUID.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return uuid.UUID("00000000-0000-0000-0000-000000000000")
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_URL, f"ai-karen:user:{value}")


def coerce_conversation_id(value: Union[str, uuid.UUID]) -> ConversationId:
    return coerce_id(value)


def coerce_message_id(value: Union[str, uuid.UUID]) -> MessageId:
    return coerce_id(value)


def coerce_memory_id(value: Union[str, uuid.UUID]) -> MemoryId:
    return coerce_id(value)


def coerce_artifact_id(value: Union[str, uuid.UUID]) -> ArtifactId:
    return coerce_id(value)


def coerce_execution_id(value: Union[str, uuid.UUID]) -> ExecutionId:
    return coerce_id(value)


__all__ = [
    "TenantId",
    "UserId",
    "ConversationId",
    "MessageId",
    "MemoryId",
    "ArtifactId",
    "ExecutionId",
    "coerce_id",
    "coerce_tenant_id",
    "coerce_user_id",
    "coerce_conversation_id",
    "coerce_message_id",
    "coerce_memory_id",
    "coerce_artifact_id",
    "coerce_execution_id",
]

"""Durable session-security persistence models.

This module extends the canonical SQLAlchemy metadata with refresh-token
rotation history. Raw refresh tokens are never stored in this history table;
only SHA-256 digests of consumed tokens are persisted so replay can be detected
without creating a second session authority.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UUID, func

from . import Base


class AuthRefreshTokenHistory(Base):
    """Consumed refresh-token digests for replay detection."""

    __tablename__ = "auth_refresh_token_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(64), nullable=False, unique=True)
    rotated_at = Column(DateTime, nullable=False, server_default=func.now())
    replayed_at = Column(DateTime)

    __table_args__ = (
        Index("idx_auth_refresh_history_session", "session_id", "rotated_at"),
        Index("idx_auth_refresh_history_user", "user_id", "rotated_at"),
        Index("idx_auth_refresh_history_token_hash", "token_hash"),
    )

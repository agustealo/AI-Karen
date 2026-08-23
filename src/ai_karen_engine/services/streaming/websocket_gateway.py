import asyncio
import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from ai_karen_engine.core.runtime.chat_runtime_contract import CanonicalChatRequest as ChatRequest
from ai_karen_engine.utils.chat_helpers import normalize_session_id as normalize_chat_session_id
from ai_karen_engine.event_bus import get_event_bus

logger = logging.getLogger(__name__)


@dataclass
class CollaborationUser:
    """Represents a user in a collaboration session."""

    user_id: str
    username: str
    status: str = "online"
    last_seen: Optional[datetime] = None
    typing_in: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.last_seen is None:
            self.last_seen = datetime.utcnow()


@dataclass
class CollaborationSession:
    """Represents an active collaboration session."""

    session_id: str
    conversation_id: str
    participants: List[CollaborationUser]
    session_type: str = "chat"
    started_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.started_at is None:
            self.started_at = datetime.utcnow()


class WebSocketMessage:
    """Represents a message sent or received over the websocket."""

    def __init__(
        self,
        content: str,
        type_: "MessageType",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.content = content
        self.type = type_
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow()
        self.message_id = str(uuid.uuid4())


class MessageType:
    """Enumeration of websocket message types."""

    TEXT = "text"
    BINARY = "binary"
    PING = "ping"
    PONG = "pong"
    CLOSE = "close"

    # Collaboration-specific message types
    PRESENCE_UPDATE = "presence_update"
    TYPING_INDICATOR = "typing_indicator"
    COLLABORATION_INVITE = "collaboration_invite"
    COLLABORATION_JOIN = "collaboration_join"
    COLLABORATION_LEAVE = "collaboration_leave"
    COLLABORATIVE_EDIT = "collaborative_edit"
    CURSOR_POSITION = "cursor_position"
    SCREEN_SHARE_START = "screen_share_start"
    SCREEN_SHARE_END = "screen_share_end"


class PresenceManager:
    """Manages user presence indicators."""

    def __init__(self):
        self.presence_data: Dict[str, CollaborationUser] = {}
        self.event_bus = get_event_bus()

    async def update_presence(
        self,
        user_id: str,
        status: str,
        conversation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update user presence status."""
        try:
            if user_id not in self.presence_data:
                self.presence_data[user_id] = CollaborationUser(
                    user_id=user_id,
                    username=metadata.get("username", user_id) if metadata else user_id,
                    status=status,
                    metadata=metadata or {},
                )
            else:
                self.presence_data[user_id].status = status
                self.presence_data[user_id].last_seen = datetime.utcnow()
                if metadata:
                    self.presence_data[user_id].metadata.update(metadata)

            # Publish presence update event
            self.event_bus.publish_presence_update(
                user_id=user_id,
                status=status,
                conversation_id=conversation_id,
                metadata=metadata,
            )

            logger.debug(f"Updated presence for user {user_id}: {status}")

        except Exception as e:
            logger.error(f"Failed to update presence for user {user_id}: {e}")

    def get_presence(self, user_id: str) -> Optional[CollaborationUser]:
        """Get presence information for a user."""
        return self.presence_data.get(user_id)

    def get_online_users(
        self, conversation_id: Optional[str] = None
    ) -> List[CollaborationUser]:
        """Get list of online users."""
        online_users = []
        for user in self.presence_data.values():
            if user.status == "online":
                # If conversation_id is specified, we need to check if the user was updated with that conversation_id
                # Since we don't store conversation_id in the user object, we'll return all online users for now
                # In a real implementation, we'd need to track user-conversation relationships separately
                if conversation_id is None:
                    online_users.append(user)
                else:
                    # For now, include all online users when filtering by conversation
                    # This would need proper conversation tracking in a real implementation
                    online_users.append(user)
        return online_users

    async def cleanup_expired_presence(self, timeout_minutes: int = 5) -> None:
        """Clean up expired presence data."""
        try:
            cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
            expired_users = []

            for user_id, user in self.presence_data.items():
                if user.last_seen and user.last_seen < cutoff_time:
                    expired_users.append(user_id)

            for user_id in expired_users:
                await self.update_presence(user_id, "offline")

            logger.debug(f"Cleaned up {len(expired_users)} expired presence entries")

        except Exception as e:
            logger.error(f"Failed to cleanup expired presence: {e}")


class TypingManager:
    """Manages typing indicators."""

    def __init__(self):
        self.typing_data: Dict[
            str, Dict[str, Any]
        ] = {}  # conversation_id -> {user_id: typing_info}
        self.event_bus = get_event_bus()

    async def set_typing(
        self,
        user_id: str,
        conversation_id: str,
        is_typing: bool,
        expires_in_seconds: int = 5,
    ) -> None:
        """Set typing indicator for a user in a conversation."""
        try:
            if conversation_id not in self.typing_data:
                self.typing_data[conversation_id] = {}

            if is_typing:
                self.typing_data[conversation_id][user_id] = {
                    "started_at": datetime.utcnow(),
                    "expires_at": datetime.utcnow()
                    + timedelta(seconds=expires_in_seconds),
                }
            else:
                self.typing_data[conversation_id].pop(user_id, None)

            # Publish typing indicator event
            self.event_bus.publish_typing_indicator(
                user_id=user_id,
                conversation_id=conversation_id,
                is_typing=is_typing,
                expires_in_seconds=expires_in_seconds,
            )

            logger.debug(
                f"Set typing indicator for user {user_id} in conversation {conversation_id}: {is_typing}"
            )

        except Exception as e:
            logger.error(f"Failed to set typing indicator: {e}")

    def get_typing_users(self, conversation_id: str) -> List[str]:
        """Get list of users currently typing in a conversation."""
        if conversation_id not in self.typing_data:
            return []

        current_time = datetime.utcnow()
        typing_users = []

        for user_id, typing_info in self.typing_data[conversation_id].items():
            if typing_info["expires_at"] > current_time:
                typing_users.append(user_id)

        return typing_users

    async def cleanup_expired_typing(self) -> None:
        """Clean up expired typing indicators."""
        try:
            current_time = datetime.utcnow()

            for conversation_id in list(self.typing_data.keys()):
                expired_users = []

                for user_id, typing_info in self.typing_data[conversation_id].items():
                    if typing_info["expires_at"] <= current_time:
                        expired_users.append(user_id)

                for user_id in expired_users:
                    self.typing_data[conversation_id].pop(user_id, None)

                # Remove empty conversation entries
                if not self.typing_data[conversation_id]:
                    del self.typing_data[conversation_id]

            logger.debug("Cleaned up expired typing indicators")

        except Exception as e:
            logger.error(f"Failed to cleanup expired typing indicators: {e}")


class CollaborationManager:
    """Manages collaboration sessions and features."""

    def __init__(self):
        self.active_sessions: Dict[str, CollaborationSession] = {}
        self.user_sessions: Dict[str, Set[str]] = {}  # user_id -> set of session_ids
        self.event_bus = get_event_bus()

    async def create_session(
        self,
        conversation_id: str,
        initiator_user_id: str,
        session_type: str = "chat",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new collaboration session."""
        try:
            session_id = str(uuid.uuid4())

            # Create initial participant
            initiator = CollaborationUser(
                user_id=initiator_user_id,
                username=metadata.get("initiator_username", initiator_user_id)
                if metadata
                else initiator_user_id,
                status="online",
            )

            session = CollaborationSession(
                session_id=session_id,
                conversation_id=conversation_id,
                participants=[initiator],
                session_type=session_type,
                metadata=metadata or {},
            )

            self.active_sessions[session_id] = session

            # Track user sessions
            if initiator_user_id not in self.user_sessions:
                self.user_sessions[initiator_user_id] = set()
            self.user_sessions[initiator_user_id].add(session_id)

            # Publish session start event
            self.event_bus.publish_collaboration_session(
                session_id=session_id,
                action="start",
                participants=[initiator_user_id],
                conversation_id=conversation_id,
                session_type=session_type,
                metadata=metadata,
            )

            logger.info(
                f"Created collaboration session {session_id} for conversation {conversation_id}"
            )
            return session_id

        except Exception as e:
            logger.error(f"Failed to create collaboration session: {e}")
            raise

    async def join_session(
        self, session_id: str, user_id: str, username: Optional[str] = None
    ) -> bool:
        """Add a user to an existing collaboration session."""
        try:
            if session_id not in self.active_sessions:
                logger.warning(f"Attempted to join non-existent session {session_id}")
                return False

            session = self.active_sessions[session_id]

            # Check if user is already in session
            for participant in session.participants:
                if participant.user_id == user_id:
                    participant.status = "online"
                    participant.last_seen = datetime.utcnow()
                    logger.debug(f"User {user_id} rejoined session {session_id}")
                    return True

            # Add new participant
            new_participant = CollaborationUser(
                user_id=user_id, username=username or user_id, status="online"
            )
            session.participants.append(new_participant)

            # Track user sessions
            if user_id not in self.user_sessions:
                self.user_sessions[user_id] = set()
            self.user_sessions[user_id].add(session_id)

            # Publish join event
            self.event_bus.publish(
                capsule="collaboration",
                event_type="user_joined_session",
                payload={
                    "session_id": session_id,
                    "user_id": user_id,
                    "conversation_id": session.conversation_id,
                    "timestamp": time.time(),
                },
                roles=["user", "admin"],
            )

            logger.info(f"User {user_id} joined collaboration session {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to join session {session_id}: {e}")
            return False

    async def leave_session(self, session_id: str, user_id: str) -> bool:
        """Remove a user from a collaboration session."""
        try:
            if session_id not in self.active_sessions:
                return False

            session = self.active_sessions[session_id]

            # Remove participant
            session.participants = [
                p for p in session.participants if p.user_id != user_id
            ]

            # Update user sessions tracking
            if user_id in self.user_sessions:
                self.user_sessions[user_id].discard(session_id)
                if not self.user_sessions[user_id]:
                    del self.user_sessions[user_id]

            # If no participants left, end the session
            if not session.participants:
                await self.end_session(session_id)
            else:
                # Publish leave event
                self.event_bus.publish(
                    capsule="collaboration",
                    event_type="user_left_session",
                    payload={
                        "session_id": session_id,
                        "user_id": user_id,
                        "conversation_id": session.conversation_id,
                        "timestamp": time.time(),
                    },
                    roles=["user", "admin"],
                )

            logger.info(f"User {user_id} left collaboration session {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to leave session {session_id}: {e}")
            return False

    async def end_session(self, session_id: str) -> bool:
        """End a collaboration session."""
        try:
            if session_id not in self.active_sessions:
                return False

            session = self.active_sessions[session_id]

            # Remove from user sessions tracking
            for participant in session.participants:
                if participant.user_id in self.user_sessions:
                    self.user_sessions[participant.user_id].discard(session_id)
                    if not self.user_sessions[participant.user_id]:
                        del self.user_sessions[participant.user_id]

            # Publish session end event
            self.event_bus.publish_collaboration_session(
                session_id=session_id,
                action="end",
                participants=[p.user_id for p in session.participants],
                conversation_id=session.conversation_id,
                session_type=session.session_type,
            )

            # Remove session
            del self.active_sessions[session_id]

            logger.info(f"Ended collaboration session {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to end session {session_id}: {e}")
            return False

    def get_session(self, session_id: str) -> Optional[CollaborationSession]:
        """Get collaboration session by ID."""
        return self.active_sessions.get(session_id)

    def get_user_sessions(self, user_id: str) -> List[CollaborationSession]:
        """Get all active sessions for a user."""
        if user_id not in self.user_sessions:
            return []

        sessions = []
        for session_id in self.user_sessions[user_id]:
            if session_id in self.active_sessions:
                sessions.append(self.active_sessions[session_id])

        return sessions

    def get_conversation_sessions(
        self, conversation_id: str
    ) -> List[CollaborationSession]:
        """Get all active sessions for a conversation."""
        return [
            session
            for session in self.active_sessions.values()
            if session.conversation_id == conversation_id
        ]


class WebSocketGateway:
    """Enhanced WebSocket gateway with collaboration features."""

    def __init__(
        self,
        chat_orchestrator=None,
        cleanup_interval: float = 30.0,
        heartbeat_interval: float = 30.0,
    ) -> None:
        self.cleanup_interval = cleanup_interval
        self.heartbeat_interval = heartbeat_interval
        self.chat_orchestrator = chat_orchestrator

        # Collaboration managers
        self.presence_manager = PresenceManager()
        self.typing_manager = TypingManager()
        self.collaboration_manager = CollaborationManager()

        # Connection tracking
        self.active_connections: Dict[
            str, Dict[str, Any]
        ] = {}  # connection_id -> connection_info
        self.user_connections: Dict[
            str, Set[str]
        ] = {}  # user_id -> set of connection_ids
        self.conversation_connections: Dict[
            str, Set[str]
        ] = {}  # conversation_id -> set of connection_ids

        # Background tasks
        self._typing_cleanup_task: Optional[asyncio.Task] = None
        self._presence_cleanup_task: Optional[asyncio.Task] = None
        self._message_cleanup_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._collaboration_cleanup_task: Optional[asyncio.Task] = None
        self._tasks: List[asyncio.Task] = []

        # Message queue for offline users
        self.message_queue: Dict[str, List[Dict[str, Any]]] = {}

        # Event bus for collaboration events
        self.event_bus = get_event_bus()

    async def start(self) -> None:
        """Start background maintenance tasks."""
        self._typing_cleanup_task = asyncio.create_task(self._cleanup_expired_typing())
        self._presence_cleanup_task = asyncio.create_task(
            self._cleanup_expired_presence()
        )
        self._message_cleanup_task = asyncio.create_task(
            self._cleanup_expired_messages()
        )
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._collaboration_cleanup_task = asyncio.create_task(
            self._cleanup_collaboration_sessions()
        )
        self._tasks = [
            self._typing_cleanup_task,
            self._presence_cleanup_task,
            self._message_cleanup_task,
            self._heartbeat_task,
            self._collaboration_cleanup_task,
        ]

    async def _cleanup_expired_typing(self) -> None:  # pragma: no cover - loop
        """Periodically remove expired typing indicators."""
        try:
            while True:
                await asyncio.sleep(max(1.0, self.cleanup_interval / 6))
                await self.typing_manager.cleanup_expired_typing()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Failed typing cleanup loop: {e}")

    async def _cleanup_expired_presence(self) -> None:  # pragma: no cover - loop
        """Periodically mark stale presence records offline."""
        try:
            while True:
                await asyncio.sleep(self.cleanup_interval)
                await self.presence_manager.cleanup_expired_presence()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Failed presence cleanup loop: {e}")

    async def _cleanup_expired_messages(self) -> None:  # pragma: no cover - loop
        """Drop queued offline messages that have aged out."""
        try:
            while True:
                await asyncio.sleep(self.cleanup_interval)
                cutoff = datetime.utcnow() - timedelta(hours=1)
                for user_id in list(self.message_queue.keys()):
                    retained = [
                        message
                        for message in self.message_queue[user_id]
                        if datetime.fromisoformat(message.get("timestamp", datetime.utcnow().isoformat())) > cutoff
                    ]
                    if retained:
                        self.message_queue[user_id] = retained
                    else:
                        del self.message_queue[user_id]
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Failed message cleanup loop: {e}")

    async def _heartbeat_loop(self) -> None:  # pragma: no cover - loop
        """Refresh connection heartbeats for active websocket clients."""
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval)
                now = datetime.utcnow().isoformat()
                for connection in self.active_connections.values():
                    connection["last_heartbeat"] = now
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Failed heartbeat loop: {e}")

    async def _cleanup_collaboration_sessions(self) -> None:  # pragma: no cover - loop
        """Clean up inactive collaboration sessions."""
        try:
            while True:
                await asyncio.sleep(self.cleanup_interval * 2)  # Run less frequently

                current_time = datetime.utcnow()
                inactive_sessions = []

                for (
                    session_id,
                    session,
                ) in self.collaboration_manager.active_sessions.items():
                    # Check if session has been inactive for more than 30 minutes
                    if session.started_at and (
                        current_time - session.started_at
                    ) > timedelta(minutes=30):
                        # Check if any participants are still online
                        has_online_participants = False
                        for participant in session.participants:
                            presence = self.presence_manager.get_presence(
                                participant.user_id
                            )
                            if presence and presence.status == "online":
                                has_online_participants = True
                                break

                        if not has_online_participants:
                            inactive_sessions.append(session_id)

                # End inactive sessions
                for session_id in inactive_sessions:
                    await self.collaboration_manager.end_session(session_id)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Failed collaboration session cleanup: {e}")

    async def stop(self) -> None:
        """Stop background maintenance tasks."""
        for task in self._tasks:
            if task and not task.done():
                task.cancel()
        for task in self._tasks:
            if task:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._tasks = []

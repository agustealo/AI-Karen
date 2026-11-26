"""
Legacy destructive event queue with tenant and role isolation.
Enhanced with hook-specific event types and routing.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import threading
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Deque, Dict, List, Optional, Union, Callable

from ai_karen_engine.config.config_manager import config_manager

# Optional Redis dependency
try:
    import redis  # type: ignore
except ImportError:
    redis = None

# Default configuration
REDIS_URL = config_manager.get_config_value("redis", "url", default=os.getenv("REDIS_URL"))
EVENT_LIST_KEY = config_manager.get_config_value("event_bus", "key", default="kari:events")
ALLOWED_PUBLISH_ROLES = set(config_manager.get_config_value("event_bus", "allowed_roles", default=["admin", "user"]))

logger = logging.getLogger(__name__)


class EventBusUnavailable(RuntimeError):
    """The configured event queue cannot safely complete an operation."""


@dataclass
class Event:
    id: str
    capsule: str
    event_type: str
    payload: Dict[str, Any]
    risk: float
    roles: List[str]
    tenant_id: Optional[str] = None

class EventBus:
    """Legacy role-scoped work queue, not a private-user broadcast transport."""

    def __init__(self, *, use_redis: Optional[bool] = None) -> None:
        self._queue: Deque[Event] = collections.deque()
        self._queue_lock = threading.Lock()
        self._list_key = EVENT_LIST_KEY
        self._redis: Optional["redis.Redis"] = None
        self._hook_handlers: Dict[str, List[Callable]] = collections.defaultdict(list)
        self._hook_enabled = True
        
        # Collaboration-specific event tracking
        self._presence_events: Dict[str, Dict[str, Any]] = {}
        self._typing_events: Dict[str, Dict[str, Any]] = {}
        self._collaboration_sessions: Dict[str, Dict[str, Any]] = {}

        use_redis = bool(REDIS_URL) if use_redis is None else use_redis
        if use_redis:
            if redis is None or not REDIS_URL:
                raise EventBusUnavailable("Configured Redis event queue is unavailable")
            try:
                self._redis = redis.from_url(REDIS_URL)
            except Exception:
                raise EventBusUnavailable("Configured Redis event queue is unavailable") from None

    def publish(
        self,
        capsule: str,
        event_type: str,
        payload: Dict[str, Any],
        risk: float = 0.0,
        roles: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
    ) -> str:
        if (
            not isinstance(roles, list)
            or not all(isinstance(role, str) and role.strip() for role in roles)
            or not ALLOWED_PUBLISH_ROLES.intersection(roles)
        ):
            raise PermissionError("Publish denied: insufficient roles")
        if tenant_id is not None and (
            not isinstance(tenant_id, str) or not tenant_id.strip()
            or tenant_id != tenant_id.strip()
        ):
            raise ValueError("Invalid event tenant scope")

        event = Event(str(uuid.uuid4()), capsule, event_type, deepcopy(payload), risk, list(roles), tenant_id)
        if self._redis is not None:
            try:
                self._redis.rpush(self._list_key, json.dumps(asdict(event)))
            except Exception:
                logger.warning("event_bus.publish_unavailable")
                raise EventBusUnavailable("Event publication unavailable") from None
        else:
            with self._queue_lock:
                self._queue.append(deepcopy(event))

        # Hooks are not a durable delivery receipt; invoke only after enqueue.
        if self._hook_enabled:
            self._trigger_hook_handlers(event)
        return event.id

    def consume(
        self,
        roles: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[Event]:
        """Remove only matching events. Unattributed events remain internal."""
        if (
            not isinstance(tenant_id, str) or not tenant_id.strip()
            or tenant_id != tenant_id.strip()
            or not isinstance(roles, list) or not roles
            or not all(isinstance(role, str) and role.strip() for role in roles)
        ):
            raise PermissionError("Event consumption requires tenant and role scope")
        allowed_roles = set(roles)

        def allowed(event: Event) -> bool:
            return (
                event.tenant_id == tenant_id
                and isinstance(event.roles, list)
                and all(isinstance(role, str) for role in event.roles)
                and bool(allowed_roles.intersection(event.roles))
            )

        if self._redis is not None:
            return self._consume_redis(allowed)

        with self._queue_lock:
            selected: List[Event] = []
            remaining: Deque[Event] = collections.deque()
            for event in self._queue:
                (selected if allowed(event) else remaining).append(event)
            self._queue = remaining
            return selected

    def _consume_redis(self, allowed: Callable[[Event], bool]) -> List[Event]:
        """Atomically select/remove matching entries without deleting the queue.

        WATCH protects the snapshot from concurrent producers and consumers.
        Malformed and unmatched entries are left intact for their owners or
        maintenance; no decoded payload or raw exception is logged.
        """
        try:
            with self._redis.pipeline() as pipe:
                pipe.watch(self._list_key)
                selected: List[Event] = []
                selected_raw = []
                for item in pipe.lrange(self._list_key, 0, -1):
                    try:
                        event = Event(**json.loads(item))
                    except (TypeError, ValueError, UnicodeError):
                        continue
                    if allowed(event):
                        selected.append(event)
                        selected_raw.append(item)
                if not selected:
                    return []
                pipe.multi()
                for item in selected_raw:
                    pipe.lrem(self._list_key, 1, item)
                removed = pipe.execute()
                if removed != [1] * len(selected):
                    raise EventBusUnavailable("Event queue removal was not confirmed")
                return selected
        except EventBusUnavailable:
            raise
        except Exception:
            # redis-py may raise WatchError both on an aborted transaction and
            # when EXEC committed but its reply was lost. Never retry either
            # automatically: the original batch may already be gone.
            logger.warning("event_bus.consume_unavailable")
            raise EventBusUnavailable("Event consumption unavailable") from None

    def register_hook_handler(self, event_type: str, handler: Callable[[Event], None]) -> None:
        """Register a hook handler for specific event types."""
        self._hook_handlers[event_type].append(handler)
    
    def unregister_hook_handler(self, event_type: str, handler: Callable[[Event], None]) -> bool:
        """Unregister a hook handler."""
        if event_type in self._hook_handlers:
            try:
                self._hook_handlers[event_type].remove(handler)
                return True
            except ValueError:
                pass
        return False
    
    def enable_hooks(self) -> None:
        """Enable hook processing."""
        self._hook_enabled = True
    
    def disable_hooks(self) -> None:
        """Disable hook processing."""
        self._hook_enabled = False
    
    def _trigger_hook_handlers(self, event: Event) -> None:
        """Trigger registered hook handlers for an event."""
        if not self._hook_enabled:
            return
        
        # Handle collaboration-specific events
        self._handle_collaboration_events(event)
        
        # Trigger handlers for specific event type
        event_key = f"{event.capsule}.{event.event_type}"
        for handler in self._hook_handlers.get(event_key, []):
            try:
                handler(event)
            except Exception:
                # Silently ignore hook handler errors to prevent disrupting event flow
                pass
        
        # Trigger handlers for wildcard patterns
        for handler in self._hook_handlers.get("*", []):
            try:
                handler(event)
            except Exception:
                pass
    
    def _handle_collaboration_events(self, event: Event) -> None:
        """Handle collaboration-specific events for presence and typing indicators."""
        try:
            if event.event_type == "user_presence_update":
                user_id = event.payload.get("user_id")
                if user_id:
                    self._presence_events[user_id] = {
                        "status": event.payload.get("status", "online"),
                        "last_seen": event.payload.get("timestamp"),
                        "conversation_id": event.payload.get("conversation_id"),
                        "metadata": event.payload.get("metadata", {})
                    }
            
            elif event.event_type == "typing_indicator":
                user_id = event.payload.get("user_id")
                conversation_id = event.payload.get("conversation_id")
                if user_id and conversation_id:
                    key = f"{conversation_id}:{user_id}"
                    if event.payload.get("is_typing", False):
                        self._typing_events[key] = {
                            "user_id": user_id,
                            "conversation_id": conversation_id,
                            "started_at": event.payload.get("timestamp"),
                            "expires_at": event.payload.get("expires_at")
                        }
                    else:
                        self._typing_events.pop(key, None)
            
            elif event.event_type == "collaboration_session_start":
                session_id = event.payload.get("session_id")
                if session_id:
                    self._collaboration_sessions[session_id] = {
                        "participants": event.payload.get("participants", []),
                        "conversation_id": event.payload.get("conversation_id"),
                        "started_at": event.payload.get("timestamp"),
                        "type": event.payload.get("session_type", "chat"),
                        "metadata": event.payload.get("metadata", {})
                    }
            
            elif event.event_type == "collaboration_session_end":
                session_id = event.payload.get("session_id")
                if session_id:
                    self._collaboration_sessions.pop(session_id, None)
                    
        except Exception:
            # Silently ignore collaboration event handling errors
            pass
    
    def get_user_presence(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get current presence status for a user."""
        return self._presence_events.get(user_id)
    
    def get_online_users(self, conversation_id: Optional[str] = None) -> List[str]:
        """Get list of online users, optionally filtered by conversation."""
        online_users = []
        for user_id, presence in self._presence_events.items():
            if presence.get("status") == "online":
                if not conversation_id or presence.get("conversation_id") == conversation_id:
                    online_users.append(user_id)
        return online_users
    
    def get_typing_users(self, conversation_id: str) -> List[str]:
        """Get list of users currently typing in a conversation."""
        typing_users = []
        for key, typing_info in self._typing_events.items():
            if typing_info.get("conversation_id") == conversation_id:
                typing_users.append(typing_info.get("user_id"))
        return typing_users
    
    def get_collaboration_sessions(self, conversation_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get active collaboration sessions, optionally filtered by conversation."""
        sessions = []
        for session_id, session_info in self._collaboration_sessions.items():
            if not conversation_id or session_info.get("conversation_id") == conversation_id:
                sessions.append({
                    "session_id": session_id,
                    **session_info
                })
        return sessions
    
    def publish_presence_update(
        self,
        user_id: str,
        status: str,
        conversation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        roles: Optional[List[str]] = None
    ) -> str:
        """Publish a user presence update event."""
        import time
        return self.publish(
            capsule="collaboration",
            event_type="user_presence_update",
            payload={
                "user_id": user_id,
                "status": status,
                "conversation_id": conversation_id,
                "timestamp": time.time(),
                "metadata": metadata or {}
            },
            roles=roles or ["user", "admin"]
        )
    
    def publish_typing_indicator(
        self,
        user_id: str,
        conversation_id: str,
        is_typing: bool,
        expires_in_seconds: int = 5,
        roles: Optional[List[str]] = None
    ) -> str:
        """Publish a typing indicator event."""
        import time
        current_time = time.time()
        return self.publish(
            capsule="collaboration",
            event_type="typing_indicator",
            payload={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "is_typing": is_typing,
                "timestamp": current_time,
                "expires_at": current_time + expires_in_seconds if is_typing else None
            },
            roles=roles or ["user", "admin"]
        )
    
    def publish_collaboration_session(
        self,
        session_id: str,
        action: str,  # "start" or "end"
        participants: List[str],
        conversation_id: str,
        session_type: str = "chat",
        metadata: Optional[Dict[str, Any]] = None,
        roles: Optional[List[str]] = None
    ) -> str:
        """Publish a collaboration session event."""
        import time
        return self.publish(
            capsule="collaboration",
            event_type=f"collaboration_session_{action}",
            payload={
                "session_id": session_id,
                "participants": participants,
                "conversation_id": conversation_id,
                "session_type": session_type,
                "timestamp": time.time(),
                "metadata": metadata or {}
            },
            roles=roles or ["user", "admin"]
        )

class RedisEventBus(EventBus):
    """Explicit Redis-only adapter reusing the canonical queue operations."""

    def __init__(
        self,
        redis_client: Optional["redis.Redis"] = None,
        list_key: Optional[str] = None,
    ) -> None:
        super().__init__(use_redis=False)
        if redis_client is not None:
            self._redis = redis_client
        elif redis is None:
            raise EventBusUnavailable("Redis event queue dependency unavailable")
        else:
            try:
                self._redis = redis.from_url(REDIS_URL) if REDIS_URL else redis.Redis()
            except Exception:
                raise EventBusUnavailable("Configured Redis event queue is unavailable") from None
        self._list_key = list_key or EVENT_LIST_KEY


# Singleton accessor
_global_bus: Union[EventBus, RedisEventBus, None] = None

def get_event_bus() -> Union[EventBus, RedisEventBus]:
    """Return a singleton EventBus, preferring Redis if configured."""
    global _global_bus
    if _global_bus is not None:
        return _global_bus

    backend = config_manager.get_config_value("event_bus", "backend", default="memory").lower()
    if backend == "redis":
        _global_bus = RedisEventBus()
    else:
        # Preserve the existing URL-driven selection for legacy configurations.
        _global_bus = EventBus()

    return _global_bus

__all__ = ["Event", "EventBus", "EventBusUnavailable", "RedisEventBus", "get_event_bus"]

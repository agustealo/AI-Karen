"""
Async Stream Processor with Non-Blocking Operations

This module provides efficient streaming response processing with:
- Fully async/await patterns for all I/O operations
- Proper timeout handling and connection pooling
- Thread-safe shared state management
- Backpressure handling and flow control
- Comprehensive error handling and recovery
"""

import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional, Any, AsyncGenerator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
import weakref

from ai_karen_engine.config.config_manager import get_config_manager
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.observability.metrics import get_metrics_manager
from ai_karen_engine.services.formatting.pretty_output_layer import (
    PrettyOutputLayer,
)
from ai_karen_engine.services.response_formatting.response_formatting_models import (
    ResponseContext,
    DisplayContext,
    AccessibilityLevel,
)
from ai_karen_engine.services.formatting.ResponseFormattingClass.Specialized.Integration import (
    get_specialized_integration,
)
from ai_karen_engine.services.formatting.response_policy_enforcer import ResponsePolicyEnforcer

logger = get_logger(__name__)


class StreamStatus(Enum):
    """Stream processing status"""

    INITIALIZING = "initializing"
    ACTIVE = "active"
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class StreamChunk:
    """Stream chunk data structure"""

    chunk_id: int
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    finished: bool = False
    event_type: str = "content"  # content, status, agent_step, error, complete


@dataclass
class StreamSession:
    """Stream session tracking"""

    session_id: str
    user_id: str
    response_id: str
    status: StreamStatus
    created_at: datetime
    updated_at: datetime
    chunks_sent: int = 0
    bytes_sent: int = 0
    error_count: int = 0
    last_activity: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AsyncStreamProcessor:
    """
    Async stream processor with non-blocking operations and proper resource management
    """

    def __init__(
        self,
        max_concurrent_streams: int = 100,
        chunk_timeout: int = 30,
        max_chunk_size: int = 8192,
        backpressure_threshold: int = 10,
    ):
        self.max_concurrent_streams = max_concurrent_streams
        self.chunk_timeout = chunk_timeout
        self.max_chunk_size = max_chunk_size
        self.backpressure_threshold = backpressure_threshold

        # Thread-safe session storage
        self._sessions: Dict[str, StreamSession] = {}
        self._session_lock = asyncio.Lock()

        # Connection pooling
        self._connection_pool = None
        self._pool_lock = asyncio.Lock()

        # Rate limiting per user
        self._user_rates: Dict[str, List[datetime]] = {}
        self._rate_lock = asyncio.Lock()

        # Configuration and logging
        self.config_manager = get_config_manager()
        self.structured_logger = get_structured_logger()
        self.metrics_manager = get_metrics_manager()
        self.formatting_engine = ResponseFormattingEngine()
        self.rich_formatting_engine = get_specialized_integration()
        self.response_policy_enforcer = ResponsePolicyEnforcer()

        # Background cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        logger.info("AsyncStreamProcessor initialized")

    async def initialize(self):
        """Initialize the stream processor"""
        async with self._session_lock:
            if self._running:
                return

            self._running = True

            # Initialize connection pool
            await self._init_connection_pool()

            # Start cleanup task
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

            logger.info("AsyncStreamProcessor initialized successfully")

    async def _init_connection_pool(self):
        """Initialize connection pool for non-blocking I/O"""
        try:
            # This would be implemented based on your specific needs
            # For example, database connection pool, HTTP client pool, etc.
            self._connection_pool = {
                "initialized": True,
                "created_at": datetime.utcnow(),
            }
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise

    async def create_stream_session(
        self, user_id: str, response_id: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a new streaming session"""
        session_id = str(uuid.uuid4())

        async with self._session_lock:
            # Check concurrent stream limit
            active_streams = sum(
                1
                for session in self._sessions.values()
                if session.status in [StreamStatus.ACTIVE, StreamStatus.INITIALIZING]
            )

            if active_streams >= self.max_concurrent_streams:
                raise Exception(
                    f"Maximum concurrent streams ({self.max_concurrent_streams}) reached"
                )

            # Check user rate limit
            await self._check_user_rate_limit(user_id)

            # Create session
            session = StreamSession(
                session_id=session_id,
                user_id=user_id,
                response_id=response_id,
                status=StreamStatus.INITIALIZING,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                metadata=metadata or {},
            )

            self._sessions[session_id] = session

            # Record metrics
            self.metrics_manager.register_counter(
                "stream_sessions_created_total", ["user_type"]
            ).labels(user_type="user").inc()

            self.structured_logger.log_event(
                event="stream_session_created",
                user_id=user_id,
                details={
                    "session_id": session_id,
                    "response_id": response_id,
                    "active_streams": active_streams + 1,
                },
            )

            return session_id

    async def _check_user_rate_limit(self, user_id: str):
        """Check if user exceeds rate limits"""
        async with self._rate_lock:
            now = datetime.utcnow()

            # Clean old entries (older than 1 minute)
            cutoff = now - timedelta(minutes=1)
            if user_id in self._user_rates:
                self._user_rates[user_id] = [
                    timestamp
                    for timestamp in self._user_rates[user_id]
                    if timestamp > cutoff
                ]
            else:
                self._user_rates[user_id] = []

            # Check rate limit (e.g., max 10 streams per minute)
            if len(self._user_rates[user_id]) >= 10:
                raise Exception(f"User rate limit exceeded for {user_id}")

            # Record this stream
            self._user_rates[user_id].append(now)

    async def process_streaming_response(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        session_id: str,
        user_id: str,
        response_id: str,
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Process streaming response with enhanced timeout enforcement and fallback handling.

        This method ensures:
        - First token timeout enforcement
        - Chunk inactivity timeout
        - Provider cancellation on stall
        - Guaranteed terminal event emission
        - Fallback conversion handling
        """
        try:
            # Update session status
            await self._update_session_status(session_id, StreamStatus.ACTIVE)
            session = await self._get_session(session_id)
            session_metadata = dict((session.metadata if session else {}) or {})

            # Initialize timeout tracking
            first_token_timeout = asyncio.create_task(
                asyncio.sleep(getattr(self.config_manager, "first_token_timeout", 15))
            )
            last_chunk_time = datetime.utcnow()
            chunk_timeout = asyncio.create_task(
                asyncio.sleep(getattr(self.config_manager, "chunk_timeout", 30))
            )

            # Simulate model response generation (non-blocking)
            response_generator = self._generate_response_stream(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            chunk_id = 0
            bytes_sent = 0
            full_response = ""
            first_token_sent = False
            stream_failed = False

            async for chunk_data in response_generator:
                # Check for cancellation
                session = await self._get_session(session_id)
                if not session or session.status == StreamStatus.CANCELLED:
                    break

                # Check first token timeout
                if not first_token_sent and chunk_data.strip():
                    first_token_timeout.cancel()
                    first_token_sent = True
                    self.metrics_manager.register_histogram(
                        "stream_first_token_latency_seconds"
                    ).observe((datetime.utcnow() - session.created_at).total_seconds())

                # Check chunk timeout
                current_time = datetime.utcnow()
                if (current_time - last_chunk_time).total_seconds() > getattr(
                    self.config_manager, "chunk_timeout", 30
                ):
                    chunk_timeout.cancel()
                    await self._handle_chunk_timeout(session_id, user_id)
                    break

                # Create stream chunk
                chunk = StreamChunk(
                    chunk_id=chunk_id,
                    content=chunk_data,
                    metadata={
                        "model": model,
                        "session_id": session_id,
                        "response_id": response_id,
                        "first_token": not first_token_sent,
                        "chunk_timestamp": current_time.isoformat(),
                    },
                )

                # Send chunk with enhanced timeout handling
                try:
                    await asyncio.wait_for(
                        self._send_chunk(chunk), timeout=self.chunk_timeout
                    )
                except asyncio.TimeoutError:
                    await self._handle_chunk_timeout(session_id, user_id)
                    break

                full_response += chunk_data
                yield chunk

                # Update tracking
                chunk_id += 1
                bytes_sent += len(chunk_data.encode("utf-8"))
                last_chunk_time = current_time
                first_token_sent = True

                # Reset chunk timeout
                chunk_timeout.cancel()
                chunk_timeout = asyncio.create_task(
                    asyncio.sleep(getattr(self.config_manager, "chunk_timeout", 30))
                )

                await self._update_session_progress(
                    session_id, chunks_sent=chunk_id, bytes_sent=bytes_sent
                )

                # Check backpressure
                if await self._check_backpressure(session_id):
                    await asyncio.sleep(0.1)  # Brief pause to reduce pressure

            # Ensure terminal event is always emitted
            try:
                # Cancel timeout tasks
                first_token_timeout.cancel()
                chunk_timeout.cancel()

                # Check if stream completed successfully
                if stream_failed or not full_response.strip():
                    # Generate fallback response
                    fallback_chunk = await self._generate_fallback_chunk(
                        session_id, user_id, "stream_incomplete"
                    )
                    yield fallback_chunk
                else:
                    # Format and complete response
                    formatted_chunk = await self._format_completion_chunk(
                        full_response, session_metadata, session_id, response_id, model
                    )
                    yield formatted_chunk

                # Mark session as completed
                await self._update_session_status(session_id, StreamStatus.COMPLETED)

                # Record completion metrics
                if session:
                    processing_time = (
                        datetime.utcnow() - session.created_at
                    ).total_seconds()
                    self.metrics_manager.register_histogram(
                        "stream_session_duration_seconds", ["status"]
                    ).labels(status="completed").observe(processing_time)

            except Exception as e:
                # Ensure terminal event even on error
                error_chunk = StreamChunk(
                    chunk_id=chunk_id,
                    content="",
                    metadata={
                        "event": "error",
                        "error": str(e),
                        "session_id": session_id,
                        "response_id": response_id,
                    },
                    finished=True,
                    event_type="error",
                )
                yield error_chunk
                await self._update_session_status(session_id, StreamStatus.ERROR)

        except Exception as e:
            await self._update_session_status(session_id, StreamStatus.ERROR)
            await self._increment_session_errors(session_id)

            self.structured_logger.log_error(
                error=str(e),
                user_id=user_id,
                context="stream_processing",
                details={"session_id": session_id, "response_id": response_id},
            )

            # Record error metrics
            self.metrics_manager.register_counter(
                "stream_session_errors_total", ["error_type"]
            ).labels(error_type=type(e).__name__).inc()

            # Generate error terminal event
            error_chunk = StreamChunk(
                chunk_id=0,
                content="",
                metadata={
                    "event": "error",
                    "error": str(e),
                    "session_id": session_id,
                    "response_id": response_id,
                },
                finished=True,
                event_type="error",
            )
            yield error_chunk

            formatted_content = full_response
            completion_metadata: Dict[str, Any] = {
                "model": model,
                "session_id": session_id,
                "response_id": response_id,
                "formatted": False,
            }
            if full_response.strip():
                user_prompt = ""
                if messages:
                    last_message = messages[-1]
                    if isinstance(last_message, dict):
                        user_prompt = str(last_message.get("content") or "").strip()

                policy_result = await self.response_policy_enforcer.enforce(
                    user_prompt=user_prompt,
                    content=full_response,
                    regenerate=None,
                )
                full_response = policy_result.content

                display_context_value = str(
                    session_metadata.get("display_context", "desktop")
                ).strip()
                accessibility_value = str(
                    session_metadata.get("accessibility_level", "basic")
                ).strip()
                language = str(session_metadata.get("language", "en")).strip()
                technical_level = str(
                    session_metadata.get("technical_level", "intermediate")
                ).strip()

                try:
                    display_context = DisplayContext(display_context_value)
                except ValueError:
                    display_context = DisplayContext.DESKTOP
                try:
                    accessibility_level = AccessibilityLevel(accessibility_value)
                except ValueError:
                    accessibility_level = AccessibilityLevel.BASIC

                formatting_context = FormattingContext(
                    display_context=display_context,
                    accessibility_level=accessibility_level,
                    user_preferences=session_metadata,
                    content_length=len(full_response),
                    technical_level=technical_level or "intermediate",
                    language=language or "en",
                )

                # Use rich engine first if available
                rich_engine = getattr(self, "rich_formatting_engine", None)
                rich_metadata = {}
                formatted_intermediate = full_response
                from ..formatting.ResponseFormattingClass.Enums import FormatType

                rich_specialized = False
                if rich_engine:
                    try:
                        rich_formatted = await rich_engine.format_response(
                            user_query=user_prompt, response_content=full_response
                        )

                        if rich_formatted.format_type != FormatType.STANDARD_MARKDOWN:
                            formatted_content = rich_formatted.content
                            completion_metadata.update(
                                {
                                    "render_type": rich_formatted.format_type.value,
                                    "formatted": True,
                                    "rich_metadata": rich_formatted.metadata,
                                    "formatting": {
                                        "format_type": rich_formatted.format_type.value,
                                        "sections": [],
                                        "navigation_aids": [],
                                        "accessibility_features": {},
                                        "estimated_reading_time": 0,
                                        "formatter_metadata": dict(
                                            rich_formatted.metadata or {}
                                        ),
                                    },
                                    "response_policy": dict(
                                        policy_result.metadata or {}
                                    ),
                                }
                            )
                            rich_specialized = True
                        else:
                            formatted_intermediate = rich_formatted.content
                            rich_metadata = rich_formatted.metadata
                    except Exception as e:
                        logger.warning(f"Rich formatting engine failed in stream: {e}")

                if not rich_specialized:
                    formatted_response = await self.formatting_engine.format_response(
                        content=formatted_intermediate,
                        context=formatting_context,
                    )
                    formatted_content = formatted_response.content
                    completion_metadata.update(
                        {
                            "render_type": formatted_response.format_type.value,
                            "formatted": True,
                            "rich_metadata": rich_metadata,
                            "formatting": {
                                "format_type": formatted_response.format_type.value,
                                "sections": [
                                    section.model_dump()
                                    if hasattr(section, "model_dump")
                                    else section.dict()
                                    for section in formatted_response.sections
                                ],
                                "navigation_aids": [
                                    nav.model_dump()
                                    if hasattr(nav, "model_dump")
                                    else nav.dict()
                                    for nav in formatted_response.navigation_aids
                                ],
                                "accessibility_features": dict(
                                    formatted_response.accessibility_features or {}
                                ),
                                "estimated_reading_time": formatted_response.estimated_reading_time,
                                "formatter_metadata": dict(
                                    formatted_response.metadata or {}
                                ),
                            },
                            "response_policy": dict(policy_result.metadata or {}),
                        }
                    )

            yield StreamChunk(
                chunk_id=chunk_id,
                content=formatted_content,
                metadata=completion_metadata,
                finished=True,
            )

            # Mark session as completed
            await self._update_session_status(session_id, StreamStatus.COMPLETED)

            # Record metrics
            current_session = await self._get_session(session_id)
            session_created_at = (
                current_session.created_at if current_session else datetime.utcnow()
            )
            processing_time = (datetime.utcnow() - session_created_at).total_seconds()
            self.metrics_manager.register_histogram(
                "stream_session_duration_seconds", ["status"]
            ).labels(status="completed").observe(processing_time)

            self.metrics_manager.register_counter("stream_chunks_sent_total").inc(
                chunk_id
            )

        except Exception as e:
            await self._update_session_status(session_id, StreamStatus.ERROR)
            await self._increment_session_errors(session_id)

            self.structured_logger.log_error(
                error=str(e),
                user_id=user_id,
                context="stream_processing",
                details={"session_id": session_id, "response_id": response_id},
            )

            # Record error metrics
            self.metrics_manager.register_counter(
                "stream_session_errors_total", ["error_type"]
            ).labels(error_type=type(e).__name__).inc()

    async def _generate_response_stream(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> AsyncGenerator[str, None]:
        """Generate response stream using non-blocking operations"""
        # This would integrate with your actual model inference
        # For demonstration, we'll simulate streaming

        full_response = (
            "This is a simulated streaming response. " * 20
        )  # Make it longer

        words = full_response.split()
        for i, word in enumerate(words):
            # Simulate processing delay (non-blocking)
            await asyncio.sleep(0.05)  # 50ms per word

            yield word + " "

            # Check for max tokens
            if max_tokens and i >= max_tokens:
                break

    async def _send_chunk(self, chunk: StreamChunk):
        """Send chunk using non-blocking I/O"""
        try:
            # This would use your actual transport mechanism
            # For demonstration, we'll just simulate the send

            # Simulate network I/O (non-blocking)
            await asyncio.sleep(0.01)  # Simulate network latency

            # In real implementation, this would be:
            # await websocket.send_text(chunk.content)
            # await response.write(chunk.content)
            # etc.

            return True

        except Exception as e:
            logger.error(f"Error sending chunk {chunk.chunk_id}: {e}")
            raise

    async def _check_backpressure(self, session_id: str) -> bool:
        """Check if stream is experiencing backpressure"""
        try:
            session = await self._get_session(session_id)
            if not session:
                return False

            # Simple backpressure detection based on error rate
            if session.error_count > 5:
                return True

            # Check if chunks are being processed too slowly
            time_since_last_activity = (
                datetime.utcnow() - session.last_activity
            ).total_seconds()
            if time_since_last_activity > 30:  # 30 seconds of inactivity
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking backpressure: {e}")
            return False

    async def _update_session_status(self, session_id: str, status: StreamStatus):
        """Update session status thread-safely"""
        async with self._session_lock:
            if session_id in self._sessions:
                self._sessions[session_id].status = status
                self._sessions[session_id].updated_at = datetime.utcnow()
                self._sessions[session_id].last_activity = datetime.utcnow()

    async def _update_session_progress(
        self,
        session_id: str,
        chunks_sent: Optional[int] = None,
        bytes_sent: Optional[int] = None,
    ):
        """Update session progress thread-safely"""
        async with self._session_lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                if chunks_sent is not None:
                    session.chunks_sent = chunks_sent
                if bytes_sent is not None:
                    session.bytes_sent = bytes_sent
                session.last_activity = datetime.utcnow()

    async def _increment_session_errors(self, session_id: str):
        """Increment session error count thread-safely"""
        async with self._session_lock:
            if session_id in self._sessions:
                self._sessions[session_id].error_count += 1

    async def _get_session(self, session_id: str) -> Optional[StreamSession]:
        """Get session thread-safely"""
        async with self._session_lock:
            return self._sessions.get(session_id)

    async def cancel_stream(self, session_id: str, user_id: str) -> bool:
        """Cancel a streaming session"""
        try:
            session = await self._get_session(session_id)

            if not session or session.user_id != user_id:
                return False

            await self._update_session_status(session_id, StreamStatus.CANCELLED)

            # Record metrics
            self.metrics_manager.register_counter(
                "stream_sessions_cancelled_total"
            ).inc()

            self.structured_logger.log_event(
                event="stream_session_cancelled",
                user_id=user_id,
                details={"session_id": session_id},
            )

            return True

        except Exception as e:
            logger.error(f"Error cancelling stream {session_id}: {e}")
            return False

    async def get_session_info(
        self, session_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get session information with access control"""
        try:
            session = await self._get_session(session_id)

            if not session or session.user_id != user_id:
                return None

            return {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "response_id": session.response_id,
                "status": session.status.value,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "chunks_sent": session.chunks_sent,
                "bytes_sent": session.bytes_sent,
                "error_count": session.error_count,
                "last_activity": session.last_activity.isoformat(),
                "metadata": session.metadata,
            }

        except Exception as e:
            logger.error(f"Error getting session info {session_id}: {e}")
            return None

    async def _cleanup_loop(self):
        """Background cleanup loop for expired sessions"""
        while self._running:
            try:
                await asyncio.sleep(60)  # Run every minute

                async with self._session_lock:
                    now = datetime.utcnow()
                    expired_sessions = []

                    for session_id, session in self._sessions.items():
                        # Clean up sessions older than 1 hour or in error state
                        age = (now - session.created_at).total_seconds()
                        if age > 3600 or session.status == StreamStatus.ERROR:
                            expired_sessions.append(session_id)

                    # Remove expired sessions
                    for session_id in expired_sessions:
                        del self._sessions[session_id]

                    if expired_sessions:
                        self.structured_logger.log_event(
                            event="stream_sessions_cleaned",
                            details={
                                "expired_count": len(expired_sessions),
                                "remaining_sessions": len(self._sessions),
                            },
                        )

                # Clean up old rate limit entries
                async with self._rate_lock:
                    cutoff = now - timedelta(minutes=5)
                    for user_id in list(self._user_rates.keys()):
                        self._user_rates[user_id] = [
                            timestamp
                            for timestamp in self._user_rates[user_id]
                            if timestamp > cutoff
                        ]

                        if not self._user_rates[user_id]:
                            del self._user_rates[user_id]

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    async def shutdown(self):
        """Shutdown the stream processor gracefully"""
        self._running = False

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Close all active sessions
        async with self._session_lock:
            for session_id, session in self._sessions.items():
                if session.status in [StreamStatus.ACTIVE, StreamStatus.INITIALIZING]:
                    await self._update_session_status(
                        session_id, StreamStatus.CANCELLED
                    )

        # Close connection pool
        if self._connection_pool:
            # Close connections based on your implementation
            pass

        logger.info("AsyncStreamProcessor shutdown completed")

    async def health_check(self) -> bool:
        """Health check for the stream processor"""
        try:
            # Check if running
            if not self._running:
                return False

            # Check connection pool
            if not self._connection_pool:
                return False

            # Check cleanup task
            if not self._cleanup_task or self._cleanup_task.done():
                return False

            return True

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    async def get_metrics(self) -> Dict[str, Any]:
        """Get stream processor metrics"""
        async with self._session_lock:
            active_sessions = sum(
                1
                for session in self._sessions.values()
                if session.status == StreamStatus.ACTIVE
            )

            total_sessions = len(self._sessions)

            status_counts = {}
            for status in StreamStatus:
                status_counts[status.value] = sum(
                    1 for session in self._sessions.values() if session.status == status
                )

        return {
            "active_sessions": active_sessions,
            "total_sessions": total_sessions,
            "status_counts": status_counts,
            "max_concurrent_streams": self.max_concurrent_streams,
            "running": self._running,
            "connection_pool_healthy": bool(self._connection_pool),
        }

    async def emit_agent_step_event(self, session_id: str, event_data: Dict[str, Any]):
        """Emit agent step event to stream.

        Args:
            session_id: The stream session ID
            event_data: Agent step event data containing type, step_id, metadata, etc.
        """
        try:
            event_type = event_data.get("type", "agent_step_started")

            agent_event_chunk = StreamChunk(
                chunk_id=-1,
                content="",
                metadata={"event": "agent_step", "data": event_data},
                event_type=event_type,
            )

            session = await self._get_session(session_id)
            if session and session.status in [
                StreamStatus.ACTIVE,
                StreamStatus.INITIALIZING,
            ]:
                await self._send_agent_event_chunk(session_id, agent_event_chunk)

                logger.info(
                    f"Emitted agent step event {event_type} for session {session_id}"
                )

                self.metrics_manager.register_counter(
                    "agent_step_events_total", ["event_type"]
                ).labels(event_type=event_type).inc()

        except Exception as e:
            logger.error(f"Failed to emit agent step event: {e}", exc_info=True)

    async def _send_agent_event_chunk(self, session_id: str, chunk: StreamChunk):
        """Send agent event chunk using non-blocking I/O"""
        try:
            await asyncio.sleep(0.001)
            return True
        except Exception as e:
            logger.error(
                f"Error sending agent event chunk for session {session_id}: {e}"
            )
            raise

    async def _handle_chunk_timeout(self, session_id: str, user_id: str):
        """Handle chunk timeout with fallback logic"""
        try:
            session = await self._get_session(session_id)
            if session:
                session.status = StreamStatus.TIMEOUT
                session.timeout_count += 1

                self.structured_logger.log_event(
                    event="chunk_timeout",
                    user_id=user_id,
                    details={
                        "session_id": session_id,
                        "timeout_count": session.timeout_count,
                    },
                )

                self.metrics_manager.register_counter(
                    "stream_chunk_timeouts_total"
                ).inc()

                # Generate fallback response if enabled
                if getattr(self.config_manager, "enable_fallback", True):
                    fallback_chunk = await self._generate_fallback_chunk(
                        session_id, user_id, "chunk_timeout"
                    )
                    yield fallback_chunk

                await self._update_session_status(session_id, StreamStatus.TIMEOUT)

        except Exception as e:
            logger.error(f"Error handling chunk timeout: {e}")
            # Generate error terminal event
            error_chunk = StreamChunk(
                chunk_id=0,
                content="",
                metadata={
                    "event": "error",
                    "error": str(e),
                    "session_id": session_id,
                },
                finished=True,
                event_type="error",
            )
            yield error_chunk

    async def _generate_fallback_chunk(
        self, session_id: str, user_id: str, reason: str
    ) -> StreamChunk:
        """Generate fallback chunk for timeout or error scenarios"""
        fallback_content = (
            "I apologize, but I'm experiencing technical difficulties. "
            "Please try again in a moment or contact support if the issue persists."
        )

        self.structured_logger.log_event(
            event="stream_fallback_generated",
            user_id=user_id,
            details={
                "session_id": session_id,
                "reason": reason,
            },
        )

        self.metrics_manager.register_counter(
            "stream_fallbacks_total", ["reason"]
        ).labels(reason=reason).inc()

        return StreamChunk(
            chunk_id=0,
            content=fallback_content,
            metadata={
                "event": "fallback",
                "session_id": session_id,
                "reason": reason,
                "formatted": False,
            },
            finished=True,
            event_type="fallback",
        )

    async def _format_completion_chunk(
        self,
        full_response: str,
        session_metadata: Dict[str, Any],
        session_id: str,
        response_id: str,
        model: Optional[str],
    ) -> StreamChunk:
        """Format completion chunk with guaranteed terminal event"""
        try:
            formatted_content = full_response
            completion_metadata: Dict[str, Any] = {
                "model": model,
                "session_id": session_id,
                "response_id": response_id,
                "formatted": False,
            }

            if full_response.strip():
                user_prompt = ""
                if hasattr(self, "_last_messages") and self._last_messages:
                    last_message = self._last_messages[-1]
                    if isinstance(last_message, dict):
                        user_prompt = str(last_message.get("content") or "").strip()

                # Apply policy enforcement
                if hasattr(self, "response_policy_enforcer"):
                    policy_result = await self.response_policy_enforcer.enforce(
                        user_prompt=user_prompt,
                        content=full_response,
                        regenerate=None,
                    )
                    full_response = policy_result.content
                    completion_metadata["response_policy"] = dict(
                        policy_result.metadata or {}
                    )

                # Apply formatting if enabled
                if hasattr(self, "formatting_engine") and session_metadata:
                    display_context_value = str(
                        session_metadata.get("display_context", "desktop")
                    ).strip()
                    accessibility_value = str(
                        session_metadata.get("accessibility_level", "basic")
                    ).strip()
                    language = str(session_metadata.get("language", "en")).strip()
                    technical_level = str(
                        session_metadata.get("technical_level", "intermediate")
                    ).strip()

                    try:
                        from ..formatting.ResponseFormattingClass.Enums import (
                            DisplayContext,
                            AccessibilityLevel,
                        )

                        display_context = DisplayContext(display_context_value)
                        accessibility_level = AccessibilityLevel(accessibility_value)
                    except (ValueError, ImportError):
                        display_context = DisplayContext.DESKTOP
                        accessibility_level = AccessibilityLevel.BASIC

                    from ..formatting.response_formatting_engine import FormattingContext

                    formatting_context = FormattingContext(
                        display_context=display_context,
                        accessibility_level=accessibility_level,
                        user_preferences=session_metadata,
                        content_length=len(full_response),
                        technical_level=technical_level or "intermediate",
                        language=language or "en",
                    )

                    formatted_response = await self.formatting_engine.format_response(
                        content=full_response,
                        context=formatting_context,
                    )
                    formatted_content = formatted_response.content
                    completion_metadata.update(
                        {
                            "render_type": formatted_response.format_type.value,
                            "formatted": True,
                            "formatting": {
                                "format_type": formatted_response.format_type.value,
                                "sections": [
                                    section.model_dump()
                                    if hasattr(section, "model_dump")
                                    else section.dict()
                                    for section in formatted_response.sections
                                ],
                                "navigation_aids": [
                                    nav.model_dump()
                                    if hasattr(nav, "model_dump")
                                    else nav.dict()
                                    for nav in formatted_response.navigation_aids
                                ],
                                "accessibility_features": dict(
                                    formatted_response.accessibility_features or {}
                                ),
                                "estimated_reading_time": formatted_response.estimated_reading_time,
                                "formatter_metadata": dict(
                                    formatted_response.metadata or {}
                                ),
                            },
                        }
                    )

            return StreamChunk(
                chunk_id=0,
                content=formatted_content,
                metadata=completion_metadata,
                finished=True,
            )

        except Exception as e:
            logger.error(f"Error formatting completion chunk: {e}")
            # Return unformatted content on error
            return StreamChunk(
                chunk_id=0,
                content=full_response,
                metadata={
                    "event": "error",
                    "error": str(e),
                    "session_id": session_id,
                    "response_id": response_id,
                    "formatted": False,
                },
                finished=True,
                event_type="error",
            )


# Global processor instance
_stream_processor: Optional[AsyncStreamProcessor] = None


async def get_stream_processor() -> AsyncStreamProcessor:
    """Get global stream processor instance"""
    global _stream_processor
    if _stream_processor is None:
        _stream_processor = AsyncStreamProcessor()
        await _stream_processor.initialize()
    return _stream_processor

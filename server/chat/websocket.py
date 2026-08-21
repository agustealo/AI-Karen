"""
WebSocket support for real-time streaming in production chat system with enhanced security.
"""

import json
import logging
import asyncio
from typing import Dict, Any, Optional, List
from fastapi import WebSocket, WebSocketDisconnect, Depends, Query, HTTPException, status
from fastapi.websockets import WebSocketState
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime

from .models import ChatConversation, ChatMessage, ChatSession
from .schemas import StreamMessageRequest, StreamChunkResponse
from .services import ChatService
from .services_enhanced import create_secure_chat_service, SecureChatService
from .providers.base import AIRequest
from .middleware import get_current_chat_user, require_chat_permission
from .security import (
    validate_content, sanitize_content, get_content_validator, 
    SecurityLevel, ThreatLevel
)
from .security_monitoring import (
    record_chat_metric, start_chat_session, update_chat_session,
    end_chat_session, MetricType, log_security_event, get_chat_monitoring_service
)
from ai_karen_engine.config.llm_provider_config import get_provider_config_manager

logger = logging.getLogger(__name__)


def _resolve_max_tokens(
    provider_name: Optional[str],
    model_name: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
    default: int = 2048,
) -> int:
    """Resolve the effective output token budget from the central provider registry."""
    requested_max_tokens = (metadata or {}).get("max_tokens")
    if not provider_name:
        return (
            requested_max_tokens
            if isinstance(requested_max_tokens, int) and requested_max_tokens > 0
            else default
        )

    try:
        resolved = get_provider_config_manager().get_effective_max_tokens(
            provider_name,
            model_name=model_name,
            requested_max_tokens=requested_max_tokens,
        )
        if isinstance(resolved, int) and resolved > 0:
            return resolved
    except Exception:
        pass

    if isinstance(requested_max_tokens, int) and requested_max_tokens > 0:
        return requested_max_tokens

    return default


class ConnectionManager:
    """Manages WebSocket connections for chat streaming with security."""
    
    def __init__(self):
        self.active_connections: Dict[str, Dict[str, Any]] = {}
        self.user_sessions: Dict[str, str] = {}
        self.connection_security: Dict[str, Dict[str, Any]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str, security_context: Dict[str, Any]):
        """Accept and store a WebSocket connection with security validation."""
        await websocket.accept()
        connection_id = f"{user_id}_{id(websocket)}"
        
        # Store connection with security context
        self.active_connections[connection_id] = {
            "websocket": websocket,
            "user_id": user_id,
            "connected_at": datetime.utcnow(),
            "security_level": security_context.get("security_level", "medium"),
            "ip_address": security_context.get("ip_address", "unknown")
        }
        self.user_sessions[connection_id] = user_id
        self.connection_security[connection_id] = security_context
        
        logger.info(f"WebSocket connected for user {user_id}, connection {connection_id}")
        
        # Record connection metric
        await record_chat_metric(MetricType.ACTIVE_USERS, 1, "count")
        
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "connection_id": connection_id,
            "timestamp": asyncio.get_event_loop().time(),
            "security_level": security_context.get("security_level", "medium")
        })
    
    async def disconnect(self, websocket: WebSocket, user_id: str, reason: str = "normal"):
        """Remove and close a WebSocket connection with security logging."""
        connection_id = f"{user_id}_{id(websocket)}"
        
        # Get security context for logging
        security_context = self.connection_security.get(connection_id, {})
        
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
        
        if connection_id in self.user_sessions:
            del self.user_sessions[connection_id]
        
        if connection_id in self.connection_security:
            del self.connection_security[connection_id]
        
        logger.info(f"WebSocket disconnected for user {user_id}, connection {connection_id}, reason: {reason}")
        
        # Log security event for disconnection
        await log_security_event(
            "websocket_disconnected",
            {
                "user_id": user_id,
                "connection_id": connection_id,
                "reason": reason,
                "session_duration": (datetime.utcnow() - security_context.get("connected_at", datetime.utcnow())).total_seconds()
            },
            user_id=user_id,
            ip_address=security_context.get("ip_address", "unknown"),
            threat_level=ThreatLevel.LOW
        )
        
        # Record disconnection metric
        await record_chat_metric(MetricType.ACTIVE_CONNECTIONS, -1, "count")
    
    async def send_to_user(self, user_id: str, message: Dict[str, Any], require_permission: str = None):
        """Send a message to all connections for a specific user with permission check."""
        user_connections = [
            (conn_id, conn_info) for conn_id, conn_info in self.active_connections.items()
            if conn_info.get("user_id") == user_id
        ]
        
        # Check permission if required
        if require_permission:
            for conn_id, conn_info in user_connections:
                security_context = self.connection_security.get(conn_id, {})
                user_permissions = security_context.get("permissions", [])
                if require_permission not in user_permissions:
                    logger.warning(f"Permission denied for user {user_id}, required: {require_permission}")
                    continue
        
        sent_count = 0
        for conn_id, conn_info in user_connections:
            try:
                websocket = conn_info["websocket"]
                
                # Validate message content
                if "content" in message:
                    validation_result = validate_content(
                        message["content"], 
                        conn_info.get("security_level", "medium")
                    )
                    
                    if not validation_result.is_valid:
                        await log_security_event(
                            "websocket_message_validation_failed",
                            {
                                "user_id": user_id,
                                "connection_id": conn_id,
                                "threats": validation_result.threats_detected,
                                "content_preview": message["content"][:100] + "..." if len(message["content"]) > 100 else message["content"]
                            },
                            user_id=user_id,
                            ip_address=conn_info.get("ip_address", "unknown"),
                            threat_level=validation_result.max_threat_level
                        )
                        continue
                
                await websocket.send_json(message)
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send WebSocket message to {conn_id}: {e}")
        
        return sent_count
    
    async def broadcast_to_conversation(self, conversation_id: str, message: Dict[str, Any], require_permission: str = "read"):
        """Broadcast a message to all users in a conversation with permission check."""
        sent_count = 0
        for conn_id, conn_info in self.active_connections.items():
            try:
                security_context = self.connection_security.get(conn_id, {})
                user_permissions = security_context.get("permissions", [])
                
                # Check if user has required permission
                if require_permission and require_permission not in user_permissions:
                    continue
                
                websocket = conn_info["websocket"]
                
                # Validate message content
                if "content" in message:
                    validation_result = validate_content(
                        message["content"], 
                        conn_info.get("security_level", "medium")
                    )
                    
                    if not validation_result.is_valid:
                        await log_security_event(
                            "websocket_broadcast_validation_failed",
                            {
                                "conversation_id": conversation_id,
                                "connection_id": conn_id,
                                "threats": validation_result.threats_detected,
                                "content_preview": message["content"][:100] + "..." if len(message["content"]) > 100 else message["content"]
                            },
                            user_id=conn_info.get("user_id"),
                            ip_address=conn_info.get("ip_address", "unknown"),
                            threat_level=validation_result.max_threat_level
                        )
                        continue
                
                await websocket.send_json(message)
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to broadcast WebSocket message to {conn_id}: {e}")
        
        return sent_count
    
    async def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics for monitoring."""
        total_connections = len(self.active_connections)
        unique_users = len(set(conn_info.get("user_id") for conn_info in self.active_connections.values()))
        
        security_levels = {}
        for conn_info in self.active_connections.values():
            level = conn_info.get("security_level", "medium")
            security_levels[level] = security_levels.get(level, 0) + 1
        
        return {
            "total_connections": total_connections,
            "unique_users": unique_users,
            "security_levels": security_levels,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def cleanup_inactive_connections(self, max_inactive_minutes: int = 30):
        """Clean up inactive connections to prevent resource leaks."""
        current_time = datetime.utcnow()
        inactive_connections = []
        
        for conn_id, conn_info in list(self.active_connections.items()):
            connected_at = conn_info.get("connected_at", current_time)
            inactive_minutes = (current_time - connected_at).total_seconds() / 60
            
            if inactive_minutes > max_inactive_minutes:
                inactive_connections.append(conn_id)
                try:
                    websocket = conn_info["websocket"]
                    await websocket.close(code=1000, reason="Connection timeout")
                except Exception as e:
                    logger.error(f"Failed to close inactive connection {conn_id}: {e}")
        
        # Remove inactive connections
        for conn_id in inactive_connections:
            user_id = self.active_connections[conn_id].get("user_id")
            await self.disconnect(
                self.active_connections[conn_id]["websocket"], 
                user_id, 
                "timeout"
            )
        
        if inactive_connections:
            logger.info(f"Cleaned up {len(inactive_connections)} inactive WebSocket connections")


# Global connection manager with security
manager = ConnectionManager()


async def get_websocket_service(
    db_session: AsyncSession = Depends(get_db_session)
) -> SecureChatService:
    """Dependency to get secure chat service for WebSocket."""
    service = create_secure_chat_service(db_session)
    await service.initialize_providers()
    return service


async def get_current_user_websocket(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
) -> Optional[Dict[str, Any]]:
    """Get current user from WebSocket connection with JWT validation."""
    if not token:
        await websocket.close(code=4001, reason="Authentication token required")
        return None
    
    try:
        # Validate JWT token
        from .middleware import verify_jwt_token
        user_context = await verify_jwt_token(token)
        
        if not user_context:
            await websocket.close(code=4002, reason="Invalid authentication token")
            return None
        
        # Get client IP for security logging
        client_ip = websocket.client.host if websocket.client else "unknown"
        
        # Enhance user context with WebSocket-specific info
        user_context.update({
            "client_ip": client_ip,
            "user_agent": websocket.headers.get("user-agent", "unknown"),
            "connection_time": datetime.utcnow().isoformat()
        })
        
        # Log WebSocket authentication
        await log_security_event(
            "websocket_authentication",
            {
                "user_id": user_context.get("user_id"),
                "client_ip": client_ip,
                "user_agent": websocket.headers.get("user-agent", "unknown")
            },
            user_id=user_context.get("user_id"),
            ip_address=client_ip,
            threat_level=ThreatLevel.LOW
        )
        
        return user_context
        
    except Exception as e:
        logger.error(f"WebSocket authentication error: {e}")
        await websocket.close(code=4003, reason="Authentication failed")
        return None


async def websocket_endpoint(
    websocket: WebSocket,
    conversation_id: str,
    token: Optional[str] = Query(None),
    db_session: AsyncSession = Depends(get_websocket_service)
):
    """WebSocket endpoint for real-time chat streaming with enhanced security."""
    # Authenticate user
    current_user = await get_current_user_websocket(websocket, token)
    
    if not current_user:
        return
    
    user_id = current_user["user_id"]
    
    # Create security context for connection
    security_context = {
        "user_id": user_id,
        "ip_address": current_user.get("client_ip", "unknown"),
        "security_level": current_user.get("security_level", "medium"),
        "permissions": current_user.get("permissions", []),
        "user_agent": current_user.get("user_agent", "unknown")
    }
    
    # Verify user has access to conversation
    conversation_result = await db_session.db_session.execute(
        select(ChatConversation).where(
            and_(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user_id
            )
        )
    )
    conversation = conversation_result.scalar_one_or_none()
        
    if not conversation:
        await log_security_event(
            "websocket_unauthorized_conversation_access",
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "client_ip": current_user.get("client_ip"),
                "user_agent": current_user.get("user_agent")
            },
            user_id=user_id,
            ip_address=current_user.get("client_ip"),
            threat_level=ThreatLevel.HIGH
        )
        await websocket.close(code=4004, reason="Conversation not found or access denied")
        return
        
        # Start chat session for monitoring
        await start_chat_session(user_id, conversation_id, {
            "websocket_connection": True,
            "security_level": security_context["security_level"],
            "client_ip": security_context["ip_address"]
        })
        
        # Connect to manager with security context
        await manager.connect(websocket, user_id, security_context)

        try:
            # Handle WebSocket messages with security validation
            while True:
                # Receive message with timeout
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=300.0,  # 5 minute timeout
                )

                message_type = data.get("type")

                # Rate limiting check
                if message_type in ["message", "typing"]:
                    monitoring_service = get_chat_monitoring_service()
                    if not monitoring_service.rate_limiter.check_rate_limit(
                        user_id,
                        "websocket_message",
                        10,
                        60,  # 10 messages per minute
                    ):
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "Rate limit exceeded. Please wait before sending more messages.",
                            }
                        )
                        await log_security_event(
                            "websocket_rate_limit_exceeded",
                            {
                                "user_id": user_id,
                                "message_type": message_type,
                                "client_ip": security_context["ip_address"],
                            },
                            user_id=user_id,
                            ip_address=security_context["ip_address"],
                            threat_level=ThreatLevel.MEDIUM,
                        )
                        continue

                if message_type == "ping":
                    # Handle ping
                    await websocket.send_json(
                        {
                            "type": "pong",
                            "timestamp": asyncio.get_event_loop().time(),
                        }
                    )

                elif message_type == "message":
                    # Handle chat message with security validation
                    await handle_chat_message_secure(
                        websocket,
                        user_id,
                        conversation_id,
                        data,
                        db_session,
                        manager,
                        security_context,
                    )

                elif message_type == "typing":
                    # Handle typing indicator
                    await handle_typing_indicator(
                        websocket, user_id, conversation_id, data, manager
                    )

                else:
                    logger.warning(
                        f"Unknown WebSocket message type: {message_type}"
                    )
                    await log_security_event(
                        "websocket_unknown_message_type",
                        {
                            "user_id": user_id,
                            "message_type": message_type,
                            "data": str(data)[:200],  # Truncate for logging
                        },
                        user_id=user_id,
                        ip_address=security_context["ip_address"],
                        threat_level=ThreatLevel.LOW,
                    )

        except asyncio.TimeoutError:
            logger.info(f"WebSocket timeout for user {user_id}")
            await websocket.close(code=1000, reason="Connection timeout")

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for user {user_id}")

        except Exception as e:
            logger.error(f"WebSocket error for user {user_id}: {e}")
            await log_security_event(
                "websocket_error",
                {
                    "user_id": user_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                user_id=user_id,
                ip_address=security_context["ip_address"],
                threat_level=ThreatLevel.MEDIUM,
            )
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "An error occurred while processing your message",
                }
            )

        finally:
            # Clean up connection and end session
            await manager.disconnect(websocket, user_id, "connection_closed")
            await end_chat_session(
                user_id,
                conversation_id,
                {"websocket_disconnected": True},
            )


async def handle_chat_message_secure(
    websocket: WebSocket,
    user_id: str,
    conversation_id: str,
    data: Dict[str, Any],
    db_session: AsyncSession,
    manager: ConnectionManager,
    security_context: Dict[str, Any]
):
    """Handle incoming chat message with security validation."""
    try:
        content = data.get("content", "").strip()
        
        if not content:
            return
        
        # Validate content security
        validation_result = validate_content(
            content, 
            security_context.get("security_level", "medium")
        )
        
        if not validation_result.is_valid:
            await websocket.send_json({
                "type": "error",
                "message": f"Message validation failed: {', '.join(validation_result.threats_detected)}"
            })
            
            await log_security_event(
                "websocket_message_validation_failed",
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "content_preview": content[:100] + "..." if len(content) > 100 else content,
                    "threats": validation_result.threats_detected,
                    "client_ip": security_context["ip_address"]
                },
                user_id=user_id,
                ip_address=security_context["ip_address"],
                threat_level=validation_result.max_threat_level
            )
            return
        
        # Sanitize content
        sanitized_content = sanitize_content(content)
        
        # Create stream request
        request = StreamMessageRequest(
            content=sanitized_content,
            conversation_id=conversation_id,
            role="user"
        )
        
        # Get conversation details
        conversation_result = await db_session.db_session.execute(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id
            )
        )
        conversation = conversation_result.scalar_one_or_none()
        
        if not conversation:
            await websocket.send_json({
                "type": "error",
                "message": "Conversation not found"
            })
            return
        
        # Check conversation security level
        if conversation.security_level == "high" and "admin" not in security_context.get("permissions", []):
            await websocket.send_json({
                "type": "error",
                "message": "Insufficient permissions for high security conversation"
            })
            return
        
        # Get provider
        provider = await db_session.get_provider(conversation.provider_id)
        if not provider:
            provider = await db_session.get_default_provider()
        
        if not provider:
            await websocket.send_json({
                "type": "error",
                "message": "No available AI provider"
            })
            return
        
        # Get conversation history
        history_result = await db_session.db_session.execute(
            select(ChatMessage).where(
                ChatMessage.conversation_id == conversation_id
            ).order_by(ChatMessage.created_at)
        )
        history_messages = history_result.scalars().all()
        
        # Prepare messages for AI
        messages = []
        if conversation.system_prompt:
            messages.append({"role": "system", "content": conversation.system_prompt})
        
        for msg in history_messages:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })
        
        # Add current message
        messages.append({"role": "user", "content": sanitized_content})
        
        # Create AI request
        ai_request = AIRequest(
            messages=messages,
            model=conversation.model,
            temperature=conversation.temperature,
            max_tokens=conversation.max_tokens
            or _resolve_max_tokens(
                conversation.provider_id, conversation.model, conversation.metadata
            ),
            metadata=conversation.metadata
        )
        
        # Send user message confirmation
        await websocket.send_json({
            "type": "message_received",
            "content": sanitized_content,
            "timestamp": asyncio.get_event_loop().time()
        })
        
        # Update chat session
        await update_chat_session(user_id, conversation_id, {
            "last_message": sanitized_content,
            "message_count": 1
        })
        
        # Stream AI response
        buffer = ""
        start_time = asyncio.get_event_loop().time()
        
        async for chunk in await provider.stream(ai_request):
            buffer += chunk.content
            
            # Validate chunk content
            if chunk.content:
                chunk_validation = validate_content(
                    chunk.content, 
                    security_context.get("security_level", "medium")
                )
                
                if not chunk_validation.is_valid:
                    await log_security_event(
                        "websocket_chunk_validation_failed",
                        {
                            "user_id": user_id,
                            "conversation_id": conversation_id,
                            "provider": chunk.provider,
                            "threats": chunk_validation.threats_detected
                        },
                        user_id=user_id,
                        ip_address=security_context["ip_address"],
                        threat_level=chunk_validation.max_threat_level
                    )
                    continue
            
            # Send chunk to user
            await websocket.send_json({
                "type": "chunk",
                "content": chunk.content,
                "role": chunk.role,
                "provider": chunk.provider,
                "is_complete": chunk.is_complete,
                "timestamp": asyncio.get_event_loop().time()
            })
            
            if chunk.is_complete:
                # Save complete message to database
                await save_ai_message_secure(
                    db_session, conversation_id, user_id, 
                    buffer, chunk.provider, chunk.model,
                    start_time, security_context
                )
                break
    
    except Exception as e:
        logger.error(f"Error handling secure chat message: {e}")
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
        
        await log_security_event(
            "websocket_message_handling_error",
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "error": str(e),
                "error_type": type(e).__name__
            },
            user_id=user_id,
            ip_address=security_context["ip_address"],
            threat_level=ThreatLevel.MEDIUM
        )


async def handle_typing_indicator(
    websocket: WebSocket,
    user_id: str,
    conversation_id: str,
    data: Dict[str, Any],
    manager: ConnectionManager
):
    """Handle typing indicator with security validation."""
    try:
        is_typing = data.get("is_typing", False)
        
        # Broadcast typing indicator to conversation participants
        await manager.broadcast_to_conversation(conversation_id, {
            "type": "typing",
            "user_id": user_id,
            "is_typing": is_typing,
            "timestamp": asyncio.get_event_loop().time()
        })
        
    except Exception as e:
        logger.error(f"Error handling typing indicator: {e}")


async def save_ai_message_secure(
    db_session: AsyncSession,
    conversation_id: str,
    user_id: str,
    content: str,
    provider: str,
    model: str,
    start_time: float,
    security_context: Dict[str, Any]
):
    """Save AI message to database with security validation."""
    try:
        import uuid
        
        # Validate content before saving
        validation_result = validate_content(
            content, 
            security_context.get("security_level", "medium")
        )
        
        if not validation_result.is_valid:
            await log_security_event(
                "ai_message_validation_failed",
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "provider": provider,
                    "threats": validation_result.threats_detected
                },
                user_id=user_id,
                ip_address=security_context["ip_address"],
                threat_level=validation_result.max_threat_level
            )
            return
        
        ai_message = ChatMessage(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            provider_id=provider,
            model=model,
            response_time=(asyncio.get_event_loop().time() - start_time) * 1000,
            metadata={
                "security_level": security_context.get("security_level", "medium"),
                "validated": True,
                "client_ip": security_context["ip_address"]
            }
        )
        
        db_session.add(ai_message)
        await db_session.commit()
        
        logger.info(f"Saved AI message for conversation {conversation_id}")
        
        # Record metric
        await record_chat_metric(MetricType.MESSAGE_VOLUME, 1, "count")
        
    except Exception as e:
        logger.error(f"Failed to save secure AI message: {e}")
        await db_session.rollback()


@router.get("/ws/stats")
async def get_websocket_stats(
    current_user: Dict[str, Any] = Depends(require_chat_admin)
):
    """Get WebSocket connection statistics (admin only)."""
    stats = await manager.get_connection_stats()
    
    await log_security_event(
        "websocket_stats_accessed",
        {
            "user_id": current_user["user_id"],
            "stats": stats
        },
        user_id=current_user["user_id"],
        threat_level=ThreatLevel.LOW
    )
    
    return stats


# Background task to clean up inactive connections
async def cleanup_websocket_connections():
    """Background task to clean up inactive WebSocket connections."""
    while True:
        try:
            await manager.cleanup_inactive_connections()
            await asyncio.sleep(300)  # Check every 5 minutes
        except Exception as e:
            logger.error(f"WebSocket cleanup error: {e}")
            await asyncio.sleep(60)  # Wait 1 minute on error


# Placeholder dependencies - these would be replaced with actual implementations
async def get_db_session():
    """Placeholder for database session dependency."""
    pass

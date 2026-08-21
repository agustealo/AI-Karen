"""
Chat service layer with business logic for the production chat system.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_, desc
from sqlalchemy.orm import selectinload

from ai_karen_engine.config.llm_provider_config import get_provider_config_manager
from .models import (
    ChatConversation,
    ChatMessage,
    ChatProviderConfiguration,
    ChatSession,
    MessageAttachment,
)
from .schemas import (
    CreateConversationRequest,
    UpdateConversationRequest,
    SendMessageRequest,
    ConversationResponse,
    MessageResponse,
    ConfigureProviderRequest,
    ProviderResponse,
    MessageMetadata,
    ConversationMetadata,
)
from .providers import (
    BaseLLMProvider,
    OpenAIProvider,
    AnthropicProvider,
    GeminiProvider,
    LocalModelProvider,
)
from .providers.base import AIRequest, AIResponse, AIStreamChunk

logger = logging.getLogger(__name__)

"""
Enhanced chat service layer with security and audit logging for AI-Karen production chat system.
This extends the existing ChatService with security features.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_, desc
from sqlalchemy.orm import selectinload

from .models import (
    ChatConversation,
    ChatMessage,
    ChatProviderConfiguration,
    ChatSession,
    MessageAttachment,
)
from .schemas import (
    CreateConversationRequest,
    UpdateConversationRequest,
    SendMessageRequest,
    ConversationResponse,
    MessageResponse,
    ConfigureProviderRequest,
    ProviderResponse,
    MessageMetadata,
    ConversationMetadata,
)
from .providers import (
    BaseLLMProvider,
    OpenAIProvider,
    AnthropicProvider,
    GeminiProvider,
    LocalModelProvider,
)
from .providers.base import AIRequest, AIResponse, AIStreamChunk
from .security import (
    ContentValidator,
    ValidationResult,
    SecurityLevel,
    get_content_validator,
    get_encryption_manager,
    validate_file_upload,
    sanitize_filename,
)
from .security_monitoring import (
    log_security_event,
    record_chat_metric,
    start_chat_session,
    update_chat_session,
    end_chat_session,
    ThreatLevel,
    MetricType,
)

logger = logging.getLogger(__name__)


class SecureChatService:
    """Enhanced chat service with security and audit logging."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self._providers: Dict[str, BaseLLMProvider] = {}
        self.content_validator = get_content_validator(SecurityLevel.MEDIUM)
        self.encryption_manager = get_encryption_manager()

    def _resolve_max_tokens(
        self,
        provider_name: Optional[str],
        model_name: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
        default: int = 2048,
    ) -> int:
        """Resolve the effective output token budget from the central provider registry."""
        requested_max_tokens = (metadata or {}).get("max_tokens")
        if not provider_name:
            return requested_max_tokens if isinstance(requested_max_tokens, int) and requested_max_tokens > 0 else default

        try:
            manager = get_provider_config_manager()
            resolved = manager.get_effective_max_tokens(
                provider_name,
                model_name=model_name,
                requested_max_tokens=requested_max_tokens,
            )
            if isinstance(resolved, int) and resolved > 0:
                return resolved
        except Exception as exc:
            logger.debug(
                "Falling back to request/default max_tokens for %s/%s: %s",
                provider_name,
                model_name,
                exc,
            )

        if isinstance(requested_max_tokens, int) and requested_max_tokens > 0:
            return requested_max_tokens

        return default

    async def initialize_providers(self):
        """Initialize all configured providers from database."""
        try:
            # Load provider configurations from database
            result = await self.db_session.execute(
                select(ChatProviderConfiguration).where(
                    ChatProviderConfiguration.is_active == True
                )
            )
            provider_configs = result.scalars().all()

            for config in provider_configs:
                provider = await self._create_provider(config)
                if provider:
                    self._providers[str(config.provider_id)] = provider

            logger.info(f"Initialized {len(self._providers)} chat providers")

        except Exception as e:
            logger.error(f"Failed to initialize providers: {e}")
            raise

    async def _create_provider(
        self, config: ChatProviderConfiguration
    ) -> Optional[BaseLLMProvider]:
        """Create a provider instance from configuration."""
        try:
            provider_config = dict(config.config)

            if config.provider_type == "openai":
                provider = OpenAIProvider(str(config.provider_id), provider_config)
            elif config.provider_type == "anthropic":
                provider = AnthropicProvider(str(config.provider_id), provider_config)
            elif config.provider_type == "gemini":
                provider = GeminiProvider(str(config.provider_id), provider_config)
            elif config.provider_type == "local":
                provider = LocalModelProvider(str(config.provider_id), provider_config)
            else:
                logger.warning(f"Unknown provider type: {config.provider_type}")
                return None

            # Configure provider
            await provider.configure(provider_config)

            return provider

        except Exception as e:
            logger.error(f"Failed to create provider {config.provider_id}: {e}")
            return None

    async def get_provider(self, provider_id: str) -> Optional[BaseLLMProvider]:
        """Get a provider by ID."""
        return self._providers.get(provider_id)

    async def get_default_provider(self) -> Optional[BaseLLMProvider]:
        """Get default provider."""
        # Try to get the first available provider
        for provider in self._providers.values():
            status = await provider.get_status()
            if status.is_available and status.is_healthy:
                return provider

        return None

    async def create_conversation_secure(
        self, user_id: str, request: CreateConversationRequest
    ) -> ConversationResponse:
        """Create a new conversation with security validation."""
        session_id = str(uuid.uuid4())
        await start_chat_session(session_id, user_id)

        try:
            # Validate input
            if request.title:
                title_validation = self.content_validator.validate_content(
                    request.title, "text"
                )
                if not title_validation.is_valid:
                    await log_security_event(
                        "invalid_content",
                        {
                            "conversation_creation": True,
                            "threats": title_validation.threats_detected,
                        },
                        user_id=user_id,
                        threat_level=ThreatLevel.MEDIUM,
                    )
                    raise ValueError(
                        f"Invalid title: {', '.join(title_validation.threats_detected)}"
                    )

                request.title = title_validation.sanitized_content

            # Extract values from request metadata if available
            metadata = request.metadata or {}
            provider_config = metadata.get("provider_id", "openai")
            model = metadata.get("model_used", "gpt-3.5-turbo")
            system_prompt = metadata.get(
                "system_prompt", "You are a helpful AI assistant."
            )
            temperature = metadata.get("temperature", 0.7)
            max_tokens = self._resolve_max_tokens(provider_config, model, metadata)

            # Validate system prompt
            if system_prompt:
                prompt_validation = self.content_validator.validate_content(
                    system_prompt, "text"
                )
                if not prompt_validation.is_valid:
                    await log_security_event(
                        "invalid_content",
                        {
                            "conversation_creation": True,
                            "threats": prompt_validation.threats_detected,
                        },
                        user_id=user_id,
                        threat_level=ThreatLevel.MEDIUM,
                    )
                    raise ValueError(
                        f"Invalid system prompt: {', '.join(prompt_validation.threats_detected)}"
                    )

                system_prompt = prompt_validation.sanitized_content

            # Encrypt sensitive metadata
            sensitive_fields = ["api_key", "auth_token", "webhook_url"]
            encrypted_metadata = self.encryption_manager.encrypt_sensitive_fields(
                metadata, sensitive_fields
            )

            # Create conversation
            conversation = ChatConversation(
                id=str(uuid.uuid4()),
                user_id=user_id,
                title=request.title or "New Conversation",
                provider_id=provider_config,
                model=model,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                metadata=encrypted_metadata,
            )

            self.db_session.add(conversation)
            await self.db_session.commit()
            await self.db_session.refresh(conversation)

            # Log audit event
            await log_security_event(
                "conversation_created",
                {
                    "conversation_id": conversation.id,
                    "provider_id": provider_config,
                    "model": model,
                },
                user_id=user_id,
            )

            # Record metrics
            await record_chat_metric(MetricType.ACTIVE_USERS, 1, "count")

            await end_chat_session(session_id)

            # Create response
            return ConversationResponse(
                id=conversation.id,
                user_id=conversation.user_id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                provider_id=conversation.provider_id,
                model_used=conversation.model,
                message_count=0,
                metadata=ConversationMetadata(**conversation.metadata),
                is_archived=False,
                messages=[],
            )

        except Exception as e:
            await end_chat_session(session_id)
            await self.db_session.rollback()
            logger.error(f"Failed to create conversation: {e}")
            raise

    async def send_message_secure(
        self, conversation_id: str, user_id: str, request: SendMessageRequest
    ) -> MessageResponse:
        """Send a message with security validation and audit logging."""
        session_id = str(uuid.uuid4())
        await start_chat_session(session_id, user_id)

        try:
            # Validate message content
            content_validation = self.content_validator.validate_content(
                request.content, "text"
            )
            if not content_validation.is_valid:
                await log_security_event(
                    "invalid_content",
                    {
                        "message_send": True,
                        "threats": content_validation.threats_detected,
                    },
                    user_id=user_id,
                    threat_level=ThreatLevel.MEDIUM,
                )
                raise ValueError(
                    f"Invalid message content: {', '.join(content_validation.threats_detected)}"
                )

            sanitized_content = content_validation.sanitized_content

            # Check rate limit
            rate_limit_ok = await self._check_message_rate_limit(user_id)
            if not rate_limit_ok:
                await log_security_event(
                    "rate_limit_exceeded",
                    {"message_send": True, "user_id": user_id},
                    user_id=user_id,
                    threat_level=ThreatLevel.MEDIUM,
                )
                raise ValueError("Message rate limit exceeded")

            # Get conversation and verify access
            conversation_result = await self.db_session.execute(
                select(ChatConversation).where(
                    and_(
                        ChatConversation.id == conversation_id,
                        ChatConversation.user_id == user_id,
                    )
                )
            )
            conversation = conversation_result.scalar_one_or_none()

            if not conversation:
                await log_security_event(
                    "unauthorized_access",
                    {"conversation_id": conversation_id, "user_id": user_id},
                    user_id=user_id,
                    threat_level=ThreatLevel.HIGH,
                )
                raise ValueError(f"Conversation {conversation_id} not found")

            # Get provider
            provider = await self.get_provider(str(conversation.provider_id))
            if not provider:
                provider = await self.get_default_provider()

            if not provider:
                raise ValueError("No available AI provider")

            # Create user message
            user_message = ChatMessage(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="user",
                content=sanitized_content,
                metadata=request.options or {},
            )

            self.db_session.add(user_message)
            await self.db_session.commit()
            await self.db_session.refresh(user_message)

            # Get conversation history
            history_result = await self.db_session.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at)
            )
            history_messages = history_result.scalars().all()

            # Prepare messages for AI
            messages = []
            if conversation.system_prompt:
                messages.append(
                    {"role": "system", "content": conversation.system_prompt}
                )

            for msg in history_messages:
                messages.append({"role": msg.role, "content": msg.content})

            # Create AI request
            ai_request = AIRequest(
                messages=messages,
                model=conversation.model,
                temperature=conversation.temperature,
                max_tokens=conversation.max_tokens
                or self._resolve_max_tokens(
                    conversation.provider_id, conversation.model, conversation.metadata
                ),
                metadata=conversation.metadata,
            )

            # Get AI response with fallback mechanism
            start_time = datetime.utcnow()
            ai_response = None
            last_error = None

            # Try primary provider
            try:
                logger.info(
                    f"Attempting AI response from provider: {provider.provider_id}"
                )
                ai_response = await provider.complete(ai_request)
                response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
                logger.info(
                    f"AI response received successfully in {response_time:.2f}ms from {provider.provider_id}"
                )

            except Exception as primary_error:
                last_error = primary_error
                logger.warning(
                    f"Primary provider {provider.provider_id} failed: {str(primary_error)}"
                )

                # Try fallback providers
                fallback_providers = [
                    p
                    for p_id, p in self._providers.items()
                    if p_id != provider.provider_id and p != provider
                ]

                if fallback_providers:
                    for fallback_provider in fallback_providers:
                        try:
                            logger.info(
                                f"Attempting fallback provider: {fallback_provider.provider_id}"
                            )
                            ai_response = await fallback_provider.complete(ai_request)
                            response_time = (
                                datetime.utcnow() - start_time
                            ).total_seconds() * 1000
                            logger.info(
                                f"Fallback provider {fallback_provider.provider_id} succeeded in {response_time:.2f}ms"
                            )
                            break
                        except Exception as fallback_error:
                            logger.warning(
                                f"Fallback provider {fallback_provider.provider_id} also failed: {str(fallback_error)}"
                            )
                            last_error = fallback_error
                            continue
                else:
                    # All providers failed - use degraded response
                    logger.error(f"All AI providers failed, using degraded response")
                    ai_response = self._get_degraded_response(ai_request)
                    response_time = (
                        datetime.utcnow() - start_time
                    ).total_seconds() * 1000

            # Validate AI response content
            response_validation = self.content_validator.validate_content(
                ai_response.content, "text"
            )
            validated_content = (
                response_validation.sanitized_content
                if response_validation.is_valid
                else ai_response.content
            )

            # Create AI message
            ai_message = ChatMessage(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="assistant",
                content=validated_content,
                provider_id=conversation.provider_id,
                model=ai_response.model,
                usage=ai_response.usage,
                response_time=response_time,
                metadata=ai_response.metadata or {},
            )

            self.db_session.add(ai_message)

            # Update conversation
            await self.db_session.commit()
            await self.db_session.refresh(ai_message)

            # Update session metrics
            await update_chat_session(
                session_id,
                message_count=2,  # user + assistant
                response_time=response_time,
                provider_used=conversation.provider_id,
            )

            # Record metrics
            await record_chat_metric(MetricType.RESPONSE_TIME, response_time, "ms")
            await record_chat_metric(MetricType.MESSAGE_VOLUME, 1, "count")

            # Log audit events
            await log_security_event(
                "message_sent",
                {
                    "conversation_id": conversation_id,
                    "message_id": user_message.id,
                    "content_length": len(sanitized_content),
                },
                user_id=user_id,
            )

            if not response_validation.is_valid:
                await log_security_event(
                    "ai_content_sanitized",
                    {
                        "conversation_id": conversation_id,
                        "message_id": ai_message.id,
                        "threats": response_validation.threats_detected,
                    },
                    user_id=user_id,
                    threat_level=ThreatLevel.LOW,
                )

            await end_chat_session(session_id)

            return MessageResponse(
                id=ai_message.id,
                conversation_id=ai_message.conversation_id,
                role=ai_message.role,
                content=ai_message.content,
                created_at=ai_message.created_at,
                updated_at=ai_message.updated_at,
                provider_id=ai_message.provider_id,
                model_used=ai_message.model,
                token_count=ai_response.usage.get("total_tokens")
                if ai_response.usage
                else None,
                processing_time_ms=int(response_time),
                metadata=MessageMetadata(**ai_message.metadata),
                parent_message_id=None,
                is_streaming=False,
                streaming_completed_at=None,
                attachments=[],
            )

        except Exception as e:
            await end_chat_session(session_id)
            await self.db_session.rollback()
            logger.error(
                f"Failed to send message to conversation {conversation_id}: {e}"
            )
            raise

    async def _check_message_rate_limit(self, user_id: str) -> bool:
        """Check if user has exceeded message rate limit."""
        try:
            # Import here to avoid circular imports
            from .middleware import check_message_rate_limit

            return await check_message_rate_limit(user_id)
        except Exception as e:
            logger.warning(f"Rate limit check failed: {e}")
            return True  # Allow on error

    async def validate_file_upload_secure(
        self, file_data: bytes, filename: str
    ) -> ValidationResult:
        """Validate uploaded file for security."""
        return validate_file_upload(file_data, filename)

    async def audit_user_action(
        self,
        user_id: str,
        action: str,
        resource_id: str = None,
        details: Dict[str, Any] = None,
    ):
        """Audit user action for security monitoring."""
        await log_security_event(
            f"user_action_{action}",
            {"resource_id": resource_id, "details": details or {}},
            user_id=user_id,
            threat_level=ThreatLevel.LOW,
        )

    def _get_degraded_response(self, request: AIRequest) -> AIResponse:
        """
        Generate a degraded response when all AI providers fail.

        Args:
            request: The original AI request

        Returns:
            AIResponse: A degraded response
        """
        logger.warning("All AI providers failed, returning degraded response")

        # Extract user message from request
        user_message = ""
        if request.messages:
            last_message = request.messages[-1]
            user_message = last_message.get("content", "")[:200]  # Truncate for safety

        # Generate a helpful degraded response
        degraded_content = f'I apologize, but I\'m currently experiencing technical difficulties. I received your message: "{user_message}". Please try again in a moment or contact support if the issue persists.'

        return AIResponse(
            content=degraded_content,
            role="assistant",
            provider="degraded_mode",
            model="fallback",
            usage={
                "prompt_tokens": len(user_message),
                "completion_tokens": len(degraded_content),
            },
            metadata={"degraded": True, "fallback_reason": "all_providers_failed"},
            response_time=0.0,
        )

    async def get_security_summary(
        self, user_id: str, hours: int = 24
    ) -> Dict[str, Any]:
        """Get security summary for a user."""
        try:
            from .security_monitoring import get_chat_monitoring_service

            monitoring_service = get_chat_monitoring_service()
            session_summary = monitoring_service.get_session_summary(hours)

            # Filter sessions for this user
            user_sessions = [
                s
                for s in monitoring_service.get_active_sessions()
                if s.user_id == user_id
            ]

            return {
                "user_id": user_id,
                "timeframe_hours": hours,
                "active_sessions": len(user_sessions),
                "session_summary": session_summary,
                "security_events": monitoring_service.get_events(
                    100, "authentication_failed"
                ),
                "alerts": monitoring_service.get_alerts(50),
            }
        except Exception as e:
            logger.error(f"Failed to get security summary for user {user_id}: {e}")
            return {"user_id": user_id, "error": str(e)}


# Factory function to create enhanced service
def create_secure_chat_service(db_session: AsyncSession) -> SecureChatService:
    """Create a secure chat service instance."""
    return SecureChatService(db_session)


class ChatService:
    """Main chat service with business logic."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self._providers: Dict[str, BaseLLMProvider] = {}
        self.content_validator = get_content_validator(SecurityLevel.MEDIUM)
        self.encryption_manager = get_encryption_manager()

    async def initialize_providers(self):
        """Initialize all configured providers from database."""
        try:
            # Load provider configurations from database
            result = await self.db_session.execute(
                select(ChatProviderConfiguration).where(
                    ChatProviderConfiguration.is_active == True
                )
            )
            provider_configs = result.scalars().all()

            for config in provider_configs:
                provider = await self._create_provider(config)
                if provider:
                    self._providers[str(config.provider_id)] = provider

            logger.info(f"Initialized {len(self._providers)} chat providers")

        except Exception as e:
            logger.error(f"Failed to initialize providers: {e}")
            raise

    async def _create_provider(
        self, config: ChatProviderConfiguration
    ) -> Optional[BaseLLMProvider]:
        """Create a provider instance from configuration."""
        try:
            provider_config = dict(config.config)

            if config.provider_type == "openai":
                provider = OpenAIProvider(str(config.provider_id), provider_config)
            elif config.provider_type == "anthropic":
                provider = AnthropicProvider(str(config.provider_id), provider_config)
            elif config.provider_type == "gemini":
                provider = GeminiProvider(str(config.provider_id), provider_config)
            elif config.provider_type == "local":
                provider = LocalModelProvider(str(config.provider_id), provider_config)
            else:
                logger.warning(f"Unknown provider type: {config.provider_type}")
                return None

            # Configure the provider
            await provider.configure(provider_config)

            return provider

        except Exception as e:
            logger.error(f"Failed to create provider {config.provider_id}: {e}")
            return None

    async def get_provider(self, provider_id: str) -> Optional[BaseLLMProvider]:
        """Get a provider by ID."""
        return self._providers.get(provider_id)

    async def get_default_provider(self) -> Optional[BaseLLMProvider]:
        """Get the default provider."""
        # Try to get the first available provider
        for provider in self._providers.values():
            status = await provider.get_status()
            if status.is_available and status.is_healthy:
                return provider

        return None

    async def list_providers(self) -> List[Dict[str, Any]]:
        """List all available providers with their status."""
        providers = []

        for provider_id, provider in self._providers.items():
            try:
                status = await provider.get_status()
                config = await provider.get_config()

                providers.append(
                    {
                        "provider_id": provider_id,
                        "provider_type": provider.__class__.__name__,
                        "is_active": True,
                        "is_available": status.is_available,
                        "is_healthy": status.is_healthy,
                        "response_time_ms": status.response_time_ms,
                        "last_checked": status.last_checked,
                        "error_message": status.error_message,
                        "config": config,
                    }
                )
            except Exception as e:
                logger.error(f"Failed to get status for provider {provider_id}: {e}")
                providers.append(
                    {
                        "provider_id": provider_id,
                        "provider_type": provider.__class__.__name__,
                        "is_active": True,
                        "is_available": False,
                        "is_healthy": False,
                        "error_message": str(e),
                    }
                )

        return providers

    async def create_conversation(
        self, user_id: str, request: CreateConversationRequest
    ) -> ConversationResponse:
        """Create a new conversation."""
        session_id = str(uuid.uuid4())
        await start_chat_session(session_id, user_id)

        try:
            # Validate input
            if request.title:
                title_validation = self.content_validator.validate_content(
                    request.title, "text"
                )
                if not title_validation.is_valid:
                    await log_security_event(
                        "invalid_content",
                        {
                            "conversation_creation": True,
                            "threats": title_validation.threats_detected,
                        },
                        user_id=user_id,
                        threat_level=ThreatLevel.MEDIUM,
                    )
                    raise ValueError(
                        f"Invalid title: {', '.join(title_validation.threats_detected)}"
                    )

                request.title = title_validation.sanitized_content

            # Extract values from request metadata if available
            metadata = request.metadata or {}
            provider_config = metadata.get("provider_id", "openai")
            model = metadata.get("model_used", "gpt-3.5-turbo")
            system_prompt = metadata.get(
                "system_prompt", "You are a helpful AI assistant."
            )
            temperature = metadata.get("temperature", 0.7)
            max_tokens = self._resolve_max_tokens(provider_config, model, metadata)

            # Validate system prompt
            if system_prompt:
                prompt_validation = self.content_validator.validate_content(
                    system_prompt, "text"
                )
                if not prompt_validation.is_valid:
                    await log_security_event(
                        "invalid_content",
                        {
                            "conversation_creation": True,
                            "threats": prompt_validation.threats_detected,
                        },
                        user_id=user_id,
                        threat_level=ThreatLevel.MEDIUM,
                    )
                    raise ValueError(
                        f"Invalid system prompt: {', '.join(prompt_validation.threats_detected)}"
                    )

                system_prompt = prompt_validation.sanitized_content

            # Encrypt sensitive metadata
            sensitive_fields = ["api_key", "auth_token", "webhook_url"]
            encrypted_metadata = self.encryption_manager.encrypt_sensitive_fields(
                metadata, sensitive_fields
            )

            # Create conversation
            conversation = ChatConversation(
                id=str(uuid.uuid4()),
                user_id=user_id,
                title=request.title or "New Conversation",
                provider_id=provider_config,
                model=model,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                metadata=encrypted_metadata,
            )

            self.db_session.add(conversation)
            await self.db_session.commit()
            await self.db_session.refresh(conversation)

            # Log audit event
            await log_security_event(
                "conversation_created",
                {
                    "conversation_id": conversation.id,
                    "provider_id": provider_config,
                    "model": model,
                },
                user_id=user_id,
            )

            # Create response
            return ConversationResponse(
                id=conversation.id,
                user_id=conversation.user_id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                provider_id=conversation.provider_id,
                model_used=conversation.model,
                message_count=0,
                metadata=ConversationMetadata(**conversation.metadata),
                is_archived=False,
                messages=[],
            )

        except Exception as e:
            await end_chat_session(session_id)
            await self.db_session.rollback()
            logger.error(f"Failed to create conversation: {e}")
            raise

    async def get_conversation(
        self, conversation_id: str, user_id: str
    ) -> Optional[ConversationResponse]:
        """Get a conversation by ID."""
        try:
            result = await self.db_session.execute(
                select(ChatConversation).where(
                    and_(
                        ChatConversation.id == conversation_id,
                        ChatConversation.user_id == user_id,
                    )
                )
            )
            conversation = result.scalar_one_or_none()

            if not conversation:
                return None

            # Count messages
            message_count_result = await self.db_session.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == conversation_id
                )
            )
            message_count = len(message_count_result.scalars().all())

            # Get last message time
            last_message_result = await self.db_session.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(desc(ChatMessage.created_at))
                .limit(1)
            )
            last_message = last_message_result.scalar_one_or_none()

            return ConversationResponse(
                id=conversation.id,
                user_id=conversation.user_id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                provider_id=conversation.provider_id,
                model_used=conversation.model,
                message_count=message_count,
                metadata=ConversationMetadata(**conversation.metadata),
                is_archived=conversation.is_archived,
                messages=[],
            )

        except Exception as e:
            logger.error(f"Failed to get conversation {conversation_id}: {e}")
            raise

    async def list_conversations(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> List[ConversationResponse]:
        """List user conversations."""
        try:
            result = await self.db_session.execute(
                select(ChatConversation)
                .where(ChatConversation.user_id == user_id)
                .order_by(desc(ChatConversation.updated_at))
                .limit(limit)
                .offset(offset)
            )
            conversations = result.scalars().all()

            conversation_responses = []
            for conversation in conversations:
                # Count messages
                message_count_result = await self.db_session.execute(
                    select(ChatMessage).where(
                        ChatMessage.conversation_id == conversation.id
                    )
                )
                message_count = len(message_count_result.scalars().all())

                # Get last message time
                last_message_result = await self.db_session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation.id)
                    .order_by(desc(ChatMessage.created_at))
                    .limit(1)
                )
                last_message = last_message_result.scalar_one_or_none()

                conversation_responses.append(
                    ConversationResponse(
                        id=conversation.id,
                        user_id=conversation.user_id,
                        title=conversation.title,
                        created_at=conversation.created_at,
                        updated_at=conversation.updated_at,
                        provider_id=conversation.provider_id,
                        model_used=conversation.model,
                        message_count=message_count,
                        metadata=ConversationMetadata(**conversation.metadata),
                        is_archived=conversation.is_archived,
                        messages=[],
                    )
                )

            return conversation_responses

        except Exception as e:
            logger.error(f"Failed to list conversations for user {user_id}: {e}")
            raise

    async def send_message(
        self, conversation_id: str, user_id: str, request: SendMessageRequest
    ) -> MessageResponse:
        """Send a message and get AI response."""
        try:
            # Get conversation
            conversation_result = await self.db_session.execute(
                select(ChatConversation).where(
                    and_(
                        ChatConversation.id == conversation_id,
                        ChatConversation.user_id == user_id,
                    )
                )
            )
            conversation = conversation_result.scalar_one_or_none()

            if not conversation:
                raise ValueError(f"Conversation {conversation_id} not found")

            # Get provider
            provider = await self.get_provider(str(conversation.provider_id))
            if not provider:
                provider = await self.get_default_provider()

            if not provider:
                raise ValueError("No available AI provider")

            # Create user message
            user_message = ChatMessage(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="user",
                content=request.content,
                metadata=request.options or {},
            )

            self.db_session.add(user_message)
            await self.db_session.commit()
            await self.db_session.refresh(user_message)

            # Get conversation history
            history_result = await self.db_session.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at)
            )
            history_messages = history_result.scalars().all()

            # Prepare messages for AI
            messages = []
            if conversation.system_prompt:
                messages.append(
                    {"role": "system", "content": conversation.system_prompt}
                )

            for msg in history_messages:
                messages.append({"role": msg.role, "content": msg.content})

            # Create AI request
            ai_request = AIRequest(
                messages=messages,
                model=conversation.model,
                temperature=conversation.temperature,
                max_tokens=conversation.max_tokens
                or self._resolve_max_tokens(
                    conversation.provider_id, conversation.model, conversation.metadata
                ),
                metadata=conversation.metadata,
            )

            # Get AI response
            ai_response = await provider.complete(ai_request)

            # Create AI message
            ai_message = ChatMessage(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role="assistant",
                content=ai_response.content,
                provider_id=conversation.provider_id,
                model=ai_response.model,
                usage=ai_response.usage,
                response_time=ai_response.response_time,
                metadata=ai_response.metadata or {},
            )

            self.db_session.add(ai_message)

            # Update conversation
            # conversation.updated_at = datetime.utcnow()  # SQLAlchemy handles this automatically

            await self.db_session.commit()
            await self.db_session.refresh(ai_message)

            return MessageResponse(
                id=ai_message.id,
                conversation_id=ai_message.conversation_id,
                role=ai_message.role,
                content=ai_message.content,
                created_at=ai_message.created_at,
                updated_at=ai_message.updated_at,
                provider_id=ai_message.provider_id,
                model_used=ai_message.model,
                token_count=ai_message.usage.get("total_tokens")
                if ai_message.usage
                else None,
                processing_time_ms=int(ai_response.response_time)
                if ai_response.response_time
                else None,
                metadata=MessageMetadata(**ai_message.metadata),
                parent_message_id=None,
                is_streaming=False,
                streaming_completed_at=None,
                attachments=[],
            )

        except Exception as e:
            await self.db_session.rollback()
            logger.error(
                f"Failed to send message to conversation {conversation_id}: {e}"
            )
            raise

    async def get_messages(
        self, conversation_id: str, user_id: str, limit: int = 100, offset: int = 0
    ) -> List[MessageResponse]:
        """Get messages for a conversation."""
        try:
            # Verify conversation belongs to user
            conversation_result = await self.db_session.execute(
                select(ChatConversation).where(
                    and_(
                        ChatConversation.id == conversation_id,
                        ChatConversation.user_id == user_id,
                    )
                )
            )
            conversation = conversation_result.scalar_one_or_none()

            if not conversation:
                raise ValueError(f"Conversation {conversation_id} not found")

            # Get messages
            result = await self.db_session.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at)
                .limit(limit)
                .offset(offset)
            )
            messages = result.scalars().all()

            return [
                MessageResponse(
                    id=message.id,
                    conversation_id=message.conversation_id,
                    role=message.role,
                    content=message.content,
                    created_at=message.created_at,
                    updated_at=message.updated_at,
                    provider_id=message.provider_id,
                    model_used=message.model,
                    token_count=message.usage.get("total_tokens")
                    if message.usage
                    else None,
                    processing_time_ms=int(message.response_time)
                    if message.response_time
                    else None,
                    metadata=MessageMetadata(**message.metadata),
                    parent_message_id=None,
                    is_streaming=False,
                    streaming_completed_at=None,
                    attachments=[],
                )
                for message in messages
            ]

        except Exception as e:
            logger.error(
                f"Failed to get messages for conversation {conversation_id}: {e}"
            )
            raise

    async def configure_provider(
        self, provider_id: str, request: ConfigureProviderRequest
    ) -> bool:
        """Configure a provider."""
        try:
            # Check if provider configuration exists
            result = await self.db_session.execute(
                select(ChatProviderConfiguration).where(
                    ChatProviderConfiguration.provider_id == provider_id
                )
            )
            config = result.scalar_one_or_none()

            if config:
                # Update existing configuration
                config.provider_type = request.config.dict().get(
                    "provider_type", "openai"
                )
                config.config = request.config.dict()
                config.is_active = (
                    request.is_active if request.is_active is not None else True
                )
                # config.updated_at = datetime.utcnow()  # SQLAlchemy handles this automatically
            else:
                # Create new configuration
                config = ChatProviderConfiguration(
                    provider_id=provider_id,
                    provider_type=request.config.dict().get("provider_type", "openai"),
                    config=request.config.dict(),
                    is_active=request.is_active
                    if request.is_active is not None
                    else True,
                )
                self.db_session.add(config)

            await self.db_session.commit()

            # Reinitialize providers
            await self.initialize_providers()

            return True

        except Exception as e:
            await self.db_session.rollback()
            logger.error(f"Failed to configure provider {provider_id}: {e}")
            raise

    async def get_provider_configurations(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all provider configurations for a user."""
        try:
            result = await self.db_session.execute(
                select(ChatProviderConfiguration)
                .where(ChatProviderConfiguration.user_id == user_id)
                .order_by(ChatProviderConfiguration.priority.desc())
            )
            configs = result.scalars().all()

            return [
                {
                    "provider_id": str(config.provider_id),
                    "provider_name": config.provider_name,
                    "provider_type": config.provider_type,
                    "config": config.config,
                    "is_active": config.is_active,
                    "priority": config.priority,
                    "created_at": config.created_at.isoformat(),
                    "updated_at": config.updated_at.isoformat(),
                }
                for config in configs
            ]
        except Exception as e:
            logger.error(
                f"Failed to get provider configurations for user {user_id}: {e}"
            )
            raise

    async def get_provider_configuration(
        self, user_id: str, provider_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a specific provider configuration for a user."""
        try:
            result = await self.db_session.execute(
                select(ChatProviderConfiguration).where(
                    and_(
                        ChatProviderConfiguration.user_id == user_id,
                        ChatProviderConfiguration.provider_id == provider_id,
                    )
                )
            )
            config = result.scalar_one_or_none()

            if not config:
                return None

            return {
                "provider_id": str(config.provider_id),
                "provider_name": config.provider_name,
                "provider_type": config.provider_type,
                "config": config.config,
                "is_active": config.is_active,
                "priority": config.priority,
                "created_at": config.created_at.isoformat(),
                "updated_at": config.updated_at.isoformat(),
            }
        except Exception as e:
            logger.error(
                f"Failed to get provider configuration {provider_id} for user {user_id}: {e}"
            )
            raise

    async def create_provider_configuration(
        self,
        user_id: str,
        provider_id: str,
        provider_name: str,
        provider_type: str,
        config: Dict[str, Any],
        priority: int = 0,
    ) -> bool:
        """Create a new provider configuration."""
        try:
            # Check if configuration already exists
            existing = await self.db_session.execute(
                select(ChatProviderConfiguration).where(
                    and_(
                        ChatProviderConfiguration.user_id == user_id,
                        ChatProviderConfiguration.provider_id == provider_id,
                    )
                )
            )
            if existing.scalar_one_or_none():
                logger.warning(
                    f"Provider configuration {provider_id} already exists for user {user_id}"
                )
                return False

            # Create new configuration
            new_config = ChatProviderConfiguration(
                user_id=user_id,
                provider_id=provider_id,
                provider_name=provider_name,
                provider_type=provider_type,
                config=config,
                is_active=True,
                priority=priority,
            )

            self.db_session.add(new_config)
            await self.db_session.commit()

            # Reinitialize providers to include new one
            await self.initialize_providers()

            logger.info(
                f"Created provider configuration {provider_id} for user {user_id}"
            )
            return True

        except Exception as e:
            await self.db_session.rollback()
            logger.error(
                f"Failed to create provider configuration {provider_id} for user {user_id}: {e}"
            )
            return False

    async def update_provider_configuration(
        self,
        user_id: str,
        provider_id: str,
        config: Dict[str, Any],
        is_active: Optional[bool] = None,
        priority: Optional[int] = None,
    ) -> bool:
        """Update an existing provider configuration."""
        try:
            # Get existing configuration
            result = await self.db_session.execute(
                select(ChatProviderConfiguration).where(
                    and_(
                        ChatProviderConfiguration.user_id == user_id,
                        ChatProviderConfiguration.provider_id == provider_id,
                    )
                )
            )
            existing_config = result.scalar_one_or_none()

            if not existing_config:
                logger.warning(
                    f"Provider configuration {provider_id} not found for user {user_id}"
                )
                return False

            # Update fields
            if config is not None:
                existing_config.config = config
            if is_active is not None:
                existing_config.is_active = is_active
            if priority is not None:
                existing_config.priority = priority

            await self.db_session.commit()

            # Reinitialize providers to reflect changes
            await self.initialize_providers()

            logger.info(
                f"Updated provider configuration {provider_id} for user {user_id}"
            )
            return True

        except Exception as e:
            await self.db_session.rollback()
            logger.error(
                f"Failed to update provider configuration {provider_id} for user {user_id}: {e}"
            )
            return False

    async def delete_provider_configuration(
        self, user_id: str, provider_id: str
    ) -> bool:
        """Delete a provider configuration."""
        try:
            # Get existing configuration
            result = await self.db_session.execute(
                select(ChatProviderConfiguration).where(
                    and_(
                        ChatProviderConfiguration.user_id == user_id,
                        ChatProviderConfiguration.provider_id == provider_id,
                    )
                )
            )
            existing_config = result.scalar_one_or_none()

            if not existing_config:
                logger.warning(
                    f"Provider configuration {provider_id} not found for user {user_id}"
                )
                return False

            # Delete configuration
            await self.db_session.delete(existing_config)
            await self.db_session.commit()

            # Remove from providers cache
            if provider_id in self._providers:
                del self._providers[provider_id]

            logger.info(
                f"Deleted provider configuration {provider_id} for user {user_id}"
            )
            return True

        except Exception as e:
            await self.db_session.rollback()
            logger.error(
                f"Failed to delete provider configuration {provider_id} for user {user_id}: {e}"
            )
            return False

    async def test_provider_connection(
        self, user_id: str, provider_id: str, config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Test connection to a provider."""
        try:
            # Get provider configuration
            if config is None:
                provider_config = await self.get_provider_configuration(
                    user_id, provider_id
                )
                if not provider_config:
                    return {
                        "success": False,
                        "error": f"Provider configuration {provider_id} not found",
                    }
                config = provider_config["config"]

            # Get provider instance
            provider = self._providers.get(provider_id)
            if not provider:
                # Try to create temporary provider for testing
                provider_config_result = await self.get_provider_configuration(
                    user_id, provider_id
                )
                if not provider_config_result:
                    return {
                        "success": False,
                        "error": f"Provider configuration {provider_id} not found",
                    }

                provider = await self._create_provider_from_config(
                    provider_id, provider_config_result["provider_type"], config
                )
                if not provider:
                    return {
                        "success": False,
                        "error": f"Failed to create provider {provider_id}",
                    }

            # Test connection
            status = await provider.health_check()

            return {
                "success": status.is_available and status.is_healthy,
                "response_time": status.response_time_ms,
                "error": status.error_message,
                "data": {
                    "last_checked": status.last_checked.isoformat()
                    if status.last_checked
                    else None
                },
            }

        except Exception as e:
            logger.error(f"Failed to test provider connection {provider_id}: {e}")
            return {"success": False, "error": str(e)}

    async def get_provider_status(
        self, user_id: str, provider_id: str
    ) -> Dict[str, Any]:
        """Get current status of a provider."""
        try:
            # Get provider
            provider = self._providers.get(provider_id)
            if not provider:
                return {"error": f"Provider {provider_id} not found"}

            # Get status
            status = await provider.get_status()

            # Get metrics
            metrics = await self.get_provider_metrics(user_id, provider_id)

            return {
                "provider_id": provider_id,
                "is_available": status.is_available,
                "is_healthy": status.is_healthy,
                "response_time_ms": status.response_time_ms,
                "error_message": status.error_message,
                "last_checked": status.last_checked.isoformat()
                if status.last_checked
                else None,
                "metrics": metrics,
            }

        except Exception as e:
            logger.error(f"Failed to get provider status {provider_id}: {e}")
            return {"error": str(e)}

    async def get_all_provider_statuses(self, user_id: str) -> List[Dict[str, Any]]:
        """Get status of all providers for a user."""
        try:
            statuses = []

            for provider_id in self._providers.keys():
                status = await self.get_provider_status(user_id, provider_id)
                if "error" not in status:
                    statuses.append(status)

            return statuses

        except Exception as e:
            logger.error(f"Failed to get all provider statuses for user {user_id}: {e}")
            raise

    async def get_provider_metrics(
        self, user_id: str, provider_id: str
    ) -> Dict[str, Any]:
        """Get performance metrics for a provider."""
        try:
            # This would typically be stored in a metrics table
            # For now, return basic metrics from the provider
            provider = self._providers.get(provider_id)
            if not provider:
                return {"error": f"Provider {provider_id} not found"}

            status = await provider.get_status()

            return {
                "provider_id": provider_id,
                "response_time_ms": status.response_time_ms,
                "is_available": status.is_available,
                "is_healthy": status.is_healthy,
                "last_checked": status.last_checked.isoformat()
                if status.last_checked
                else None,
                "error_rate": 0.0,  # Would be calculated from actual usage data
                "uptime_percentage": 100.0,  # Would be calculated from actual usage data
                "request_count": 0,  # Would be from usage tracking
                "success_count": 0,  # Would be from usage tracking
            }

        except Exception as e:
            logger.error(f"Failed to get provider metrics {provider_id}: {e}")
            return {"error": str(e)}

    async def get_all_provider_metrics(self, user_id: str) -> List[Dict[str, Any]]:
        """Get performance metrics for all providers."""
        try:
            all_metrics = []

            for provider_id in self._providers.keys():
                metrics = await self.get_provider_metrics(user_id, provider_id)
                if "error" not in metrics:
                    all_metrics.append(metrics)

            return all_metrics

        except Exception as e:
            logger.error(f"Failed to get all provider metrics for user {user_id}: {e}")
            raise

    async def set_fallback_chain(self, user_id: str, provider_ids: List[str]) -> bool:
        """Set the fallback chain order for providers."""
        try:
            # Update priorities for all providers in the chain
            for i, provider_id in enumerate(provider_ids):
                success = await self.update_provider_configuration(
                    user_id, provider_id, {}, None, len(provider_ids) - i
                )
                if not success:
                    logger.warning(
                        f"Failed to update priority for provider {provider_id}"
                    )

            # Reinitialize providers to reflect new priorities
            await self.initialize_providers()

            logger.info(f"Set fallback chain for user {user_id}: {provider_ids}")
            return True

        except Exception as e:
            logger.error(f"Failed to set fallback chain for user {user_id}: {e}")
            return False

    async def get_fallback_chain(self, user_id: str) -> List[str]:
        """Get the current fallback chain order."""
        try:
            configs = await self.get_provider_configurations(user_id)

            # Sort by priority (higher first)
            sorted_configs = sorted(configs, key=lambda x: x["priority"], reverse=True)

            return [
                config["provider_id"]
                for config in sorted_configs
                if config["is_active"]
            ]

        except Exception as e:
            logger.error(f"Failed to get fallback chain for user {user_id}: {e}")
            raise

    async def set_primary_provider(self, user_id: str, provider_id: str) -> bool:
        """Set the primary provider for a user."""
        try:
            # Set highest priority for the primary provider
            success = await self.update_provider_configuration(
                user_id, provider_id, {}, None, 999
            )

            if success:
                logger.info(f"Set primary provider {provider_id} for user {user_id}")

            return success

        except Exception as e:
            logger.error(
                f"Failed to set primary provider {provider_id} for user {user_id}: {e}"
            )
            return False

    async def get_primary_provider(self, user_id: str) -> Optional[str]:
        """Get the primary provider for a user."""
        try:
            configs = await self.get_provider_configurations(user_id)

            # Find the one with highest priority
            primary_config = max(configs, key=lambda x: x["priority"], default=None)

            return primary_config["provider_id"] if primary_config else None

        except Exception as e:
            logger.error(f"Failed to get primary provider for user {user_id}: {e}")
            raise

    async def _create_provider_from_config(
        self, provider_id: str, provider_type: str, config: Dict[str, Any]
    ) -> Optional[BaseLLMProvider]:
        """Create a provider instance from configuration."""
        try:
            if provider_type == "openai":
                return OpenAIProvider(provider_id, config)
            elif provider_type == "anthropic":
                return AnthropicProvider(provider_id, config)
            elif provider_type == "gemini":
                return GeminiProvider(provider_id, config)
            elif provider_type == "local":
                return LocalModelProvider(provider_id, config)
            else:
                logger.error(f"Unknown provider type: {provider_type}")
                return None

        except Exception as e:
            logger.error(f"Failed to create provider {provider_id}: {e}")
            return None

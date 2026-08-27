"""
Base provider interface for the production chat system.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, AsyncGenerator, Union
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class ProviderFeatures:
    """Provider capabilities and features."""

    def __init__(
        self,
        streaming: bool = False,
        function_calling: bool = False,
        vision: bool = False,
        embedding: bool = False,
        fine_tuning: bool = False,
        max_tokens: int = 2048,
        supported_models: Optional[List[str]] = None
    ):
        self.streaming = streaming
        self.function_calling = function_calling
        self.vision = vision
        self.embedding = embedding
        self.fine_tuning = fine_tuning
        self.max_tokens = max_tokens
        self.supported_models = supported_models or []


class AIRequest:
    """AI request structure for LLM providers."""

    def __init__(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.messages = messages
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
        self.tools = tools
        self.metadata = metadata or {}


class AIResponse:
    """AI response structure from LLM providers."""

    def __init__(
        self,
        content: str,
        provider: str,
        model: str,
        role: str = "assistant",
        usage: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        response_time: Optional[float] = None
    ):
        self.content = content
        self.role = role
        self.provider = provider
        self.model = model
        self.usage = usage
        self.metadata = metadata or {}
        self.response_time = response_time


class AIStreamChunk:
    """AI streaming chunk structure."""

    def __init__(
        self,
        content: str,
        provider: str,
        role: str = "assistant",
        is_complete: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.content = content
        self.role = role
        self.provider = provider
        self.is_complete = is_complete
        self.metadata = metadata or {}


class ProviderStatus:
    """Provider status information."""

    def __init__(
        self,
        is_available: bool,
        is_healthy: bool,
        response_time_ms: Optional[float] = None,
        error_message: Optional[str] = None,
        last_checked: Optional[datetime] = None
    ):
        self.is_available = is_available
        self.is_healthy = is_healthy
        self.response_time_ms = response_time_ms
        self.error_message = error_message
        self.last_checked = last_checked or datetime.utcnow()


class ValidationResult:
    """Validation result for provider configuration."""

    def __init__(
        self,
        is_valid: bool,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None
    ):
        self.is_valid = is_valid
        self.errors = errors or []
        self.warnings = warnings or []


class BaseLLMProvider(ABC):
    """Base interface for all LLM providers."""

    def __init__(self, provider_id: str, config: Dict[str, Any]):
        self.provider_id = provider_id
        self.config = config
        self._features = None

    @property
    def features(self) -> ProviderFeatures:
        """Get provider features and capabilities."""
        if self._features is None:
            self._features = self._get_features()
        return self._features

    @abstractmethod
    def _get_features(self) -> ProviderFeatures:
        """Get provider-specific features and capabilities."""
        pass

    @abstractmethod
    async def complete(self, request: AIRequest) -> AIResponse:
        """Complete a chat request non-streaming."""
        pass

    @abstractmethod
    async def stream(self, request: AIRequest) -> AsyncGenerator[AIStreamChunk, None]:
        """Stream a chat request."""
        pass

    @abstractmethod
    async def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate provider configuration."""
        pass

    @abstractmethod
    async def get_status(self) -> ProviderStatus:
        """Get the current status of the provider."""
        pass

    @abstractmethod
    async def configure(self, config: Dict[str, Any]) -> None:
        """Configure the provider with new settings."""
        pass

    @abstractmethod
    async def get_config(self) -> Dict[str, Any]:
        """Get the current provider configuration."""
        pass

    async def health_check(self) -> ProviderStatus:
        """Perform a health check on the provider."""
        start_time = time.time()
        try:
            test_request = AIRequest(
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            await self.complete(test_request)
            response_time_ms = (time.time() - start_time) * 1000
            return ProviderStatus(
                is_available=True,
                is_healthy=True,
                response_time_ms=response_time_ms,
                last_checked=datetime.utcnow()
            )
        except Exception as e:
            logger.error(f"Health check failed for provider {self.provider_id}: {e}")
            return ProviderStatus(
                is_available=False,
                is_healthy=False,
                error_message=str(e),
                last_checked=datetime.utcnow()
            )

    def _prepare_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prepare messages for the specific provider format."""
        return messages

    def _extract_usage_info(self, response: Any) -> Optional[Dict[str, Any]]:
        """Extract usage information from provider response."""
        return None

    def _calculate_response_time(self, start_time: float) -> float:
        """Calculate response time in milliseconds."""
        return (time.time() - start_time) * 1000

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        pass


class FallbackManager:
    """Manager for handling provider fallbacks."""

    def __init__(self, providers: List[BaseLLMProvider]):
        self.providers = providers
        self.current_index = 0

    async def execute_with_fallback(self, request: AIRequest) -> AIResponse:
        """Execute request with fallback to other providers if primary fails."""
        errors = []
        for i, provider in enumerate(self.providers):
            try:
                logger.info(f"Attempting request with provider: {provider.provider_id}")
                response = await provider.complete(request)
                self.current_index = i
                logger.info(f"Request successful with provider: {provider.provider_id}")
                return response
            except Exception as e:
                error_msg = f"Provider {provider.provider_id} failed: {str(e)}"
                logger.warning(error_msg)
                errors.append(Exception(error_msg))
                continue
        error_messages = [str(e) for e in errors]
        raise Exception(f"All providers failed: {'; '.join(error_messages)}")

    def get_next_provider(self) -> BaseLLMProvider:
        """Get the next provider in the fallback chain."""
        next_index = (self.current_index + 1) % len(self.providers)
        return self.providers[next_index]

    def mark_provider_failed(self, provider_id: str) -> None:
        """Mark a provider as failed and move to next."""
        for i, provider in enumerate(self.providers):
            if provider.provider_id == provider_id:
                self.current_index = (i + 1) % len(self.providers)
                logger.warning(f"Marking provider {provider_id} as failed, moving to next provider")
                break
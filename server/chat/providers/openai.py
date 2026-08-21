"""
OpenAI provider implementation for the production chat system.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, Any, AsyncGenerator, Optional
import aiohttp

from .base import (
    BaseLLMProvider, 
    AIRequest, 
    AIResponse, 
    AIStreamChunk, 
    ProviderFeatures, 
    ProviderStatus, 
    ValidationResult
)

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """OpenAI provider implementation."""
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(provider_id, config)
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.model = config.get("model", "gpt-3.5-turbo")
        self.timeout = config.get("timeout_seconds", 30)
        self.max_tokens = config.get("max_tokens", 4096)
    
    def _get_features(self) -> ProviderFeatures:
        """Get OpenAI provider features."""
        return ProviderFeatures(
            streaming=True,
            function_calling=True,
            vision=True,
            embedding=True,
            fine_tuning=False,
            max_tokens=self.max_tokens,
            supported_models=[
                "gpt-3.5-turbo",
                "gpt-3.5",
                "gpt-4",
                "gpt-4-turbo",
                "gpt-4-32k",
                "gpt-4o",
                "gpt-4o-mini",
                "text-davinci-003",
                "text-davinci-002",
                "text-davinci-001"
            ]
        )
    
    async def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate OpenAI configuration."""
        errors = []
        warnings = []
        
        # Check required fields
        if not config.get("api_key"):
            errors.append("API key is required")
        
        # Check model
        model = config.get("model")
        if model and model not in self.features.supported_models:
            errors.append(f"Unsupported model: {model}")
        
        # Check temperature
        temperature = config.get("temperature")
        if temperature is not None and (temperature < 0.0 or temperature > 2.0):
            errors.append("Temperature must be between 0.0 and 2.0")
        
        # Check max_tokens
        max_tokens = config.get("max_tokens")
        if max_tokens is not None and max_tokens < 1:
            errors.append("Max tokens must be greater than 0")
        
        # Check timeout
        timeout = config.get("timeout_seconds")
        if timeout is not None and (timeout < 1 or timeout > 300):
            warnings.append("Timeout should be between 1 and 300 seconds")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    async def configure(self, config: Dict[str, Any]) -> None:
        """Configure the OpenAI provider."""
        self.config = config
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.model = config.get("model", "gpt-3.5-turbo")
        self.timeout = config.get("timeout_seconds", 30)
        self.max_tokens = config.get("max_tokens", self.max_tokens)
        
        logger.info(f"OpenAI provider configured with model: {self.model}")
    
    async def get_config(self) -> Dict[str, Any]:
        """Get the current OpenAI configuration."""
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout,
            "max_tokens": self.max_tokens,
        }
    
    async def get_status(self) -> ProviderStatus:
        """Get the current status of the OpenAI provider."""
        start_time = time.time()
        
        try:
            # Test with a simple API call
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.get(
                    f"{self.base_url}/models",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        response_time_ms = self._calculate_response_time(start_time)
                        return ProviderStatus(
                            is_available=True,
                            is_healthy=True,
                            response_time_ms=response_time_ms,
                            last_checked=datetime.fromtimestamp(start_time)
                        )
                    else:
                        return ProviderStatus(
                            is_available=False,
                            is_healthy=False,
                            error_message=f"API returned status {response.status}",
                            last_checked=datetime.fromtimestamp(start_time)
                        )
                        
        except Exception as e:
            logger.error(f"OpenAI status check failed: {e}")
            return ProviderStatus(
                is_available=False,
                is_healthy=False,
                error_message=str(e),
                last_checked=datetime.fromtimestamp(start_time)
            )
    
    def _prepare_messages(self, messages: list) -> list:
        """Prepare messages for OpenAI API format."""
        openai_messages = []
        
        for message in messages:
            openai_message = {
                "role": message.get("role", "user"),
                "content": message.get("content", "")
            }
            
            # Add optional fields
            if "name" in message:
                openai_message["name"] = message["name"]
            
            openai_messages.append(openai_message)
        
        return openai_messages
    
    def _extract_usage_info(self, response_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract usage information from OpenAI response."""
        usage = response_data.get("usage")
        if usage:
            return {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens")
            }
        return None
    
    async def complete(self, request: AIRequest) -> AIResponse:
        """Complete a chat request with OpenAI."""
        start_time = time.time()
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": request.model or self.model,
                "messages": self._prepare_messages(request.messages),
                "temperature": request.temperature,
                "max_tokens": request.max_tokens or self.max_tokens,
                "stream": False
            }
            
            # Add tools if provided
            if request.tools:
                payload["tools"] = request.tools
            
            # Add metadata if provided
            if request.metadata:
                payload["metadata"] = request.metadata
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        
                        content = response_data["choices"][0]["message"]["content"]
                        model_used = response_data.get("model", self.model)
                        
                        return AIResponse(
                            content=content,
                            role="assistant",
                            provider=self.provider_id,
                            model=model_used,
                            usage=self._extract_usage_info(response_data),
                            response_time=self._calculate_response_time(start_time)
                        )
                    else:
                        error_text = await response.text()
                        raise Exception(f"OpenAI API error: {response.status} - {error_text}")
                        
        except asyncio.TimeoutError:
            raise Exception(f"OpenAI API timeout after {self.timeout} seconds")
        except Exception as e:
            logger.error(f"OpenAI completion failed: {e}")
            raise
    
    async def stream(self, request: AIRequest) -> AsyncGenerator[AIStreamChunk, None]:
        """Stream a chat request with OpenAI."""
        start_time = time.time()
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": request.model or self.model,
                "messages": self._prepare_messages(request.messages),
                "temperature": request.temperature,
                "max_tokens": request.max_tokens or self.max_tokens,
                "stream": True
            }
            
            # Add tools if provided
            if request.tools:
                payload["tools"] = request.tools
            
            # Add metadata if provided
            if request.metadata:
                payload["metadata"] = request.metadata
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        buffer = ""
                        
                        async for line in response.content:
                            if line.startswith("data: "):
                                line_data = line[6:]  # Remove "data: " prefix
                                
                                if line_data.startswith("[DONE]"):
                                    # Send final chunk
                                    yield AIStreamChunk(
                                        content=buffer,
                                        role="assistant",
                                        provider=self.provider_id,
                                        is_complete=True
                                    )
                                    break
                                else:
                                    try:
                                        json_data = json.loads(line_data)
                                        if "choices" in json_data and len(json_data["choices"]) > 0:
                                            delta = json_data["choices"][0]["delta"]
                                            if "content" in delta:
                                                buffer += delta["content"]
                                            
                                            yield AIStreamChunk(
                                                content=delta.get("content", ""),
                                                role="assistant",
                                                provider=self.provider_id,
                                                is_complete=False
                                            )
                                    except json.JSONDecodeError:
                                        # Skip malformed JSON
                                        continue
                                        
                    else:
                        error_text = await response.text()
                        raise Exception(f"OpenAI API error: {response.status} - {error_text}")
                        
        except asyncio.TimeoutError:
            raise Exception(f"OpenAI API timeout after {self.timeout} seconds")
        except Exception as e:
            logger.error(f"OpenAI streaming failed: {e}")
            raise
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        # Session management not needed for this implementation
        pass

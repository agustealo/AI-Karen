"""
Anthropic provider implementation for the production chat system.
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


class AnthropicProvider(BaseLLMProvider):
    """Anthropic provider implementation."""
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(provider_id, config)
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url", "https://api.anthropic.com")
        self.model = config.get("model", "claude-3-sonnet-20240229")
        self.timeout = config.get("timeout_seconds", 30)
        self.max_tokens = config.get("max_tokens", 4096)
    
    def _get_features(self) -> ProviderFeatures:
        """Get Anthropic provider features."""
        return ProviderFeatures(
            streaming=True,
            function_calling=True,
            vision=True,
            embedding=False,  # Anthropic doesn't provide embeddings
            fine_tuning=False,
            max_tokens=self.max_tokens,
            supported_models=[
                "claude-3-opus-20240229",
                "claude-3-sonnet-20240229",
                "claude-3-haiku-20240307",
                "claude-2.1",
                "claude-2.0",
                "claude-instant-1.2"
            ]
        )
    
    async def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate Anthropic configuration."""
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
        if temperature is not None and (temperature < 0.0 or temperature > 1.0):
            errors.append("Temperature must be between 0.0 and 1.0")
        
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
        """Configure the Anthropic provider."""
        self.config = config
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url", "https://api.anthropic.com")
        self.model = config.get("model", "claude-3-sonnet-20240229")
        self.timeout = config.get("timeout_seconds", 30)
        self.max_tokens = config.get("max_tokens", 4096)
        
        logger.info(f"Anthropic provider configured with model: {self.model}")
    
    async def get_config(self) -> Dict[str, Any]:
        """Get the current Anthropic configuration."""
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout,
            "max_tokens": self.max_tokens
        }
    
    async def get_status(self) -> ProviderStatus:
        """Get the current status of the Anthropic provider."""
        start_time = time.time()
        
        try:
            # Test with a simple API call
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            
            # Anthropic doesn't have a simple status endpoint, so we'll use a minimal message
            test_payload = {
                "model": self.model,
                "max_tokens": 10,
                "messages": [
                    {"role": "user", "content": "Hi"}
                ]
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(
                    f"{self.base_url}/v1/messages",
                    headers=headers,
                    json=test_payload
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
            logger.error(f"Anthropic status check failed: {e}")
            return ProviderStatus(
                is_available=False,
                is_healthy=False,
                error_message=str(e),
                last_checked=datetime.fromtimestamp(start_time)
            )
    
    def _prepare_messages(self, messages: list) -> list:
        """Prepare messages for Anthropic API format."""
        anthropic_messages = []
        
        # Anthropic requires the conversation to start with a user message
        # and alternate between user and assistant
        
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            
            # Handle different content formats
            if isinstance(content, str):
                anthropic_message = {
                    "role": role,
                    "content": content
                }
            elif isinstance(content, list):
                # Handle multimodal content
                anthropic_message = {
                    "role": role,
                    "content": content
                }
            else:
                anthropic_message = {
                    "role": role,
                    "content": str(content)
                }
            
            anthropic_messages.append(anthropic_message)
        
        return anthropic_messages
    
    def _extract_usage_info(self, response_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract usage information from Anthropic response."""
        usage = response_data.get("usage")
        if usage:
            return {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            }
        return None
    
    def _convert_tools_to_anthropic_format(self, tools: list) -> list:
        """Convert tools to Anthropic's tool format."""
        anthropic_tools = []
        
        for tool in tools:
            anthropic_tool = {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "input_schema": tool.get("parameters", {})
            }
            anthropic_tools.append(anthropic_tool)
        
        return anthropic_tools
    
    async def complete(self, request: AIRequest) -> AIResponse:
        """Complete a chat request with Anthropic."""
        start_time = time.time()
        
        try:
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": request.model or self.model,
                "messages": self._prepare_messages(request.messages),
                "max_tokens": request.max_tokens or self.max_tokens,
                "temperature": request.temperature,
                "stream": False
            }
            
            # Add system message if provided in metadata
            if request.metadata and "system" in request.metadata:
                payload["system"] = request.metadata["system"]
            
            # Add tools if provided
            if request.tools:
                payload["tools"] = self._convert_tools_to_anthropic_format(request.tools)
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(
                    f"{self.base_url}/v1/messages",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        
                        content = response_data["content"][0]["text"] if response_data.get("content") else ""
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
                        raise Exception(f"Anthropic API error: {response.status} - {error_text}")
                        
        except asyncio.TimeoutError:
            raise Exception(f"Anthropic API timeout after {self.timeout} seconds")
        except Exception as e:
            logger.error(f"Anthropic completion failed: {e}")
            raise
    
    async def stream(self, request: AIRequest) -> AsyncGenerator[AIStreamChunk, None]:
        """Stream a chat request with Anthropic."""
        start_time = time.time()
        
        try:
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": request.model or self.model,
                "messages": self._prepare_messages(request.messages),
                "max_tokens": request.max_tokens or self.max_tokens,
                "temperature": request.temperature,
                "stream": True
            }
            
            # Add system message if provided in metadata
            if request.metadata and "system" in request.metadata:
                payload["system"] = request.metadata["system"]
            
            # Add tools if provided
            if request.tools:
                payload["tools"] = self._convert_tools_to_anthropic_format(request.tools)
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(
                    f"{self.base_url}/v1/messages",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        buffer = ""
                        
                        async for line in response.content:
                            line_str = line.decode('utf-8').strip()
                            
                            if line_str.startswith("data: "):
                                line_data = line_str[6:]  # Remove "data: " prefix
                                
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
                                        
                                        if json_data.get("type") == "content_block_delta":
                                            delta = json_data.get("delta", {})
                                            if delta.get("type") == "text_delta":
                                                text_content = delta.get("text", "")
                                                buffer += text_content
                                                
                                                yield AIStreamChunk(
                                                    content=text_content,
                                                    role="assistant",
                                                    provider=self.provider_id,
                                                    is_complete=False
                                                )
                                    except json.JSONDecodeError:
                                        # Skip malformed JSON
                                        continue
                                        
                    else:
                        error_text = await response.text()
                        raise Exception(f"Anthropic API error: {response.status} - {error_text}")
                        
        except asyncio.TimeoutError:
            raise Exception(f"Anthropic API timeout after {self.timeout} seconds")
        except Exception as e:
            logger.error(f"Anthropic streaming failed: {e}")
            raise
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        # Session management not needed for this implementation
        pass

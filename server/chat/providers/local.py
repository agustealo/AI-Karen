"""
Local model provider implementation for the production chat system.
Supports various local inference servers and custom model deployments.
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


class LocalModelProvider(BaseLLMProvider):
    """Local model provider implementation."""
    
    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(provider_id, config)
        self.base_url = config.get("base_url", "http://localhost:11434")  # Default to Ollama
        self.model = config.get("model", "llama2")
        self.timeout = config.get("timeout_seconds", 60)  # Longer timeout for local models
        self.max_tokens = config.get("max_tokens", 4096)
        self.provider_type = config.get("provider_type", "ollama")  # ollama, llama_cpp, custom
        self.api_format = config.get("api_format", "openai")  # openai, custom
    
    def _get_features(self) -> ProviderFeatures:
        """Get local model provider features."""
        # Features depend on the specific local setup
        base_features = ProviderFeatures(
            streaming=True,
            function_calling=False,  # Typically not supported by local models
            vision=False,  # Can be enabled for specific models
            embedding=False,  # Separate embedding models needed
            fine_tuning=False,  # Not applicable for local inference
            max_tokens=self.max_tokens,
            supported_models=[self.model]  # Local models are typically single-model deployments
        )
        
        # Enable vision for multimodal models
        if self.model and any(x in self.model.lower() for x in ["vision", "multimodal", "llava"]):
            base_features.vision = True
        
        return base_features
    
    async def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate local model configuration."""
        errors = []
        warnings = []
        
        # Check required fields
        if not config.get("base_url"):
            errors.append("Base URL is required for local model provider")
        
        # Check model
        model = config.get("model")
        if not model:
            errors.append("Model name is required")
        
        # Check provider type
        provider_type = config.get("provider_type")
        if provider_type and provider_type not in ["ollama", "llama_cpp", "custom"]:
            errors.append("Provider type must be one of: ollama, llama_cpp, custom")
        
        # Check API format
        api_format = config.get("api_format")
        if api_format and api_format not in ["openai", "custom"]:
            errors.append("API format must be one of: openai, custom")
        
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
        if timeout is not None and (timeout < 1 or timeout > 600):
            warnings.append("Timeout should be between 1 and 600 seconds for local models")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    async def configure(self, config: Dict[str, Any]) -> None:
        """Configure the local model provider."""
        self.config = config
        self.base_url = config.get("base_url", "http://localhost:11434")
        self.model = config.get("model", "llama2")
        self.timeout = config.get("timeout_seconds", 60)
        self.max_tokens = config.get("max_tokens", 4096)
        self.provider_type = config.get("provider_type", "ollama")
        self.api_format = config.get("api_format", "openai")
        
        logger.info(f"Local model provider configured with model: {self.model} at {self.base_url}")
    
    async def get_config(self) -> Dict[str, Any]:
        """Get the current local model configuration."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout,
            "max_tokens": self.max_tokens,
            "provider_type": self.provider_type,
            "api_format": self.api_format
        }
    
    async def get_status(self) -> ProviderStatus:
        """Get the current status of the local model provider."""
        start_time = time.time()
        
        try:
            # Different endpoints based on provider type
            if self.provider_type == "ollama":
                status_url = f"{self.base_url}/api/tags"
            elif self.provider_type == "llama_cpp":
                status_url = f"{self.base_url}/health"
            else:
                # For custom providers, try a generic health check
                status_url = f"{self.base_url}/health"
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(status_url) as response:
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
                            error_message=f"Local model server returned status {response.status}",
                            last_checked=datetime.fromtimestamp(start_time)
                        )
                        
        except Exception as e:
            logger.error(f"Local model status check failed: {e}")
            return ProviderStatus(
                is_available=False,
                is_healthy=False,
                error_message=str(e),
                last_checked=datetime.fromtimestamp(start_time)
            )
    
    def _prepare_ollama_request(self, request: AIRequest) -> Dict[str, Any]:
        """Prepare request for Ollama API format."""
        return {
            "model": request.model or self.model,
            "prompt": self._extract_prompt_from_messages(request.messages),
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens or self.max_tokens
            }
        }
    
    def _prepare_openai_format_request(self, request: AIRequest) -> Dict[str, Any]:
        """Prepare request for OpenAI-compatible format."""
        return {
            "model": request.model or self.model,
            "messages": request.messages,
            "stream": False,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or self.max_tokens
        }
    
    def _extract_prompt_from_messages(self, messages: list) -> str:
        """Extract a single prompt from message history for local models that expect a single prompt."""
        prompt_parts = []
        
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            
            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
        
        return "\n\n".join(prompt_parts)
    
    def _extract_usage_info(self, response_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract usage information from local model response."""
        # Local models may not provide detailed usage info
        if "usage" in response_data:
            return response_data["usage"]
        
        # Try to extract from common fields
        if "prompt_eval_count" in response_data and "eval_count" in response_data:
            return {
                "prompt_tokens": response_data.get("prompt_eval_count"),
                "completion_tokens": response_data.get("eval_count"),
                "total_tokens": response_data.get("prompt_eval_count", 0) + response_data.get("eval_count", 0)
            }
        
        return None
    
    async def complete(self, request: AIRequest) -> AIResponse:
        """Complete a chat request with local model."""
        start_time = time.time()
        
        try:
            # Prepare request based on provider type and API format
            if self.provider_type == "ollama":
                payload = self._prepare_ollama_request(request)
                endpoint = "/api/generate"
            elif self.api_format == "openai":
                payload = self._prepare_openai_format_request(request)
                endpoint = "/v1/chat/completions"
            else:
                # Default to OpenAI format for custom providers
                payload = self._prepare_openai_format_request(request)
                endpoint = "/v1/chat/completions"
            
            url = f"{self.base_url}{endpoint}"
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        
                        # Extract content based on provider type
                        if self.provider_type == "ollama":
                            content = response_data.get("response", "")
                        elif self.api_format == "openai":
                            choices = response_data.get("choices", [])
                            if choices and len(choices) > 0:
                                content = choices[0].get("message", {}).get("content", "")
                            else:
                                content = ""
                        else:
                            content = response_data.get("content", "")
                        
                        model_used = response_data.get("model", request.model or self.model)
                        
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
                        raise Exception(f"Local model API error: {response.status} - {error_text}")
                        
        except asyncio.TimeoutError:
            raise Exception(f"Local model API timeout after {self.timeout} seconds")
        except Exception as e:
            logger.error(f"Local model completion failed: {e}")
            raise
    
    async def stream(self, request: AIRequest) -> AsyncGenerator[AIStreamChunk, None]:
        """Stream a chat request with local model."""
        start_time = time.time()
        
        try:
            # Prepare request based on provider type and API format
            if self.provider_type == "ollama":
                payload = self._prepare_ollama_request(request)
                payload["stream"] = True
                endpoint = "/api/generate"
            elif self.api_format == "openai":
                payload = self._prepare_openai_format_request(request)
                payload["stream"] = True
                endpoint = "/v1/chat/completions"
            else:
                # Default to OpenAI format for custom providers
                payload = self._prepare_openai_format_request(request)
                payload["stream"] = True
                endpoint = "/v1/chat/completions"
            
            url = f"{self.base_url}{endpoint}"
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(url, json=payload) as response:
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
                                        
                                        # Extract content based on provider type
                                        if self.provider_type == "ollama":
                                            content = json_data.get("response", "")
                                        elif self.api_format == "openai":
                                            choices = json_data.get("choices", [])
                                            if choices and len(choices) > 0:
                                                delta = choices[0].get("delta", {})
                                                content = delta.get("content", "")
                                            else:
                                                content = ""
                                        else:
                                            content = json_data.get("content", "")
                                        
                                        if content:
                                            buffer += content
                                            
                                            yield AIStreamChunk(
                                                content=content,
                                                role="assistant",
                                                provider=self.provider_id,
                                                is_complete=False
                                            )
                                    except json.JSONDecodeError:
                                        # Skip malformed JSON
                                        continue
                                        
                    else:
                        error_text = await response.text()
                        raise Exception(f"Local model API error: {response.status} - {error_text}")
                        
        except asyncio.TimeoutError:
            raise Exception(f"Local model API timeout after {self.timeout} seconds")
        except Exception as e:
            logger.error(f"Local model streaming failed: {e}")
            raise
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        # Session management not needed for this implementation
        pass

"""
Google Gemini provider implementation for the production chat system.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, Any, AsyncGenerator, Optional, List, Union
import aiohttp

from .base import (
    BaseLLMProvider,
    AIRequest,
    AIResponse,
    AIStreamChunk,
    ProviderFeatures,
    ProviderStatus,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    """Google Gemini provider implementation."""

    def __init__(self, provider_id: str, config: Dict[str, Any]):
        super().__init__(provider_id, config)
        self.api_key = config.get("api_key")
        self.base_url = config.get(
            "base_url", "https://generativelanguage.googleapis.com"
        )
        self.model = config.get("model", "gemini-pro")
        self.timeout = config.get("timeout_seconds", 30)
        self.max_tokens = config.get("max_tokens", 4096)

    def _get_features(self) -> ProviderFeatures:
        """Get Gemini provider features."""
        return ProviderFeatures(
            streaming=True,
            function_calling=True,
            vision=True,
            embedding=True,
            fine_tuning=False,
            max_tokens=self.max_tokens,
            supported_models=[
                "gemini-pro",
                "gemini-pro-vision",
                "gemini-1.5-pro",
                "gemini-1.5-flash",
                "gemini-1.0-pro",
            ],
        )

    async def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate Gemini configuration."""
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
            is_valid=len(errors) == 0, errors=errors, warnings=warnings
        )

    async def configure(self, config: Dict[str, Any]) -> None:
        """Configure the Gemini provider."""
        self.config = config
        self.api_key = config.get("api_key")
        self.base_url = config.get(
            "base_url", "https://generativelanguage.googleapis.com"
        )
        self.model = config.get("model", "gemini-pro")
        self.timeout = config.get("timeout_seconds", 30)
        self.max_tokens = config.get("max_tokens", 4096)

        logger.info(f"Gemini provider configured with model: {self.model}")

    async def get_config(self) -> Dict[str, Any]:
        """Get the current Gemini configuration."""
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout,
            "max_tokens": self.max_tokens,
        }

    async def get_status(self) -> ProviderStatus:
        """Get the current status of the Gemini provider."""
        start_time = time.time()

        try:
            # Test with a simple API call
            url = f"{self.base_url}/v1beta/models/{self.model}:generateContent?key={self.api_key}"

            test_payload = {
                "contents": [{"parts": [{"text": "Hi"}]}],
                "generationConfig": {"maxOutputTokens": 10, "temperature": 0.1},
            }

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.post(url, json=test_payload) as response:
                    if response.status == 200:
                        response_time_ms = self._calculate_response_time(start_time)
                        return ProviderStatus(
                            is_available=True,
                            is_healthy=True,
                            response_time_ms=response_time_ms,
                            last_checked=datetime.fromtimestamp(start_time),
                        )
                    else:
                        return ProviderStatus(
                            is_available=False,
                            is_healthy=False,
                            error_message=f"API returned status {response.status}",
                            last_checked=datetime.fromtimestamp(start_time),
                        )

        except Exception as e:
            logger.error(f"Gemini status check failed: {e}")
            return ProviderStatus(
                is_available=False,
                is_healthy=False,
                error_message=str(e),
                last_checked=datetime.fromtimestamp(start_time),
            )

    def _prepare_messages(self, messages: list) -> list:
        """Prepare messages for Gemini API format."""
        gemini_contents = []

        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")

            # Convert role to Gemini format
            if role == "assistant":
                gemini_role = "model"
            else:
                gemini_role = "user"

            # Handle different content formats
            if isinstance(content, str):
                gemini_content = {"role": gemini_role, "parts": [{"text": content}]}
            elif isinstance(content, list):
                # Handle multimodal content
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        if "text" in item:
                            parts.append({"text": item["text"]})
                        elif "image_url" in item:
                            parts.append(
                                {
                                    "inline_data": {
                                        "mime_type": "image/jpeg",  # Default, should be detected
                                        "data": item["image_url"].get("url", ""),
                                    }
                                }
                            )
                    else:
                        parts.append({"text": str(item)})

                gemini_content = {"role": gemini_role, "parts": parts}
            else:
                gemini_content = {
                    "role": gemini_role,
                    "parts": [{"text": str(content)}],
                }

            gemini_contents.append(gemini_content)

        return gemini_contents

    def _extract_usage_info(self, response: Any) -> Optional[Dict[str, Any]]:
        """
        Extract usage information from provider response.

        Args:
            response: Raw provider response

        Returns:
            Optional[Dict[str, Any]]: Usage information
        """
        if isinstance(response, dict):
            metadata = response.get("usageMetadata")
            if metadata:
                return {
                    "prompt_tokens": metadata.get("promptTokenCount"),
                    "completion_tokens": metadata.get("candidatesTokenCount"),
                    "total_tokens": metadata.get("totalTokenCount"),
                }
        return None

    def _convert_tools_to_gemini_format(self, tools: list) -> Dict[str, Any]:
        """Convert tools to Gemini's tool format."""
        gemini_tools = []

        for tool in tools:
            gemini_tool = {
                "functionDeclarations": [
                    {
                        "name": tool.get("name"),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {}),
                    }
                ]
            }
            gemini_tools.append(gemini_tool)

        return {"tools": gemini_tools}

    async def complete(self, request: AIRequest) -> AIResponse:
        """Complete a chat request with Gemini."""
        start_time = time.time()

        try:
            url = f"{self.base_url}/v1beta/models/{request.model or self.model}:generateContent?key={self.api_key}"

            payload = {
                "contents": self._prepare_messages(request.messages),
                "generationConfig": {
                    "temperature": request.temperature,
                    "maxOutputTokens": request.max_tokens or self.max_tokens,
                },
            }

            # Add system instruction if provided in metadata
            if request.metadata and "system" in request.metadata:
                payload["systemInstruction"] = {
                    "parts": [{"text": request.metadata["system"]}]
                }

            # Add tools if provided
            if request.tools:
                payload.update(self._convert_tools_to_gemini_format(request.tools))

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        response_data = await response.json()

                        # Extract content from Gemini response
                        candidates = response_data.get("candidates", [])
                        if candidates and len(candidates) > 0:
                            content_parts = (
                                candidates[0].get("content", {}).get("parts", [])
                            )
                            content = ""
                            for part in content_parts:
                                if "text" in part:
                                    content += part["text"]
                        else:
                            content = ""

                        model_used = response_data.get(
                            "model", request.model or self.model
                        )

                        return AIResponse(
                            content=content,
                            role="assistant",
                            provider=self.provider_id,
                            model=model_used,
                            usage=self._extract_usage_info(response_data),
                            response_time=self._calculate_response_time(start_time),
                        )
                    else:
                        error_text = await response.text()
                        raise Exception(
                            f"Gemini API error: {response.status} - {error_text}"
                        )

        except asyncio.TimeoutError:
            raise Exception(f"Gemini API timeout after {self.timeout} seconds")
        except Exception as e:
            logger.error(f"Gemini completion failed: {e}")
            raise

    async def stream(self, request: AIRequest) -> AsyncGenerator[AIStreamChunk, None]:
        """Stream a chat request with Gemini."""
        start_time = time.time()

        try:
            url = f"{self.base_url}/v1beta/models/{request.model or self.model}:streamGenerateContent?key={self.api_key}"

            payload = {
                "contents": self._prepare_messages(request.messages),
                "generationConfig": {
                    "temperature": request.temperature,
                    "maxOutputTokens": request.max_tokens or self.max_tokens,
                },
            }

            # Add system instruction if provided in metadata
            if request.metadata and "system" in request.metadata:
                payload["systemInstruction"] = {
                    "parts": [{"text": request.metadata["system"]}]
                }

            # Add tools if provided
            if request.tools:
                payload.update(self._convert_tools_to_gemini_format(request.tools))

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        buffer = ""

                        async for line in response.content:
                            line_str = line.decode("utf-8").strip()

                            if line_str.startswith("data: "):
                                line_data = line_str[6:]  # Remove "data: " prefix

                                if line_data.startswith("[DONE]"):
                                    # Send final chunk
                                    yield AIStreamChunk(
                                        content=buffer,
                                        role="assistant",
                                        provider=self.provider_id,
                                        is_complete=True,
                                    )
                                    break
                                else:
                                    try:
                                        json_data = json.loads(line_data)

                                        candidates = json_data.get("candidates", [])
                                        if candidates and len(candidates) > 0:
                                            content_parts = (
                                                candidates[0]
                                                .get("content", {})
                                                .get("parts", [])
                                            )
                                            for part in content_parts:
                                                if "text" in part:
                                                    text_content = part["text"]
                                                    buffer += text_content

                                                    yield AIStreamChunk(
                                                        content=text_content,
                                                        role="assistant",
                                                        provider=self.provider_id,
                                                        is_complete=False,
                                                    )
                                    except json.JSONDecodeError:
                                        # Skip malformed JSON
                                        continue

                    else:
                        error_text = await response.text()
                        raise Exception(
                            f"Gemini API error: {response.status} - {error_text}"
                        )

        except asyncio.TimeoutError:
            raise Exception(f"Gemini API timeout after {self.timeout} seconds")
        except Exception as e:
            logger.error(f"Gemini streaming failed: {e}")
            raise

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        # Session management not needed for this implementation
        pass

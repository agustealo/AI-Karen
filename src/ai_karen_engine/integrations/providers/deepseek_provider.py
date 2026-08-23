"""
Enhanced Deepseek LLM Provider Implementation

Improved version with streaming support, better error handling, and latest API features.
"""

import logging
import time
import os
from typing import Any, Dict, List, Optional, Union, Iterator

from ai_karen_engine.integrations.llm_utils import (
    LLMProviderBase,
    GenerationFailed,
    EmbeddingFailed,
    record_llm_metric,
)

logger = logging.getLogger("kari.deepseek_provider")


class DeepseekProvider(LLMProviderBase):
    """Enhanced Deepseek provider with streaming support and latest features."""

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        timeout: int = 60,
        max_retries: int = 3,
    ):
        """
        Initialize Deepseek provider.

        Args:
            model: Default model name (e.g., "deepseek-chat", "deepseek-coder")
            api_key: Deepseek API key (from env DEEPSEEK_API_KEY if not provided)
            base_url: Deepseek API base URL
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.model = model
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.initialization_error: Optional[str] = None
        self.client: Optional[Any] = None

        # Graceful initialization - don't fail if API key is missing
        self._initialize_client()

    def _initialize_client(self):
        """Initialize DeepSeek client with graceful error handling."""
        try:
            import openai

            self.openai = openai

            if not self.api_key:
                self.initialization_error = "No DeepSeek API key provided. Set DEEPSEEK_API_KEY environment variable."
                logger.warning(self.initialization_error)
                return

            # Initialize client with Deepseek settings
            self.client = openai.OpenAI(
                api_key=self.api_key, base_url=self.base_url, timeout=self.timeout
            )

            # Validate API key by making a simple request
            self._validate_api_key()

        except ImportError:
            self.initialization_error = "OpenAI Python package required for DeepSeek. Install with: pip install openai"
            logger.error(self.initialization_error)
        except Exception as ex:
            self.initialization_error = f"DeepSeek client initialization failed: {ex}"
            logger.error(self.initialization_error)

    def _validate_api_key(self):
        """Validate API key with a minimal request."""
        if not self.client or not self.api_key:
            return

        try:
            # Make a minimal request to validate the API key
            self.client.models.list()
            logger.info("DeepSeek API key validated successfully")
        except Exception as ex:
            error_msg = str(ex).lower()
            if "api key" in error_msg or "unauthorized" in error_msg:
                self.initialization_error = "Invalid DeepSeek API key. Please check your DEEPSEEK_API_KEY environment variable."
            elif "rate limit" in error_msg or "quota" in error_msg:
                # Rate limit during validation is not a fatal error
                logger.warning(
                    "Rate limited during API key validation, but key appears valid"
                )
            else:
                self.initialization_error = f"API key validation failed: {ex}"

            if self.initialization_error:
                logger.error(self.initialization_error)

    def _retry_with_backoff(self, func, *args, **kwargs):
        """Execute function with exponential backoff retry logic."""
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as ex:
                last_exception = ex

                # Check if it's a retryable error
                if self._is_retryable_error(ex):
                    if attempt < self.max_retries - 1:
                        wait_time = 2**attempt  # Exponential backoff
                        logger.warning(
                            f"Attempt {attempt + 1} failed, retrying in {wait_time}s: {ex}"
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(f"All {self.max_retries} attempts failed")
                else:
                    # Non-retryable error, fail immediately
                    break

        raise last_exception

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable with enhanced classification."""
        error_str = str(error).lower()

        # Rate limiting and server errors are retryable
        retryable_patterns = [
            "rate limit",
            "too many requests",
            "server error",
            "timeout",
            "connection",
            "503",
            "502",
            "500",
            "internal server error",
            "service unavailable",
            "bad gateway",
        ]

        # Non-retryable errors (fail fast)
        non_retryable_patterns = [
            "invalid api key",
            "unauthorized",
            "forbidden",
            "not found",
            "invalid request",
            "400",
            "401",
            "403",
            "404",
        ]

        # Check non-retryable first
        if any(pattern in error_str for pattern in non_retryable_patterns):
            return False

        return any(pattern in error_str for pattern in retryable_patterns)

    def generate_text(self, prompt: str, **kwargs) -> str:
        """Generate text using Deepseek API."""
        t0 = time.time()

        # Check initialization status
        if self.initialization_error:
            raise GenerationFailed(self.initialization_error)

        if not self.client:
            raise GenerationFailed("DeepSeek client not initialized")

        try:
            model = kwargs.pop("model", self.model)

            # Prepare chat completion parameters
            messages = [{"role": "user", "content": prompt}]

            # Handle system message if provided
            if "system_message" in kwargs:
                messages.insert(
                    0, {"role": "system", "content": kwargs.pop("system_message")}
                )

            completion_kwargs = {
                "model": model,
                "messages": messages,
                "max_tokens": kwargs.pop("max_tokens", 1000),
                "temperature": kwargs.pop("temperature", 0.7),
                "top_p": kwargs.pop("top_p", 1.0),
                "frequency_penalty": kwargs.pop("frequency_penalty", 0.0),
                "presence_penalty": kwargs.pop("presence_penalty", 0.0),
            }

            # Add any additional parameters
            completion_kwargs.update(
                {k: v for k, v in kwargs.items() if k not in ["stream"]}
            )

            def _generate():
                response = self.client.chat.completions.create(**completion_kwargs)
                return response.choices[0].message.content or ""

            text = self._retry_with_backoff(_generate)

            record_llm_metric("generate_text", time.time() - t0, True, "deepseek")
            return text

        except Exception as ex:
            record_llm_metric(
                "generate_text", time.time() - t0, False, "deepseek", error=str(ex)
            )

            # Provide more specific error messages
            error_msg = str(ex).lower()
            if "api key" in error_msg or "unauthorized" in error_msg:
                raise GenerationFailed(
                    "Invalid Deepseek API key. Check your DEEPSEEK_API_KEY environment variable."
                )
            elif "rate limit" in error_msg or "quota" in error_msg:
                raise GenerationFailed(
                    "Deepseek rate limit exceeded or quota reached. Please try again later."
                )
            elif "model" in error_msg and "not found" in error_msg:
                raise GenerationFailed(
                    f"Model '{model}' not available. Check available models."
                )
            else:
                raise GenerationFailed(f"Deepseek generation failed: {ex}")

    def stream_generate(self, prompt: str, **kwargs) -> Iterator[str]:
        """Generate text with streaming support."""
        # Check initialization status
        if self.initialization_error:
            raise GenerationFailed(self.initialization_error)

        if not self.client:
            raise GenerationFailed("DeepSeek client not initialized")

        try:
            model = kwargs.pop("model", self.model)

            # Prepare chat completion parameters
            messages = [{"role": "user", "content": prompt}]

            # Handle system message if provided
            if "system_message" in kwargs:
                messages.insert(
                    0, {"role": "system", "content": kwargs.pop("system_message")}
                )

            completion_kwargs = {
                "model": model,
                "messages": messages,
                "max_tokens": kwargs.pop("max_tokens", 1000),
                "temperature": kwargs.pop("temperature", 0.7),
                "top_p": kwargs.pop("top_p", 1.0),
                "frequency_penalty": kwargs.pop("frequency_penalty", 0.0),
                "presence_penalty": kwargs.pop("presence_penalty", 0.0),
                "stream": True,
            }

            # Add any additional parameters
            completion_kwargs.update({k: v for k, v in kwargs.items()})

            def _stream():
                return self.client.chat.completions.create(**completion_kwargs)

            stream = self._retry_with_backoff(_stream)

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as ex:
            error_msg = str(ex).lower()
            if "api key" in error_msg or "unauthorized" in error_msg:
                raise GenerationFailed(
                    "Invalid Deepseek API key. Check your DEEPSEEK_API_KEY environment variable."
                )
            elif "rate limit" in error_msg:
                raise GenerationFailed(
                    "Deepseek rate limit exceeded. Please try again later."
                )
            else:
                raise GenerationFailed(f"Deepseek streaming failed: {ex}")

    def embed(self, text: Union[str, List[str]], **kwargs) -> List[float]:
        """Generate embeddings using Deepseek API (if supported)."""
        t0 = time.time()

        # Note: Deepseek may not have a dedicated embedding API
        # This is a placeholder implementation that could be updated when available
        try:
            # For now, we'll raise an informative error
            raise EmbeddingFailed(
                "Deepseek embedding API not yet supported. "
                "Use another provider like OpenAI or HuggingFace for embeddings."
            )

        except Exception as ex:
            record_llm_metric(
                "embed", time.time() - t0, False, "deepseek", error=str(ex)
            )
            raise EmbeddingFailed(f"Deepseek embedding failed: {ex}")

    def get_models(self) -> List[str]:
        """Get list of available models from DeepSeek with fallback to static list."""
        # Skip network calls in offline/development mode
        offline_mode = os.getenv("KARI_DEEPSEEK_OFFLINE", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        if offline_mode:
            logger.info("DeepSeek offline mode enabled, using static model list")
            return self._get_common_models()

        try:
            if self.initialization_error or not self.client:
                logger.info("Using fallback model list due to initialization issues")
                return self._get_common_models()

            def _list_models():
                models = self.client.models.list()
                return [model.id for model in models.data]

            discovered_models = self._retry_with_backoff(_list_models)

            # Merge with common models to ensure we have a comprehensive list
            common_models = self._get_common_models()
            all_models = list(set(discovered_models + common_models))

            logger.info(
                f"Discovered {len(discovered_models)} models from API, total available: {len(all_models)}"
            )
            return sorted(all_models)

        except Exception as ex:
            logger.warning(f"Could not fetch DeepSeek models: {ex}")
            return self._get_common_models()

    def _get_common_models(self) -> List[str]:
        """Get list of common DeepSeek models."""
        return ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"]

    def get_provider_info(self) -> Dict[str, Any]:
        """Get provider metadata with initialization status."""
        try:
            models = self.get_models()
        except Exception:
            models = []

        return {
            "name": "deepseek",
            "model": self.model,
            "base_url": self.base_url,
            "has_api_key": bool(self.api_key),
            "api_key_valid": self.initialization_error is None
            and self.client is not None,
            "initialization_error": self.initialization_error,
            "available_models": models,
            "supports_streaming": True,
            "supports_embeddings": False,  # Not yet supported
            "supports_code_generation": True,
            "supports_reasoning": True,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }

    def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check on DeepSeek API."""
        # Check initialization status first
        if self.initialization_error:
            return {
                "status": "unhealthy",
                "error": self.initialization_error,
                "provider": "deepseek",
                "initialization_status": "failed",
            }

        if not self.client:
            return {
                "status": "unhealthy",
                "error": "DeepSeek client not initialized",
                "provider": "deepseek",
                "initialization_status": "failed",
            }

        try:
            start_time = time.time()

            # Test API connectivity with minimal request
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=1,
            )

            response_time = time.time() - start_time

            health_result = {
                "status": "healthy",
                "provider": "deepseek",
                "response_time": response_time,
                "model_tested": "deepseek-chat",
                "initialization_status": "success",
                "api_key_status": "valid",
                "connectivity": "ok",
            }

            # Test model discovery
            try:
                available_models = self.get_models()
                health_result["model_discovery"] = {
                    "status": "success",
                    "models_found": len(available_models),
                    "sample_models": available_models[:5],  # First 5 models
                }
            except Exception as e:
                health_result["model_discovery"] = {"status": "failed", "error": str(e)}
                health_result["warnings"] = health_result.get("warnings", [])
                health_result["warnings"].append(
                    "Model discovery failed, using fallback list"
                )

            # Test capability detection
            try:
                health_result["capabilities"] = {
                    "text_generation": True,
                    "code_generation": True,
                    "reasoning": True,
                    "streaming": True,
                    "embeddings": False,  # Not supported yet
                    "function_calling": False,  # Check if supported
                }
            except Exception as e:
                health_result["capabilities"] = {
                    "text_generation": True,
                    "detection_error": str(e),
                }

            # Add Model Library compatibility check
            try:
                from ai_karen_engine.core.model_runtime.compatibility.provider_model_compatibility import (
                    ProviderModelCompatibilityService,
                )

                compatibility_service = ProviderModelCompatibilityService()
                validation = compatibility_service.validate_provider_model_setup(
                    "deepseek"
                )

                health_result["model_library"] = {
                    "available": True,
                    "compatible_models_count": validation.get("total_compatible", 0),
                    "validation_status": validation.get("status", "unknown"),
                }

                # Add recommendations if no compatible models
                if validation.get("total_compatible", 0) == 0:
                    health_result["warnings"] = health_result.get("warnings", [])
                    health_result["warnings"].append(
                        "No compatible models found in Model Library"
                    )

            except Exception as e:
                health_result["model_library"] = {"available": False, "error": str(e)}
                health_result["warnings"] = health_result.get("warnings", [])
                health_result["warnings"].append(f"Model Library unavailable: {e}")

            return health_result

        except Exception as ex:
            error_msg = str(ex).lower()

            # Classify the error for better diagnostics
            if "api key" in error_msg or "unauthorized" in error_msg:
                error_type = "authentication_error"
                specific_error = "Invalid or expired API key"
            elif "rate limit" in error_msg or "quota" in error_msg:
                error_type = "rate_limit_error"
                specific_error = "Rate limit exceeded or quota reached"
            elif "timeout" in error_msg or "connection" in error_msg:
                error_type = "connectivity_error"
                specific_error = "Network connectivity issue"
            elif "model" in error_msg and "not found" in error_msg:
                error_type = "model_error"
                specific_error = "Requested model not available"
            else:
                error_type = "unknown_error"
                specific_error = str(ex)

            return {
                "status": "unhealthy",
                "provider": "deepseek",
                "error": specific_error,
                "error_type": error_type,
                "raw_error": str(ex),
                "initialization_status": "success"
                if not self.initialization_error
                else "failed",
                "model_library": {
                    "available": False,
                    "error": "Provider health check failed",
                },
            }

    # Lightweight status helpers -------------------------------------------------

    def ping(self) -> bool:
        try:
            self.health_check()
            return True
        except Exception:
            return False

    def available_models(self) -> list[str]:
        try:
            return self.get_models()
        except Exception:
            return [self.model]

    def count_tokens(self, text: str) -> int:
        """
        Count the number of tokens in a text string.

        Args:
            text: The text to count tokens for

        Returns:
            int: Estimated number of tokens
        """
        try:
            # Use tiktoken for accurate token counting
            import tiktoken

            # Get encoding for the current model
            model = self.model.lower()
            if "coder" in model:
                encoding = tiktoken.encoding_for_model(
                    "gpt-4"
                )  # Close approximation for coder model
            else:
                encoding = tiktoken.encoding_for_model(
                    "gpt-3.5-turbo"
                )  # Close approximation for chat model

            return len(encoding.encode(text))

        except ImportError:
            # Fallback to rough estimation if tiktoken not available
            logger.warning("tiktoken not installed. Using rough token estimation.")
            return len(text.split()) * 1.3  # Rough estimation

        except Exception as ex:
            logger.warning(f"Token counting failed: {ex}. Using rough estimation.")
            return len(text.split()) * 1.3  # Rough estimation


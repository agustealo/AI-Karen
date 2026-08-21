"""
Enhanced OpenAI LLM Provider Implementation

Improved version with latest API features, better error handling, and streaming support.
"""

import logging
import os
import time
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterator, List, Optional, Union

from ai_karen_engine.config.llm_provider_config import (
    get_openai_compatible_provider_defaults,
)
from ai_karen_engine.integrations.llm_utils import (
    EmbeddingFailed,
    GenerationFailed,
    LLMProviderBase,
    record_llm_metric,
)

logger = logging.getLogger("kari.openai_provider")


class OpenAIProvider(LLMProviderBase):
    """Enhanced OpenAI provider with latest API features."""

    def __init__(
        self,
        model: str = "gpt-3.5-turbo",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 60,
        max_retries: int = 3,
        provider_name: str = "openai",
        health_url: Optional[str] = None,
        api_key_header: Optional[str] = None,
        api_key_prefix: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize OpenAI provider.

        Args:
            model: Default model identifier
            api_key: Provider API key (from the provider-specific env var if omitted)
            base_url: Custom base URL for OpenAI-compatible APIs
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            health_url: Optional custom health check URL
            api_key_header: Optional custom header for API key (e.g. "X-API-Key")
            api_key_prefix: Optional prefix for API key value (e.g. "Bearer")
            custom_headers: Additional custom headers for all requests
        """
        self.provider_name = str(provider_name or "openai").strip().lower()
        self.provider_defaults = get_openai_compatible_provider_defaults(
            self.provider_name
        )
        self.api_key_env_var = str(self.provider_defaults["api_key_env"])
        self.display_name = str(self.provider_defaults["display_name"])
        self.model = model
        self.api_key = api_key or os.getenv(self.api_key_env_var)
        self.base_url = self._normalize_base_url(
            base_url or str(self.provider_defaults["base_url"])
        )
        self.health_url = health_url or os.getenv(f"KAREN_BUILTIN_{self.provider_name.upper()}_HEALTH_URL")
        self.api_key_header = api_key_header or self.provider_defaults.get("api_key_header", "Authorization")
        self.api_key_prefix = api_key_prefix if api_key_prefix is not None else self.provider_defaults.get("api_key_prefix", "Bearer")
        self.custom_headers = custom_headers or {}
        self.timeout = timeout
        self.max_retries = (
            min(max_retries, 2) if self.provider_name == "zai" else max_retries
        )
        self.last_usage: Dict[str, Any] = {}
        self.initialization_error: Optional[str] = None
        self.client: Optional[Any] = None

        # Graceful initialization - don't fail if API key is missing
        self._initialize_client()

    def _initialize_client(self):
        """Initialize OpenAI client with graceful error handling."""
        try:
            import openai

            self.openai = openai

            if not self.api_key:
                if self.provider_name in ["builtin_vllm", "builtin_transformers"]:
                    # Local deployments may not require auth. Use a
                    # placeholder key so the OpenAI client can initialize.
                    self.api_key = "EMPTY"
                    logger.info(
                        "No %s API key provided; initializing unauthenticated local client",
                        self.display_name
                    )
                else:
                    self.initialization_error = (
                        f"No {self.display_name} API key provided. "
                        f"Set {self.api_key_env_var} environment variable."
                    )
                    logger.warning(self.initialization_error)
                    return

            # Initialize client with custom settings
            client_kwargs = {
                "api_key": self.api_key,
                "timeout": self.timeout,
                # Avoid stacked retries from both the OpenAI SDK and our wrapper.
                "max_retries": 0,
            }
            if self.base_url:
                client_kwargs["base_url"] = self.base_url

            # Prepare custom headers
            headers = dict(self.custom_headers)
            
            # Apply custom API key header if it's not the default Authorization header
            # or if a custom prefix is specified
            if self.api_key_header != "Authorization" or self.api_key_prefix != "Bearer":
                auth_val = f"{self.api_key_prefix} {self.api_key}" if self.api_key_prefix else self.api_key
                headers[self.api_key_header] = auth_val
                # If we're using a custom header, we must set a dummy key in the client 
                # constructor so the SDK doesn't complain about missing api_key, 
                # but our custom header will take precedence in the underlying requests.
                client_kwargs["api_key"] = "PROVIDED_VIA_CUSTOM_HEADER"

            if headers:
                client_kwargs["default_headers"] = headers

            self.client = openai.OpenAI(**client_kwargs)

            # Validate API key by making a simple request
            if self.provider_name not in ["builtin_vllm", "builtin_transformers"]:
                self._validate_api_key()

        except ImportError:
            self.initialization_error = f"{self.display_name} client dependency not installed. Install with: pip install openai"
            logger.error(self.initialization_error)
        except Exception as ex:
            self.initialization_error = (
                f"{self.display_name} client initialization failed: {ex}"
            )
            logger.error(self.initialization_error)

    def _validate_api_key(self):
        """Validate API key with a minimal request."""
        if not self.client or not self.api_key:
            return

        if self.provider_name in ["builtin_vllm", "builtin_transformers"]:
            # Local providers don't need API key validation
            return

    def _normalize_base_url(self, base_url: str) -> str:
        """Normalize provider base URLs for the active transport."""
        normalized = str(base_url or "").rstrip("/")
        if self.provider_name == "zai" and normalized.endswith("/api/coding/paas/v4"):
            logger.warning(
                "Normalizing legacy Z.ai coding endpoint to general PaaS endpoint for chat completions"
            )
            return "https://api.z.ai/api/paas/v4"
        return normalized

    def _retry_with_backoff(self, func, *args, **kwargs):
        """Execute function with exponential backoff retry logic and rate limit handling."""
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as ex:
                last_exception = ex
                error_str = str(ex).lower()

                # Handle rate limiting with specific retry-after logic
                if (
                    "rate limit" in error_str
                    or "too many requests" in error_str
                    or "429" in error_str
                ):
                    retry_after = self._extract_retry_after(ex, attempt)
                    if retry_after and attempt < self.max_retries - 1:
                        logger.warning(
                            f"Rate limited, waiting {retry_after}s before retry {attempt + 1}"
                        )
                        time.sleep(retry_after)
                        continue

                # Check if it's a retryable error
                if self._is_retryable_error(ex):
                    if attempt < self.max_retries - 1:
                        wait_time = self._default_backoff_seconds(attempt)
                        logger.warning(
                            f"Attempt {attempt + 1} failed, retrying in {wait_time}s: {ex}"
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(f"All {self.max_retries} attempts failed")
                else:
                    # Non-retryable error, fail immediately
                    logger.error(f"Non-retryable error encountered: {ex}")
                    break

        raise last_exception

    def _default_backoff_seconds(self, attempt: int) -> int:
        base_delay = 2 if self.provider_name == "zai" else 1
        return min(base_delay * (2**attempt), 60)

    def _extract_retry_after(self, error: Exception, attempt: int = 0) -> Optional[int]:
        """Extract retry-after value from rate limit error."""
        try:
            # Try to extract from OpenAI error response
            if hasattr(error, "response") and hasattr(error.response, "headers"):
                headers = error.response.headers
                retry_after = headers.get("retry-after")
                if retry_after:
                    return int(retry_after)

                reset_at = headers.get("x-ratelimit-reset")
                if reset_at:
                    try:
                        if str(reset_at).isdigit():
                            wait_seconds = int(reset_at) - int(time.time())
                        else:
                            wait_seconds = int(
                                parsedate_to_datetime(str(reset_at)).timestamp()
                                - time.time()
                            )
                        if wait_seconds > 0:
                            return min(wait_seconds, 60)
                    except Exception:
                        pass

            # Fallback to parsing error message
            error_str = str(error)
            if "retry after" in error_str.lower():
                import re

                match = re.search(r"retry after (\d+)", error_str.lower())
                if match:
                    return int(match.group(1))

        except Exception:
            pass

        # Default backoff for rate limits
        return self._default_backoff_seconds(attempt)

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

    def _calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate request cost based on token counts."""
        prompt_rate = float(os.getenv("OPENAI_PROMPT_COST_PER_1K", "0")) / 1000
        completion_rate = float(os.getenv("OPENAI_COMPLETION_COST_PER_1K", "0")) / 1000
        return prompt_tokens * prompt_rate + completion_tokens * completion_rate

    def generate_text(self, prompt: str, **kwargs) -> str:
        """Generate text using OpenAI API."""
        t0 = time.time()

        # Check initialization status
        if self.initialization_error:
            raise GenerationFailed(self.initialization_error)

        if not self.client:
            raise GenerationFailed("OpenAI client not initialized")

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
            # Strip parameters that are not supported by the OpenAI completions API
            sanitized_kwargs = {
                k: v for k, v in kwargs.items() 
                if k not in ["stream", "provider", "timeout_ms"]
            }
            completion_kwargs.update(sanitized_kwargs)

            def _generate():
                return self.client.chat.completions.create(**completion_kwargs)

            response = self._retry_with_backoff(_generate)
            text = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            if usage:
                prompt_t = getattr(usage, "prompt_tokens", 0)
                completion_t = getattr(usage, "completion_tokens", 0)
                total_t = getattr(usage, "total_tokens", 0)
                self.last_usage = {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": completion_t,
                    "total_tokens": total_t,
                    "cost": self._calculate_cost(prompt_t, completion_t),
                }
            else:
                self.last_usage = {}

            record_llm_metric(
                "generate_text", time.time() - t0, True, self.provider_name
            )
            return text

        except Exception as ex:
            record_llm_metric(
                "generate_text",
                time.time() - t0,
                False,
                self.provider_name,
                error=str(ex),
            )

            # Provide more specific error messages
            error_msg = str(ex).lower()
            if "api key" in error_msg or "unauthorized" in error_msg:
                raise GenerationFailed(
                    f"Invalid {self.display_name} API key. Check your {self.api_key_env_var} environment variable."
                )
            elif "rate limit" in error_msg or "quota" in error_msg:
                raise GenerationFailed(
                    f"{self.display_name} rate limit exceeded or quota reached. Please try again later."
                )
            elif "model" in error_msg and "not found" in error_msg:
                raise GenerationFailed(
                    f"Model '{model}' not available. Check available models."
                )
            else:
                raise GenerationFailed(f"{self.display_name} generation failed: {ex}")

    def stream_generate(self, prompt: str, **kwargs) -> Iterator[str]:
        """Generate text with streaming support."""
        # Check initialization status
        if self.initialization_error:
            raise GenerationFailed(self.initialization_error)

        if not self.client:
            raise GenerationFailed("OpenAI client not initialized")

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
                    f"Invalid {self.display_name} API key. Check your {self.api_key_env_var} environment variable."
                )
            elif "rate limit" in error_msg:
                raise GenerationFailed(
                    f"{self.display_name} rate limit exceeded. Please try again later."
                )
            else:
                raise GenerationFailed(f"{self.display_name} streaming failed: {ex}")

    def embed(self, text: Union[str, List[str]], **kwargs) -> List[float]:
        """Generate embeddings using OpenAI embeddings API."""
        t0 = time.time()

        # Check initialization status
        if self.initialization_error:
            raise EmbeddingFailed(self.initialization_error)

        if not self.client:
            raise EmbeddingFailed("OpenAI client not initialized")

        try:
            # Use embedding model
            model = kwargs.get("embedding_model", "text-embedding-3-small")

            def _embed():
                return self.client.embeddings.create(model=model, input=text)

            response = self._retry_with_backoff(_embed)
            if isinstance(text, str):
                embeddings = response.data[0].embedding
            else:
                embeddings = [item.embedding for item in response.data]

            usage = getattr(response, "usage", None)
            if usage:
                prompt_t = getattr(usage, "prompt_tokens", 0)
                self.last_usage = {
                    "prompt_tokens": prompt_t,
                    "completion_tokens": 0,
                    "total_tokens": prompt_t,
                    "cost": self._calculate_cost(prompt_t, 0),
                }
            else:
                self.last_usage = {}

            record_llm_metric("embed", time.time() - t0, True, self.provider_name)
            return embeddings

        except Exception as ex:
            record_llm_metric(
                "embed", time.time() - t0, False, self.provider_name, error=str(ex)
            )

            error_msg = str(ex).lower()
            if "api key" in error_msg or "unauthorized" in error_msg:
                raise EmbeddingFailed(
                    f"Invalid {self.display_name} API key. Check your {self.api_key_env_var} environment variable."
                )
            elif "rate limit" in error_msg:
                raise EmbeddingFailed(
                    f"{self.display_name} rate limit exceeded. Please try again later."
                )
            else:
                raise EmbeddingFailed(f"{self.display_name} embedding failed: {ex}")

    def get_models(self) -> List[str]:
        """Get list of available models from OpenAI with fallback to static list."""
        # Skip network calls in offline/development mode
        offline_mode = os.getenv("KARI_OPENAI_OFFLINE", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        if offline_mode:
            logger.info(
                f"{self.display_name} offline mode enabled, using static model list"
            )
            return self._get_common_models()

        try:
            if self.initialization_error or not self.client:
                # Return common models as fallback
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
            logger.warning(f"Could not fetch {self.display_name} models: {ex}")
            return self._get_common_models()

    def _get_common_models(self) -> List[str]:
        """Get list of common provider models."""
        return list(self.provider_defaults["common_models"])

    def get_provider_info(self) -> Dict[str, Any]:
        """Get provider metadata with initialization status."""
        try:
            models = self.get_models()
        except Exception:
            models = []

        return {
            "name": self.provider_name,
            "model": self.model,
            "base_url": self.base_url or str(self.provider_defaults["base_url"]),
            "health_url": self.health_url,
            "has_api_key": bool(self.api_key),
            "api_key_valid": self.initialization_error is None
            and self.client is not None,
            "initialization_error": self.initialization_error,
            "available_models": models,
            "supports_streaming": True,
            "supports_embeddings": True,
            "supports_function_calling": True,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }

    def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check on OpenAI API."""
        if self.provider_name == "builtin_vllm":
            base_url = (self.base_url or "").rstrip("/")
            health_url = (
                self.health_url
                or os.getenv("KAREN_BUILTIN_VLLM_HEALTH_URL")
                or (base_url.removesuffix("/v1") + "/health" if base_url else "")
            )
            served_model = (
                os.getenv("KAREN_BUILTIN_VLLM_SERVED_MODEL_NAME")
                or self.model
                or "auto"
            )
            result: Dict[str, Any] = {
                "provider": self.provider_name,
                "runtime_engine": "vllm",
                "base_url": base_url,
                "health_url": health_url,
                "default_model": served_model,
                "model_tested": served_model,
                "initialization_status": "success"
                if not self.initialization_error
                else "failed",
            }
            if self.initialization_error:
                result.update(
                    {
                        "status": "unhealthy",
                        "error": self.initialization_error,
                        "health_endpoint_ok": False,
                        "models_endpoint_ok": False,
                        "served_model_available": False,
                    }
                )
                return result
            if not base_url or not health_url:
                result.update(
                    {
                        "status": "unhealthy",
                        "error": "builtin_vllm requires base_url and health_url",
                        "health_endpoint_ok": False,
                        "models_endpoint_ok": False,
                        "served_model_available": False,
                    }
                )
                return result

            try:
                import httpx

                health_response = httpx.get(health_url, timeout=5.0)
                result["health_endpoint_ok"] = health_response.status_code == 200
                result["health_status_code"] = health_response.status_code

                models_response = httpx.get(f"{base_url}/models", timeout=5.0)
                result["models_endpoint_ok"] = models_response.status_code == 200
                result["models_status_code"] = models_response.status_code
                available_models: List[str] = []
                if models_response.status_code == 200:
                    models_payload = models_response.json()
                    available_models = [
                        str(item.get("id"))
                        for item in models_payload.get("data", [])
                        if item.get("id")
                    ]
                result["available_models"] = available_models
                result["served_model_available"] = served_model in available_models

                if (
                    result["health_endpoint_ok"]
                    and result["models_endpoint_ok"]
                    and result["served_model_available"]
                ):
                    result.update(
                        {
                            "status": "healthy",
                            "message": "builtin_vllm server is reachable and served model is available",
                            "connectivity": "ok",
                        }
                    )
                else:
                    missing = []
                    if not result["health_endpoint_ok"]:
                        missing.append("health_endpoint")
                    if not result["models_endpoint_ok"]:
                        missing.append("models_endpoint")
                    if not result["served_model_available"]:
                        missing.append("served_model")
                    result.update(
                        {
                            "status": "unhealthy",
                            "error": "builtin_vllm health failed: "
                            + ", ".join(missing),
                            "connectivity": "failed",
                        }
                    )
                return result
            except Exception as e:
                result.update(
                    {
                        "status": "unhealthy",
                        "error": f"builtin_vllm unreachable at {health_url or base_url}: {e}",
                        "health_endpoint_ok": False,
                        "models_endpoint_ok": False,
                        "served_model_available": False,
                        "connectivity": "failed",
                    }
                )
                return result

        if self.provider_name == "builtin_transformers":
            # For local providers, check if the server is actually reachable if it has a base_url
            if self.base_url or self.health_url:
                try:
                    import httpx
                    # Prioritize health_url if available, otherwise fallback to /models on base_url
                    url = self.health_url or f"{self.base_url.rstrip('/')}/models"
                    response = httpx.get(url, timeout=2.0)
                    if response.status_code == 200:
                        return {
                            "status": "healthy",
                            "provider": self.provider_name,
                            "model_tested": self.model,
                            "message": f"Local provider reachable at {url}",
                            "initialization_status": "success"
                        }
                    else:
                        return {
                            "status": "unhealthy",
                            "provider": self.provider_name,
                            "error": f"Local provider returned status {response.status_code} at {url}",
                            "initialization_status": "failed"
                        }
                except Exception as e:
                    return {
                        "status": "unhealthy",
                        "provider": self.provider_name,
                        "error": f"Local provider unreachable at {self.health_url or self.base_url}: {e}",
                        "initialization_status": "failed"
                    }
            
            # Default to healthy for purely in-process or localhost (best-effort)
            return {
                "status": "healthy",
                "provider": self.provider_name,
                "model_tested": self.model,
                "message": "Local fallback provider available",
                "initialization_status": "success" if not self.initialization_error else "lazy-loaded"
            }

        # Check initialization status first
        if self.initialization_error:
            return {
                "status": "unhealthy",
                "error": self.initialization_error,
                "provider": self.provider_name,
                "initialization_status": "failed",
            }

        if not self.client:
            return {
                "status": "unhealthy",
                "error": f"{self.display_name} client not initialized",
                "provider": self.provider_name,
                "initialization_status": "failed",
            }

        try:
            start_time = time.time()

            # Test API connectivity with minimal request
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=1,
            )

            response_time = time.time() - start_time

            health_result = {
                "status": "healthy",
                "provider": self.provider_name,
                "response_time": response_time,
                "model_tested": self.model,
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

            # Add Model Library compatibility check
            try:
                from ai_karen_engine.services.models.compatibility.provider_model_compatibility import (
                    ProviderModelCompatibilityService,
                )

                compatibility_service = ProviderModelCompatibilityService()
                validation = compatibility_service.validate_provider_model_setup(
                    self.provider_name
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
                "provider": self.provider_name,
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

    def validate_config(self) -> Dict[str, Any]:
        """Validate provider configuration."""
        if self.provider_name in ["builtin_vllm", "builtin_transformers"]:
            # Local providers are always considered valid for config purposes
            # their actual health is tracked via ping/health_check
            return {"valid": True, "message": "Local provider configuration valid"}

        if not self.api_key:
            return {"valid": False, "error": f"No {self.display_name} API key provided"}

        if self.initialization_error:
            # Check if this is a local provider that might be lazy-loaded
            if self.provider_name in ["local_gguf", "local_gguf_optimized"]:
                return {"valid": True, "message": "Local provider (GGUF) config valid"}
            return {"valid": False, "error": self.initialization_error}

        return {"valid": True, "message": "Configuration valid"}

    # Lightweight status helpers -------------------------------------------------

    def ping(self) -> bool:
        """Return True if the provider responds to a minimal request."""
        try:
            return self.health_check().get("status") == "healthy"
        except Exception:
            return False

    def available_models(self) -> list[str]:
        """Return a best-effort list of models for this provider."""
        try:
            return self.get_models()
        except Exception:
            return [self.model]

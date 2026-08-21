"""
Gemini LLM provider adapter for Karen.

Responsibilities:
- Initialize the Gemini SDK lazily.
- Generate text.
- Stream text.
- Generate embeddings.
- Discover live generateContent-capable models.
- Report honest provider health and metadata.

Non-responsibilities:
- Global fallback routing.
- UI model selection.
- Fabricated degraded responses.
- Runtime provider orchestration.
"""

from __future__ import annotations

import logging
import os
import random
import importlib
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

from ai_karen_engine.integrations.llm_utils import (
    EmbeddingFailed,
    GenerationFailed,
    LLMProviderBase,
    record_llm_metric,
)

logger = logging.getLogger("kari.gemini_provider")


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_EMBEDDING_MODEL = "models/embedding-001"

STATIC_GENERATION_MODELS = [
    "gemini-1.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3-flash",
    "gemini-3-pro",
]

DEFAULT_SAFETY_SETTINGS = {
    "HARM_CATEGORY_HARASSMENT": "BLOCK_MEDIUM_AND_ABOVE",
    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_MEDIUM_AND_ABOVE",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_MEDIUM_AND_ABOVE",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_MEDIUM_AND_ABOVE",
}


@dataclass(frozen=True)
class ErrorClassification:
    error_type: str
    user_message: str
    retryable: bool


class GeminiProvider(LLMProviderBase):
    """
    Gemini provider adapter.

    This class is intentionally limited to provider-level behavior. Runtime routing,
    global fallback order, degraded-mode response policy, and UI provider/model
    truth must remain owned by Karen's central runtime/provider registry.
    """

    def __init__(
        self,
        model: str = DEFAULT_GEMINI_MODEL,
        api_key: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 2,
        safety_settings: Optional[Dict[str, str]] = None,
    ) -> None:
        self.model = self._normalize_model_name(model) or DEFAULT_GEMINI_MODEL
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        self.timeout = max(1, int(timeout or 30))
        self.max_retries = max(1, int(max_retries or 1))
        self.transport = (os.getenv("KARI_GEMINI_TRANSPORT") or "rest").strip() or "rest"

        self.initialization_error: Optional[str] = None
        self.genai: Optional[Any] = None

        self.safety_settings = safety_settings or dict(DEFAULT_SAFETY_SETTINGS)

        self._model_cache: List[str] = []
        self._model_cache_ts: float = 0.0
        self._model_cache_source: str = "unavailable"
        self._model_cache_error: Optional[str] = None
        self._model_cache_ttl_seconds = self._env_int(
            "KARI_GEMINI_MODEL_CACHE_TTL_SECONDS",
            300,
            minimum=0,
            maximum=86_400,
        )

        self._validate_on_init = self._env_bool("KARI_GEMINI_VALIDATE_ON_INIT", False)

    @staticmethod
    def _env_bool(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _env_int(
        name: str,
        default: int,
        minimum: Optional[int] = None,
        maximum: Optional[int] = None,
    ) -> int:
        raw = os.getenv(name)
        if raw is None or raw.strip() == "":
            value = default
        else:
            try:
                value = int(raw)
            except ValueError:
                logger.warning(
                    "Invalid integer env value for %s. Using default=%s.",
                    name,
                    default,
                )
                value = default

        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    @property
    def offline_mode(self) -> bool:
        return self._env_bool("KARI_GEMINI_OFFLINE", False)

    @staticmethod
    def _normalize_model_name(model: Optional[str]) -> str:
        if model is None:
            return ""
        normalized = str(model).strip()
        while normalized.startswith("models/"):
            normalized = normalized[len("models/") :]
        return normalized.strip()

    @staticmethod
    def _qualified_model_name(model: str) -> str:
        normalized = GeminiProvider._normalize_model_name(model)
        return f"models/{normalized}" if normalized else ""

    def _ensure_initialized(self) -> None:
        if self.genai is None and self.initialization_error is None:
            self._initialize_client()

    def _initialize_client(self) -> None:
        try:
            self.genai = importlib.import_module("google.generativeai")

            if not self.api_key and not self.offline_mode:
                self.initialization_error = (
                    "No Gemini API key configured. Set GEMINI_API_KEY or enable "
                    "KARI_GEMINI_OFFLINE=true for offline metadata-only mode."
                )
                logger.info("Gemini provider unavailable: missing API key.")
                return

            if self.api_key:
                configure = getattr(self.genai, "configure", None)
                if configure is None:
                    raise AttributeError("google.generativeai.configure is unavailable")
                configure(api_key=self.api_key, transport=self.transport)

            if self._validate_on_init and not self.offline_mode:
                self._validate_api_key()

        except ImportError:
            self.initialization_error = (
                "Google Generative AI package is not installed. Install "
                "google-generativeai in the API environment."
            )
            logger.warning(self.initialization_error)
        except Exception as ex:
            self.initialization_error = f"Gemini client initialization failed: {ex}"
            logger.error("Gemini client initialization failed: %s", ex)

    def _validate_api_key(self) -> None:
        if self.offline_mode:
            logger.info("Gemini offline mode enabled. Skipping API key validation.")
            return

        if not self.genai:
            self.initialization_error = "Gemini client not initialized."
            return

        if not self.api_key:
            self.initialization_error = "No Gemini API key configured."
            return

        try:
            next(iter(self.genai.list_models()), None)
            logger.info("Gemini API key validation succeeded.")
        except Exception as ex:
            classified = self._classify_error(ex)
            if classified.error_type == "authentication_error":
                self.initialization_error = classified.user_message
                logger.error("Gemini API key validation failed: %s", classified.user_message)
                return

            logger.warning(
                "Gemini API key validation deferred due to non-auth error: %s",
                ex,
            )

    def _classify_error(self, error: Exception) -> ErrorClassification:
        raw = str(error) or error.__class__.__name__
        lowered = raw.lower()

        auth_patterns = (
            "api key",
            "unauthorized",
            "unauthenticated",
            "permission denied",
            "forbidden",
            "invalid credential",
            "401",
            "403",
        )
        safety_patterns = (
            "safety",
            "blocked",
            "block_reason",
            "harm_category",
            "prohibited",
        )
        model_patterns = (
            "model not found",
            "not found",
            "404",
            "unsupported model",
            "unknown model",
        )
        invalid_request_patterns = (
            "invalid request",
            "bad request",
            "invalid argument",
            "400",
        )
        rate_limit_patterns = (
            "quota",
            "rate limit",
            "too many requests",
            "resource exhausted",
            "429",
        )
        transient_patterns = (
            "timeout",
            "deadline exceeded",
            "internal server error",
            "service unavailable",
            "server error",
            "bad gateway",
            "gateway timeout",
            "connection",
            "503",
            "504",
            "502",
            "500",
        )

        if any(pattern in lowered for pattern in auth_patterns):
            return ErrorClassification(
                error_type="authentication_error",
                user_message="Invalid or unauthorized Gemini API key.",
                retryable=False,
            )

        if any(pattern in lowered for pattern in safety_patterns):
            return ErrorClassification(
                error_type="safety_filter_error",
                user_message="Content blocked by Gemini safety filters.",
                retryable=False,
            )

        if any(pattern in lowered for pattern in model_patterns):
            return ErrorClassification(
                error_type="model_error",
                user_message="Requested Gemini model is not available.",
                retryable=False,
            )

        if any(pattern in lowered for pattern in invalid_request_patterns):
            return ErrorClassification(
                error_type="invalid_request_error",
                user_message="Gemini rejected the request as invalid.",
                retryable=False,
            )

        if any(pattern in lowered for pattern in rate_limit_patterns):
            return ErrorClassification(
                error_type="rate_limit_error",
                user_message="Gemini quota exceeded or rate limited.",
                retryable=True,
            )

        if any(pattern in lowered for pattern in transient_patterns):
            return ErrorClassification(
                error_type="connectivity_error",
                user_message="Temporary Gemini connectivity or service error.",
                retryable=True,
            )

        return ErrorClassification(
            error_type="unknown_error",
            user_message=raw,
            retryable=False,
        )

    def _retry_with_backoff(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as ex:
                last_exception = ex
                classified = self._classify_error(ex)

                if not classified.retryable:
                    raise ex

                if attempt >= self.max_retries - 1:
                    break

                wait_seconds = min(8.0, float(2**attempt)) + random.uniform(0.0, 0.25)
                logger.warning(
                    "Gemini retryable error. attempt=%s max_retries=%s error_type=%s wait_seconds=%.2f",
                    attempt + 1,
                    self.max_retries,
                    classified.error_type,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        if last_exception is not None:
            logger.error(
                "Gemini operation failed after retries. max_retries=%s error_type=%s",
                self.max_retries,
                self._classify_error(last_exception).error_type,
            )
            raise last_exception

        raise RuntimeError("Gemini retry loop exited without executing the operation.")

    def _prepare_safety_settings(self) -> List[Dict[str, Any]]:
        if not self.genai:
            return []

        prepared: List[Dict[str, Any]] = []

        for category, threshold in self.safety_settings.items():
            prepared.append(
                {
                    "category": getattr(self.genai.types.HarmCategory, category, category),
                    "threshold": getattr(
                        self.genai.types.HarmBlockThreshold,
                        threshold,
                        threshold,
                    ),
                }
            )

        return prepared

    def _cache_is_fresh(self) -> bool:
        if self._model_cache_ttl_seconds <= 0:
            return False
        if not self._model_cache:
            return False
        return (time.time() - self._model_cache_ts) < self._model_cache_ttl_seconds

    def _set_model_cache(
        self,
        models: List[str],
        source: str,
        error: Optional[str] = None,
    ) -> List[str]:
        normalized = sorted({self._normalize_model_name(model) for model in models if model})
        self._model_cache = normalized
        self._model_cache_ts = time.time()
        self._model_cache_source = source
        self._model_cache_error = error
        return normalized

    def _discover_generation_models(self, force_refresh: bool = False) -> List[str]:
        """
        Return live generateContent-capable Gemini models.

        Static fallback names are not returned from this method unless offline mode
        is explicitly enabled. This keeps runtime selection honest.
        """
        if self.offline_mode:
            return self._set_model_cache(
                STATIC_GENERATION_MODELS,
                source="offline_static",
                error=None,
            )

        if not force_refresh and self._cache_is_fresh():
            return list(self._model_cache)

        self._ensure_initialized()

        if self.initialization_error or not self.genai:
            return self._set_model_cache(
                [],
                source="unavailable",
                error=self.initialization_error or "Gemini client not initialized.",
            )

        genai = self.genai
        if genai is None:
            return self._set_model_cache(
                [],
                source="unavailable",
                error="Gemini client not initialized.",
            )

        def _list_models() -> List[str]:
            models: List[str] = []
            for model in genai.list_models():
                methods = getattr(model, "supported_generation_methods", []) or []
                name = self._normalize_model_name(getattr(model, "name", ""))
                if name and "generateContent" in methods:
                    models.append(name)
            return models

        try:
            discovered = self._retry_with_backoff(_list_models)
            return self._set_model_cache(
                discovered,
                source="live_discovery",
                error=None,
            )
        except Exception as ex:
            classified = self._classify_error(ex)
            if classified.error_type == "authentication_error":
                self.initialization_error = classified.user_message

            return self._set_model_cache(
                [],
                source="unavailable",
                error=str(ex),
            )

    @staticmethod
    def _model_rank(name: str, requested_preview: bool = False) -> Tuple[int, int, int, int, int, str]:
        lowered = name.lower()
        preview_like = any(token in lowered for token in ("preview", "experimental", "exp"))

        stable_score = 1 if requested_preview or not preview_like else 0
        pro_score = 1 if "pro" in lowered else 0
        flash_score = 1 if "flash" in lowered else 0
        lite_score = 0 if "lite" in lowered else 1
        latest_score = 1 if "latest" in lowered else 0

        numeric_score = 0
        for token in lowered.replace(".", "-").split("-"):
            if token.isdigit():
                numeric_score = max(numeric_score, int(token))

        return (
            stable_score,
            pro_score,
            lite_score,
            latest_score,
            numeric_score + flash_score,
            lowered,
        )

    def _resolve_generation_model(self, requested_model: Optional[str]) -> str:
        normalized = self._normalize_model_name(requested_model or self.model)
        if not normalized:
            normalized = self.model or DEFAULT_GEMINI_MODEL

        discovered = self._discover_generation_models()

        if discovered:
            if normalized in discovered:
                return self._qualified_model_name(normalized)

            requested_preview = any(
                token in normalized.lower()
                for token in ("preview", "experimental", "exp")
            )

            candidates = [
                name
                for name in discovered
                if name.startswith(f"{normalized}-") or normalized in name
            ]

            if not candidates and normalized.startswith("gemini-1.5-flash"):
                candidates = [name for name in discovered if name.startswith("gemini-1.5-flash")]

            if not candidates and normalized.startswith("gemini-1.5-pro"):
                candidates = [name for name in discovered if name.startswith("gemini-1.5-pro")]

            if not candidates and normalized.startswith("gemini-2.0-flash"):
                candidates = [name for name in discovered if name.startswith("gemini-2.0-flash")]

            if not candidates and normalized.startswith("gemini-2.5-flash"):
                candidates = [name for name in discovered if name.startswith("gemini-2.5-flash")]

            if not candidates and normalized.startswith("gemini-2.5-pro"):
                candidates = [name for name in discovered if name.startswith("gemini-2.5-pro")]

            if candidates:
                resolved = sorted(
                    candidates,
                    key=lambda item: self._model_rank(item, requested_preview=requested_preview),
                    reverse=True,
                )[0]
                logger.info(
                    "Resolved Gemini model alias. requested_model=%s resolved_model=%s",
                    normalized,
                    resolved,
                )
                return self._qualified_model_name(resolved)

            if self._model_cache_source == "live_discovery":
                raise GenerationFailed(
                    f"Gemini model '{normalized}' was not found in live discovery."
                )

        if self._model_cache_source == "offline_static":
            return self._qualified_model_name(normalized)

        if self._model_cache_error:
            logger.warning(
                "Gemini model discovery unavailable. requested_model=%s discovery_error=%s",
                normalized,
                self._model_cache_error,
            )

        return self._qualified_model_name(normalized)

    @staticmethod
    def _safe_getattr(value: Any, attr: str, default: Any = None) -> Any:
        try:
            return getattr(value, attr, default)
        except Exception:
            return default

    def _get_block_reason(self, response: Any) -> Optional[str]:
        prompt_feedback = self._safe_getattr(response, "prompt_feedback")
        if not prompt_feedback:
            return None

        block_reason = self._safe_getattr(prompt_feedback, "block_reason")
        if block_reason:
            return str(block_reason)

        return None

    def _extract_text_from_parts(self, parts: Any) -> str:
        extracted: List[str] = []

        if not parts:
            return ""

        for part in parts:
            text = self._safe_getattr(part, "text", None)
            if text:
                extracted.append(str(text))

        return "".join(extracted).strip()

    def _extract_response_text(self, response: Any) -> str:
        block_reason = self._get_block_reason(response)
        if block_reason:
            raise GenerationFailed(f"Content blocked by Gemini safety filters: {block_reason}")

        try:
            direct_text = self._safe_getattr(response, "text", None)
            if direct_text:
                return str(direct_text).strip()
        except Exception:
            pass

        candidates = self._safe_getattr(response, "candidates", []) or []
        collected: List[str] = []

        for candidate in candidates:
            content = self._safe_getattr(candidate, "content")
            parts = self._safe_getattr(content, "parts", []) if content else []
            candidate_text = self._extract_text_from_parts(parts)
            if candidate_text:
                collected.append(candidate_text)

        text = "".join(collected).strip()
        if text:
            return text

        finish_reasons = []
        for candidate in candidates:
            finish_reason = self._safe_getattr(candidate, "finish_reason")
            if finish_reason:
                finish_reasons.append(str(finish_reason))

        if finish_reasons:
            raise GenerationFailed(
                "Gemini returned no text. finish_reason="
                + ",".join(sorted(set(finish_reasons)))
            )

        raise GenerationFailed("Gemini returned no usable text.")

    def _extract_stream_chunk_text(self, chunk: Any) -> str:
        block_reason = self._get_block_reason(chunk)
        if block_reason:
            raise GenerationFailed(f"Content blocked by Gemini safety filters: {block_reason}")

        try:
            direct_text = self._safe_getattr(chunk, "text", None)
            if direct_text:
                return str(direct_text)
        except Exception:
            pass

        candidates = self._safe_getattr(chunk, "candidates", []) or []
        collected: List[str] = []

        for candidate in candidates:
            content = self._safe_getattr(candidate, "content")
            parts = self._safe_getattr(content, "parts", []) if content else []
            text = self._extract_text_from_parts(parts)
            if text:
                collected.append(text)

        return "".join(collected)

    def _build_generation_config(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        generation_config = {
            "temperature": kwargs.pop("temperature", 0.7),
            "top_p": kwargs.pop("top_p", 0.8),
            "top_k": kwargs.pop("top_k", 40),
            "max_output_tokens": kwargs.pop(
                "max_tokens",
                kwargs.pop("max_output_tokens", 1000),
            ),
        }

        ignored = {
            "messages",
            "stream",
            "safety_settings",
            "model",
            "request_id",
            "correlation_id",
            "user_id",
            "tenant_id",
            "session_id",
            "conversation_id",
        }

        generation_config.update(
            {key: value for key, value in kwargs.items() if key not in ignored}
        )
        return generation_config

    def _format_generation_failure(
        self,
        ex: Exception,
        operation: str,
        model_name: Optional[str] = None,
    ) -> GenerationFailed:
        if isinstance(ex, GenerationFailed):
            return ex

        classified = self._classify_error(ex)

        if classified.error_type == "model_error" and model_name:
            return GenerationFailed(
                f"Gemini {operation} failed: model '{model_name}' is not available."
            )

        return GenerationFailed(f"Gemini {operation} failed: {classified.user_message}")

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        t0 = time.time()
        model_name: Optional[str] = None

        self._ensure_initialized()

        if self.initialization_error:
            raise GenerationFailed(self.initialization_error)

        if not self.genai:
            raise GenerationFailed("Gemini client not initialized.")

        try:
            requested_model_name = kwargs.pop("model", self.model)
            model_name = self._resolve_generation_model(requested_model_name)
            model = self.genai.GenerativeModel(model_name)

            generation_config = self._build_generation_config(kwargs)
            safety_settings = kwargs.get("safety_settings", self._prepare_safety_settings())

            def _generate() -> str:
                response = model.generate_content(
                    prompt,
                    generation_config=generation_config,
                    safety_settings=safety_settings,
                    request_options={"timeout": self.timeout},
                )
                text = self._extract_response_text(response)

                logger.debug(
                    "Gemini generation succeeded. requested_model=%s resolved_model=%s latency_ms=%.2f response_length=%s",
                    requested_model_name,
                    model_name,
                    (time.time() - t0) * 1000,
                    len(text),
                )
                return text

            text = self._retry_with_backoff(_generate)
            record_llm_metric("generate_text", time.time() - t0, True, "gemini")
            return text

        except Exception as ex:
            record_llm_metric(
                "generate_text",
                time.time() - t0,
                False,
                "gemini",
                error=str(ex),
            )
            raise self._format_generation_failure(ex, "generation", model_name)

    def stream_generate(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        t0 = time.time()
        model_name: Optional[str] = None

        self._ensure_initialized()

        if self.initialization_error:
            raise GenerationFailed(self.initialization_error)

        if not self.genai:
            raise GenerationFailed("Gemini client not initialized.")

        try:
            requested_model_name = kwargs.pop("model", self.model)
            model_name = self._resolve_generation_model(requested_model_name)

            logger.debug(
                "Gemini stream starting. requested_model=%s resolved_model=%s",
                requested_model_name,
                model_name,
            )

            model = self.genai.GenerativeModel(model_name)
            generation_config = self._build_generation_config(kwargs)
            safety_settings = kwargs.get("safety_settings", self._prepare_safety_settings())

            def _stream() -> Any:
                return model.generate_content(
                    prompt,
                    generation_config=generation_config,
                    safety_settings=safety_settings,
                    stream=True,
                    request_options={"timeout": self.timeout},
                )

            stream = self._retry_with_backoff(_stream)
            yielded_any = False
            total_chars = 0

            for chunk in stream:
                text = self._extract_stream_chunk_text(chunk)
                if not text:
                    continue

                yielded_any = True
                total_chars += len(text)
                yield text

            if not yielded_any:
                raise GenerationFailed("Gemini stream produced no usable text.")

            record_llm_metric("stream_generate", time.time() - t0, True, "gemini")
            logger.debug(
                "Gemini stream completed. requested_model=%s resolved_model=%s latency_ms=%.2f response_length=%s",
                requested_model_name,
                model_name,
                (time.time() - t0) * 1000,
                total_chars,
            )

        except Exception as ex:
            record_llm_metric(
                "stream_generate",
                time.time() - t0,
                False,
                "gemini",
                error=str(ex),
            )
            raise self._format_generation_failure(ex, "streaming", model_name)

    def embed(self, text: Union[str, List[str]], **kwargs: Any) -> Any:
        t0 = time.time()

        self._ensure_initialized()

        if self.initialization_error:
            raise EmbeddingFailed(self.initialization_error)

        if not self.genai:
            raise EmbeddingFailed("Gemini client not initialized.")

        embedding_model = kwargs.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
        genai = self.genai
        if genai is None:
            raise EmbeddingFailed("Gemini client not initialized.")

        try:
            def _embed_one(value: str) -> List[float]:
                result = genai.embed_content(
                    model=embedding_model,
                    content=value,
                    task_type=kwargs.get("task_type", "retrieval_document"),
                    request_options={"timeout": self.timeout},
                )
                embedding = result.get("embedding") if isinstance(result, dict) else None
                if not embedding:
                    raise EmbeddingFailed("Gemini returned no embedding.")
                return embedding

            def _embed() -> Any:
                if isinstance(text, str):
                    return _embed_one(text)
                return [_embed_one(item) for item in text]

            embeddings = self._retry_with_backoff(_embed)

            record_llm_metric("embed", time.time() - t0, True, "gemini")
            return embeddings

        except Exception as ex:
            record_llm_metric(
                "embed",
                time.time() - t0,
                False,
                "gemini",
                error=str(ex),
            )

            if isinstance(ex, EmbeddingFailed):
                raise ex

            classified = self._classify_error(ex)
            raise EmbeddingFailed(f"Gemini embedding failed: {classified.user_message}")

    def get_models(self, force_refresh: bool = False) -> List[str]:
        """
        Return models that the runtime may display for this provider.

        Live discovery is preferred. Static models are returned only in explicit
        offline metadata mode. Missing keys and failed initialization return an
        empty list so the UI/runtime does not mistake Gemini for available.
        """
        if self.offline_mode:
            return list(STATIC_GENERATION_MODELS)

        models = self._discover_generation_models(force_refresh=force_refresh)
        if models:
            return models

        return []

    def _get_common_models(self) -> List[str]:
        """
        Return static Gemini family names for metadata/offline display only.

        Do not treat this list as proof that the current API key can call these
        models. Runtime execution must use live discovery or a direct successful
        generation call.
        """
        return list(STATIC_GENERATION_MODELS)

    def get_provider_info(self) -> Dict[str, Any]:
        self._ensure_initialized()

        configured = bool(self.api_key) or self.offline_mode
        initialized = self.genai is not None and self.initialization_error is None

        try:
            models = self.get_models()
        except Exception as ex:
            models = []
            self._model_cache_error = str(ex)

        model_source = self._model_cache_source
        available = bool(configured and initialized and models and model_source in {"live_discovery", "offline_static"})

        return {
            "name": "gemini",
            "model": self.model,
            "configured": configured,
            "has_api_key": bool(self.api_key),
            "initialized": initialized,
            "available": available,
            "api_key_valid": bool(self.api_key and initialized and model_source == "live_discovery"),
            "initialization_error": self.initialization_error,
            "available_models": models,
            "model_source": model_source,
            "model_cache_ttl_seconds": self._model_cache_ttl_seconds,
            "model_cache_age_seconds": max(0.0, time.time() - self._model_cache_ts)
            if self._model_cache_ts
            else None,
            "model_discovery_error": self._model_cache_error,
            "supports_streaming": True,
            "supports_embeddings": True,
            "supports_multimodal": True,
            "safety_settings": self.safety_settings,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "transport": self.transport,
            "offline_mode": self.offline_mode,
        }

    def health_check(self) -> Dict[str, Any]:
        start_time = time.time()
        self._ensure_initialized()

        configured = bool(self.api_key) or self.offline_mode
        initialized = self.genai is not None and self.initialization_error is None

        if self.offline_mode:
            models = self.get_models()
            return {
                "status": "degraded",
                "provider": "gemini",
                "configured": configured,
                "initialized": initialized,
                "offline_mode": True,
                "model_tested": None,
                "response_time": time.time() - start_time,
                "model_discovery": {
                    "status": "offline_static",
                    "models_found": len(models),
                    "source": "offline_static",
                    "sample_models": models[:5],
                },
                "warning": "Gemini offline mode is enabled. Models are metadata only.",
            }

        if not configured:
            return {
                "status": "unhealthy",
                "provider": "gemini",
                "configured": False,
                "initialized": initialized,
                "offline_mode": False,
                "error_type": "configuration_error",
                "error": "No Gemini API key configured.",
                "model_discovery": {
                    "status": "unavailable",
                    "models_found": 0,
                    "source": "unavailable",
                },
            }

        if self.initialization_error:
            return {
                "status": "unhealthy",
                "provider": "gemini",
                "configured": configured,
                "initialized": False,
                "offline_mode": False,
                "error_type": "initialization_error",
                "error": self.initialization_error,
                "model_discovery": {
                    "status": "unavailable",
                    "models_found": 0,
                    "source": "unavailable",
                },
            }

        if not self.genai:
            return {
                "status": "unhealthy",
                "provider": "gemini",
                "configured": configured,
                "initialized": False,
                "offline_mode": False,
                "error_type": "initialization_error",
                "error": "Gemini client not initialized.",
                "model_discovery": {
                    "status": "unavailable",
                    "models_found": 0,
                    "source": "unavailable",
                },
            }

        try:
            discovered = self._discover_generation_models(force_refresh=True)
            discovery_status = "success" if discovered else "empty"

            health_model = self._resolve_generation_model(self.model)
            model = self.genai.GenerativeModel(health_model)
            response = model.generate_content(
                "Hello",
                generation_config={"max_output_tokens": 1},
                request_options={"timeout": self.timeout},
            )
            health_text = self._extract_response_text(response)

            return {
                "status": "healthy",
                "provider": "gemini",
                "configured": configured,
                "initialized": True,
                "offline_mode": False,
                "response_time": time.time() - start_time,
                "model_tested": health_model,
                "response_length": len(health_text),
                "api_key_status": "valid",
                "connectivity": "ok",
                "model_discovery": {
                    "status": discovery_status,
                    "models_found": len(discovered),
                    "source": self._model_cache_source,
                    "sample_models": discovered[:5],
                },
                "capabilities": {
                    "text_generation": True,
                    "streaming": True,
                    "embeddings": True,
                    "multimodal": True,
                    "safety_filtering": True,
                },
            }

        except Exception as ex:
            classified = self._classify_error(ex)
            return {
                "status": "unhealthy",
                "provider": "gemini",
                "configured": configured,
                "initialized": initialized,
                "offline_mode": False,
                "response_time": time.time() - start_time,
                "error_type": classified.error_type,
                "error": classified.user_message,
                "raw_error": str(ex),
                "model_discovery": {
                    "status": "failed" if self._model_cache_error else self._model_cache_source,
                    "models_found": len(self._model_cache),
                    "source": self._model_cache_source,
                    "error": self._model_cache_error,
                    "sample_models": self._model_cache[:5],
                },
            }

    def ping(self) -> bool:
        try:
            return self.health_check().get("status") == "healthy"
        except Exception:
            return False

    def available_models(self) -> List[str]:
        return self.get_models()

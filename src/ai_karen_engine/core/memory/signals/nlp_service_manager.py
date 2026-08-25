"""
Unified NLP service manager for spaCy and DistilBERT integration.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import threading
from collections.abc import AsyncIterator
from typing import Any

from ai_karen_engine.config.config_manager import config_manager
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.memory.signals.distilbert_service import DistilBertService
from ai_karen_engine.core.memory.signals.nlp_config import (
    DistilBertConfig,
    NLPConfig,
    SmallLanguageModelConfig,
    SpacyConfig,
)
from ai_karen_engine.core.memory.signals.nlp_health_monitor import (
    NLPHealthMonitor,
    NLPSystemHealth,
)
from ai_karen_engine.core.memory.signals.spacy_service import (
    ParsedMessage,
    SpacyService,
)
from ai_karen_engine.core.reasoning.synthesis.small_language_model_service import (
    OutlineResult,
    ScaffoldResult,
    SmallLanguageModelService,
    SummaryResult,
)

logger = get_logger(__name__)


class NLPServiceManager:
    """Unified manager for NLP services with configuration and health monitoring."""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.config = self._load_config()

        enable_heavy_helpers = os.getenv(
            "KARI_ENABLE_DEGRADED_HELPERS", ""
        ).lower() in {"1", "true", "yes"}
        if not enable_heavy_helpers:
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            logger.info(
                "DistilBERT will run in offline fallback mode. Set "
                "KARI_ENABLE_DEGRADED_HELPERS=1 to allow full model loading."
            )

        # Initialize services based on configuration
        self.spacy_service = (
            SpacyService(self.config.spacy) if self.config.spacy.enabled else None
        )
        self.distilbert_service = (
            DistilBertService(self.config.distilbert)
            if self.config.distilbert.enabled
            else None
        )
        self.small_language_model_service = (
            SmallLanguageModelService(self.config.small_language_model)
            if self.config.small_language_model.enabled
            else None
        )

        # Initialize health monitor with available services
        self.health_monitor = NLPHealthMonitor(
            self.spacy_service, self.distilbert_service, self.config
        )

        self._initialized = True
        logger.info("NLP Service Manager initialized")

    def _get_nltk_data_path(self) -> str:
        """
        Get standardized NLTK data path following DRY and production best practices.
        Uses a workspace-relative path for maximum reliability in containerized/constrained environments.
        """
        # Prefer workspace-relative path for reliability and permission consistency
        workspace_path = "/mnt/Development/KIRO/AI-Karen/nltk_data"

        # Fallback list for robustness
        paths = [
            workspace_path,
            "/usr/share/nltk_data",
            "/usr/local/share/nltk_data",
            os.path.expanduser("~/nltk_data"),
        ]

        # Return the first one that exists or can be used
        for path in paths:
            if os.path.exists(path) and os.access(path, os.W_OK):
                return path

        # If workspace path doesn't exist but parent is writable, create it
        if not os.path.exists(workspace_path):
            parent_dir = os.path.dirname(workspace_path)
            if os.path.exists(parent_dir) and os.access(parent_dir, os.W_OK):
                try:
                    os.makedirs(workspace_path, exist_ok=True)
                    return workspace_path
                except Exception:
                    pass

        return paths[0]

    async def ensure_assets_ready(self) -> dict[str, Any]:
        """
        Ensure all NLP assets (NLTK, spaCy) are ready.
        Attempts auto-download if resources are missing and enabled.
        """
        results = {
            "spacy": {"status": "unknown", "details": ""},
            "nltk": {"status": "unknown", "details": []},
            "ready": False,
        }

        # 1. Check spaCy
        if self.spacy_service:
            try:
                import spacy

                model_name = self.config.spacy.model_name
                try:
                    spacy.load(model_name)
                    results["spacy"]["status"] = "ready"
                except Exception:
                    if self.config.spacy.download_missing:
                        logger.info(f"Downloading spaCy model: {model_name}")
                        subprocess.run(
                            [sys.executable, "-m", "spacy", "download", model_name],
                            check=True,
                        )
                        results["spacy"]["status"] = "installed"
                    else:
                        results["spacy"]["status"] = "missing"
                        results["spacy"]["details"] = f"Model {model_name} not found"
            except ImportError:
                results["spacy"]["status"] = "error"
                results["spacy"]["details"] = "spaCy not installed"
        else:
            results["spacy"]["status"] = "disabled"

        # 2. Check NLTK
        try:
            import nltk

            nltk_path = self._get_nltk_data_path()
            if nltk_path not in nltk.data.path:
                nltk.data.path.append(nltk_path)

            resources = ["punkt", "stopwords", "wordnet"]
            for resource in resources:
                try:
                    nltk.data.find(
                        f"tokenizers/{resource}"
                        if resource == "punkt"
                        else f"corpora/{resource}"
                    )
                    results["nltk"]["details"].append(
                        {"resource": resource, "status": "ready"}
                    )
                except LookupError:
                    if (
                        os.getenv("KARI_ENABLE_NLTK_DOWNLOADS", "false").lower()
                        == "true"
                    ):
                        logger.info(f"Downloading NLTK resource: {resource}")
                        nltk.download(resource, download_dir=nltk_path, quiet=True)
                        results["nltk"]["details"].append(
                            {"resource": resource, "status": "installed"}
                        )
                    else:
                        results["nltk"]["details"].append(
                            {"resource": resource, "status": "missing"}
                        )

            # Check if all required NLTK resources are available
            nltk_ready = all(
                r["status"] in ("ready", "installed")
                for r in results["nltk"]["details"]
            )
            results["nltk"]["status"] = "ready" if nltk_ready else "degraded"
        except ImportError:
            results["nltk"]["status"] = "error"
            results["nltk"]["details"] = "nltk not installed"

        results["ready"] = (
            results["spacy"]["status"] in ("ready", "installed", "disabled")
        ) and (results["nltk"]["status"] == "ready")
        return results

    async def generate_response(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        provider: str | None = None,
        correlation_id: str | None = None,
        stream: bool = False,
        **kwargs,
    ) -> dict[str, Any]:
        """Delegate generation to the centralized provider system."""
        from ai_karen_engine.integrations.llm_registry import get_registry

        registry = get_registry()

        # Try the specified provider first, then fall back to healthy providers
        requested_provider = provider
        providers_to_try = []
        if requested_provider:
            providers_to_try.append(requested_provider)

        # Add fallback providers in order of preference: local GGUF first, then fallback, then ollama
        fallback_providers = ["local_gguf", "fallback", "ollama"]
        for fallback_provider in fallback_providers:
            if fallback_provider != requested_provider:  # Avoid duplicates
                providers_to_try.append(fallback_provider)

        last_error = None
        failed_providers = []

        for provider_name in providers_to_try:
            try:
                # Skip provider if it already failed
                if provider_name in failed_providers:
                    logger.info(f"Skipping already failed provider: {provider_name}")
                    continue

                provider_instance = registry.get_provider(provider_name)

                if not provider_instance:
                    logger.warning(f"Provider {provider_name} not found in registry")
                    failed_providers.append(provider_name)
                    continue

                # Check if provider is healthy
                health_status = registry.health_check(provider_name)
                is_healthy = health_status.get("status") == "healthy"

                # Allow local GGUF even if health check says unhealthy since we know the model files exist
                if not is_healthy and provider_name not in [
                    "fallback",
                    "local_gguf",
                ]:
                    logger.warning(
                        f"Provider {provider_name} is unhealthy: {health_status.get('error', 'Unknown error')}"
                    )
                    failed_providers.append(provider_name)
                    continue

                # For local GGUF, log but still attempt even if health check fails
                if not is_healthy and provider_name == "local_gguf":
                    logger.warning(
                        f"{provider_name} health check failed: {health_status.get('error', 'Unknown error')}, but attempting anyway since model files exist"
                    )

                logger.info(f"Attempting generation with provider: {provider_name}")
                result = await self._try_generate_with_provider(
                    provider_instance, provider_name, messages, **kwargs
                )

                if result and result.get("success"):
                    logger.info(f"Generation succeeded with provider: {provider_name}")
                    
                    # Track if we used a fallback
                    used_fallback = (requested_provider is not None and provider_name != requested_provider)
                    
                    # Add provider info to result
                    result["provider"] = provider_name
                    result["actual_provider"] = provider_name
                    result["requested_provider"] = requested_provider
                    result["model_id"] = model_id
                    result["used_fallback"] = used_fallback
                    result["is_degraded"] = used_fallback
                    return result
                else:
                    logger.warning(
                        f"Generation failed with provider {provider_name}: {result}"
                    )
                    last_error = result.get("error", f"Provider {provider_name} failed")
                    failed_providers.append(provider_name)

                    # If local GGUF failed with timeout, try fallback immediately
                    if provider_name == "local_gguf" and "timed out" in str(last_error).lower():
                        logger.info(
                            "local_gguf timed out, trying fallback provider immediately"
                        )
                        continue

            except Exception as e:
                logger.error(f"Error with provider {provider_name}: {e}")
                last_error = str(e)
                failed_providers.append(provider_name)
                continue

        # All providers failed
        error_msg = last_error or "All providers failed"
        logger.error(f"All generation attempts failed: {error_msg}")
        logger.error(f"Failed providers: {failed_providers}")

        # If local GGUF was attempted and failed, specifically mention it
        if "local_gguf" in failed_providers:
            error_msg = f"Local model generation failed. {error_msg}"

        return {
            "content": "Error: Generation failed",
            "error": error_msg,
            "success": False,
            "actual_provider": "failed",
            "requested_provider": requested_provider,
            "attempted_providers": providers_to_try,
            "failed_providers": failed_providers,
            "used_fallback": True,
            "is_degraded": True
        }

        try:
            import asyncio
            import inspect

            gen_kwargs = {
                "max_tokens": kwargs.get("max_tokens", 256),
                "temperature": kwargs.get("temperature", 0.7),
            }

            if hasattr(provider_instance, "generate_response") and callable(
                provider_instance.generate_response
            ):
                try:
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda m=messages,
                            g=gen_kwargs: provider_instance.generate_response(m, **g),
                        ),
                        timeout=60.0,
                    )
                    if result and str(result).strip():
                        logger.info(
                            "nlp_service_manager: generate_response succeeded for %s",
                            provider,
                        )
                        return {"content": result, "success": True}
                    logger.warning(
                        "nlp_service_manager: generate_response returned empty for %s",
                        provider,
                    )
                except asyncio.TimeoutError:
                    logger.error("generate_response timed out for %s", provider)
                except Exception as e:
                    logger.warning("generate_response failed for %s: %s", provider, e)

            if hasattr(provider_instance, "generate_text"):
                sig = inspect.signature(provider_instance.generate_text)
                params = sig.parameters
                prompt_param = params.get("prompt")
                accepts_list = False
                if prompt_param:
                    ann = str(prompt_param.annotation)
                    accepts_list = "List" in ann or "Union" in ann

                if accepts_list:
                    try:
                        result = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda m=messages,
                                g=gen_kwargs: provider_instance.generate_text(m, **g),
                            ),
                            timeout=60.0,
                        )
                        if result and str(result).strip():
                            logger.info(
                                "nlp_service_manager: generate_text (list) succeeded for %s",
                                provider,
                            )
                            return {"content": result, "success": True}
                        logger.warning(
                            "nlp_service_manager: generate_text (list) returned empty for %s",
                            provider,
                        )
                    except asyncio.TimeoutError:
                        logger.error("generate_text (list) timed out for %s", provider)
                    except Exception as e:
                        logger.warning(
                            "generate_text (list) failed for %s: %s", provider, e
                        )

                # Fallback to string format if list format failed or not supported
                prompt = "\n".join(
                    [
                        f"{m.get('role', 'user')}: {m.get('content', '')}"
                        for m in messages
                    ]
                )
                try:
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda p=prompt,
                            g=gen_kwargs: provider_instance.generate_text(p, **g),
                        ),
                        timeout=60.0,
                    )
                    if result and str(result).strip():
                        logger.info(
                            "nlp_service_manager: generate_text (string) succeeded for %s",
                            provider,
                        )
                        return {"content": result, "success": True}
                    logger.warning(
                        "nlp_service_manager: generate_text (string) returned empty for %s",
                        provider,
                    )
                    # Don't return empty result, let it fall through to error handling
                except asyncio.TimeoutError:
                    logger.error("Generation timed out for %s", provider)
                    return {
                        "content": "Error: Generation timed out",
                        "error": f"Provider {provider} timed out",
                        "success": False,
                    }
                except Exception as e:
                    logger.error("Generation failed for %s: %s", provider, e)
                    return {
                        "content": "Error: Generation failed",
                        "error": str(e),
                        "success": False,
                    }

            return {
                "content": "Error: Provider does not support text generation",
                "error": f"Provider {provider} missing generate_text method",
                "success": False,
            }
        except Exception as e:
            logger.error("Generation failed for %s: %s", provider, e)
            return {
                "content": "Error: Generation failed",
                "error": str(e),
                "success": False,
            }

    async def _try_generate_with_provider(
        self,
        provider_instance,
        provider_name: str,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> dict[str, Any]:
        """Try generation with a specific provider instance with improved timeout handling."""
        try:
            import asyncio
            import inspect
            import time

            start_time = time.time()
            stream = kwargs.get("stream", False)
            gen_kwargs = {
                "max_tokens": kwargs.get("max_tokens", 256),
                "temperature": kwargs.get("temperature", 0.7),
            }

            # Debug logging
            logger.info(f"Attempting generation with provider {provider_name}")
            logger.info(f"Messages: {messages}")
            logger.info(f"Gen kwargs: {gen_kwargs}")

            # Special handling for the local GGUF provider - reduce timeout for faster feedback
            if provider_name == "local_gguf":
                timeout = 30.0  # Reduced timeout for faster fallback
                logger.info(f"Using reduced timeout {timeout}s for local_gguf provider")
            else:
                timeout = 60.0

            if hasattr(provider_instance, "generate_response") and callable(
                provider_instance.generate_response
            ):
                try:
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda m=messages,
                            s=stream,
                            g=gen_kwargs: provider_instance.generate_response(
                                m, stream=s, **g
                            ),
                        ),
                        timeout=timeout,
                    )
                    elapsed = time.time() - start_time

                    # If we are streaming and got a generator, return it directly
                    if stream and (
                        hasattr(result, "__next__") or hasattr(result, "__iter__")
                    ):
                        logger.info(f"Returning generator from provider {provider_name}")
                        return {
                            "content": result,
                            "success": True,
                            "elapsed_time": elapsed,
                        }

                    logger.info(
                        f"generate_response result for {provider_name} in {elapsed:.2f}s: {result}"
                    )
                    raw_result = str(result or "")
                    sanitized_result = self._sanitize_generated_content(raw_result)
                    if self._looks_like_transcript_loop(raw_result):
                        logger.warning(
                            "Rejected malformed transcript-style completion from %s",
                            provider_name,
                        )
                        return {
                            "content": "Error: Malformed transcript response",
                            "success": False,
                            "elapsed_time": elapsed,
                        }
                    if sanitized_result.strip() and not self._is_low_information_content(
                        sanitized_result
                    ):
                        logger.info(
                            "nlp_service_manager: generate_response succeeded for %s in %.2fs",
                            provider_name,
                            elapsed,
                        )
                        return {
                            "content": sanitized_result,
                            "success": True,
                            "elapsed_time": elapsed,
                        }
                    logger.warning(
                        "nlp_service_manager: generate_response returned empty/low-information output for %s",
                        provider_name,
                    )
                except asyncio.TimeoutError:
                    elapsed = time.time() - start_time
                    logger.error(
                        f"generate_response timed out for {provider_name} after {elapsed:.2f}s"
                    )
                    return {
                        "content": "Error: Generation timed out",
                        "success": False,
                        "elapsed_time": elapsed,
                    }
                except Exception as e:
                    elapsed = time.time() - start_time
                    logger.error(
                        f"generate_response failed for {provider_name} after {elapsed:.2f}s: {e}"
                    )
                    return {
                        "content": "Error: Generation failed",
                        "success": False,
                        "elapsed_time": elapsed,
                    }

            if hasattr(provider_instance, "generate_text"):
                sig = inspect.signature(provider_instance.generate_text)
                params = sig.parameters
                prompt_param = params.get("prompt")
                accepts_list = False
                if prompt_param:
                    ann = str(prompt_param.annotation)
                    accepts_list = "List" in ann or "Union" in ann

                if accepts_list:
                    try:
                        result = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda m=messages,
                                g=gen_kwargs: provider_instance.generate_text(m, **g),
                            ),
                            timeout=timeout,
                        )
                        elapsed = time.time() - start_time
                        raw_result = str(result or "")
                        sanitized_result = self._sanitize_generated_content(raw_result)
                        if self._looks_like_transcript_loop(raw_result):
                            logger.warning(
                                "Rejected malformed transcript-style completion from %s",
                                provider_name,
                            )
                            return {
                                "content": "Error: Malformed transcript response",
                                "success": False,
                                "elapsed_time": elapsed,
                            }
                        if sanitized_result.strip() and not self._is_low_information_content(
                            sanitized_result
                        ):
                            logger.info(
                                "nlp_service_manager: generate_text (list) succeeded for %s in %.2fs",
                                provider_name,
                                elapsed,
                            )
                            return {
                                "content": sanitized_result,
                                "success": True,
                                "elapsed_time": elapsed,
                            }
                        logger.warning(
                            "nlp_service_manager: generate_text (list) returned empty/low-information output for %s",
                            provider_name,
                        )
                    except asyncio.TimeoutError:
                        elapsed = time.time() - start_time
                        logger.error(
                            f"generate_text (list) timed out for {provider_name} after {elapsed:.2f}s"
                        )
                        return {
                            "content": "Error: Generation timed out",
                            "success": False,
                            "elapsed_time": elapsed,
                        }
                    except Exception as e:
                        elapsed = time.time() - start_time
                        logger.warning(
                            "generate_text (list) failed for %s after %.2fs: %s",
                            provider_name,
                            elapsed,
                            e,
                        )

                # Fallback to string format if list format failed or not supported
                prompt = "\n".join(
                    [
                        f"{m.get('role', 'user')}: {m.get('content', '')}"
                        for m in messages
                    ]
                )
                try:
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda p=prompt,
                            g=gen_kwargs: provider_instance.generate_text(p, **g),
                        ),
                        timeout=timeout,
                    )
                    elapsed = time.time() - start_time
                    raw_result = str(result or "")
                    sanitized_result = self._sanitize_generated_content(raw_result)
                    if self._looks_like_transcript_loop(raw_result):
                        logger.warning(
                            "Rejected malformed transcript-style completion from %s",
                            provider_name,
                        )
                        return {
                            "content": "Error: Malformed transcript response",
                            "success": False,
                            "elapsed_time": elapsed,
                        }
                    if sanitized_result.strip() and not self._is_low_information_content(
                        sanitized_result
                    ):
                        logger.info(
                            "nlp_service_manager: generate_text (string) succeeded for %s in %.2fs",
                            provider_name,
                            elapsed,
                        )
                        return {
                            "content": sanitized_result,
                            "success": True,
                            "elapsed_time": elapsed,
                        }
                    logger.warning(
                        "nlp_service_manager: generate_text (string) returned empty/low-information output for %s",
                        provider_name,
                    )
                except asyncio.TimeoutError:
                    elapsed = time.time() - start_time
                    logger.error(
                        f"Generation timed out for {provider_name} after {elapsed:.2f}s"
                    )
                    return {
                        "content": "Error: Generation timed out",
                        "success": False,
                        "elapsed_time": elapsed,
                    }
                except Exception as e:
                    elapsed = time.time() - start_time
                    logger.error(
                        f"Generation failed for {provider_name} after {elapsed:.2f}s: {e}"
                    )
                    return {
                        "content": "Error: Generation failed",
                        "error": str(e),
                        "success": False,
                        "elapsed_time": elapsed,
                    }

            return {
                "content": "Error: Provider does not support text generation",
                "success": False,
            }
        except Exception as e:
            elapsed = time.time() - start_time if "start_time" in locals() else 0
            logger.error(
                "Generation failed for %s after %.2fs: %s", provider_name, elapsed, e
            )
            return {
                "content": "Error: Generation failed",
                "error": str(e),
                "success": False,
                "elapsed_time": elapsed,
            }

    @staticmethod
    def _looks_like_transcript_loop(content: str) -> bool:
        text = str(content or "").strip()
        if not text:
            return False
        lowered = text.lower()
        if "<|assistant|>" in lowered or "<|user|>" in lowered:
            return True

        lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
        if len(lines) < 4:
            return False

        user_lines = sum(1 for line in lines if line.startswith("user:"))
        bot_lines = sum(
            1
            for line in lines
            if line.startswith("bot:") or line.startswith("assistant:")
        )
        return user_lines >= 2 and bot_lines >= 1

    @staticmethod
    def _sanitize_generated_content(content: str) -> str:
        text = str(content or "").strip()
        if not text:
            return ""

        text = (
            text.replace("<|assistant|>", "")
            .replace("<|user|>", "")
            .replace("<|end|>", "")
            .strip()
        )

        leaked_line = re.compile(r"^\s*(user|bot|assistant)\s*:\s*", re.IGNORECASE)
        if any(leaked_line.match(line) for line in text.splitlines()):
            cleaned_lines = [
                line.strip()
                for line in text.splitlines()
                if line.strip() and not leaked_line.match(line)
            ]
            if cleaned_lines:
                return "\n".join(cleaned_lines).strip()

        return text

    @staticmethod
    def _is_low_information_content(content: str) -> bool:
        """Detect trivial outputs that should be treated as failed generations."""
        text = str(content or "").strip()
        if not text:
            return True
        if len(text) == 1 and not text.isalnum():
            return True
        if re.fullmatch(r"[.\-_=~`'\"!?,:;()\[\]{}|/\\\s]+", text):
            return True
        return False

    async def generate_response_stream(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        provider: str | None = None,
        correlation_id: str | None = None,
        **kwargs,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield tokens from the centralized provider system in streaming mode."""
        
        # Use generate_response but with stream=True
        # This will return a generator if the provider supports it
        result = await self.generate_response(
            model_id=model_id,
            messages=messages,
            provider=provider,
            correlation_id=correlation_id,
            stream=True,
            **kwargs,
        )

        if not result.get("success"):
            error_content = result.get("content", "Error: Generation failed")
            yield {
                "content": error_content,
                "provider": result.get("actual_provider", "unknown"),
                "success": False,
                "is_degraded": True
            }
            return

        content_obj = result.get("content")
        actual_provider = result.get("actual_provider")

        # Case 1: content is already a generator (sync iterator)
        if hasattr(content_obj, "__next__") or hasattr(content_obj, "__iter__"):
            logger.info(f"🌊 Streaming tokens from {actual_provider}")
            
            # Wrap the sync iterator into an async generator
            def next_chunk(it):
                try:
                    return next(it)
                except StopIteration:
                    return None
                except Exception as e:
                    logger.error(f"Error during iterator next(): {e}")
                    return f"\n[Stream Error: {e}]"

            it = iter(content_obj)
            while True:
                chunk = await asyncio.get_event_loop().run_in_executor(None, next_chunk, it)
                if chunk is None:
                    break
                
                yield {
                    "content": chunk,
                    "provider": actual_provider,
                    "success": True
                }
        
        # Case 2: content is a string (fallback or non-streaming provider)
        elif isinstance(content_obj, str):
            logger.info(f"📄 Provider {actual_provider} returned full text (non-streaming)")
            yield {
                "content": content_obj,
                "provider": actual_provider,
                "success": True
            }
        
        else:
            logger.warning(f"⚠️ Unexpected content type from {actual_provider}: {type(content_obj)}")
            yield {
                "content": str(content_obj or ""),
                "provider": actual_provider,
                "success": True
            }

    def _load_config(self) -> NLPConfig:
        """Load NLP configuration from config manager."""
        try:
            # Get NLP config from main config
            nlp_config_dict = config_manager.get_config_value("nlp", default={})

            # Create config objects with defaults
            spacy_config = SpacyConfig(**nlp_config_dict.get("spacy", {}))
            distilbert_config = DistilBertConfig(
                **nlp_config_dict.get("distilbert", {})
            )
            small_language_model_config = SmallLanguageModelConfig(
                **nlp_config_dict.get("small_language_model", {})
            )

            config = NLPConfig(
                spacy=spacy_config,
                distilbert=distilbert_config,
                small_language_model=small_language_model_config,
                **{
                    k: v
                    for k, v in nlp_config_dict.items()
                    if k not in ["spacy", "distilbert", "small_language_model"]
                },
            )

            logger.info("NLP configuration loaded successfully")
            return config

        except Exception as e:
            logger.warning(f"Failed to load NLP config: {e}, using defaults")
            return NLPConfig()

    async def initialize(self):
        """Initialize all NLP services and start monitoring."""
        try:
            # Start health monitoring if enabled
            if self.config.enable_monitoring:
                await self.health_monitor.start_monitoring()
                logger.info("NLP health monitoring started")

            # Run initial health check
            health_status = await self.health_monitor.check_health()
            if health_status.is_healthy:
                logger.info("NLP services initialized successfully")
            else:
                logger.info(
                    f"NLP services initialized with issues: {health_status.alerts}"
                )

        except Exception as e:
            logger.error(f"Failed to initialize NLP services: {e}")
            raise

    async def shutdown(self):
        """Shutdown all NLP services."""
        try:
            await self.health_monitor.stop_monitoring()
            logger.info("NLP Service Manager shutdown completed")
        except Exception as e:
            logger.error(f"Error during NLP service shutdown: {e}")

    # spaCy service methods
    async def parse_message(self, text: str) -> ParsedMessage:
        """Parse message using spaCy service."""
        if self.spacy_service is None:
            from ai_karen_engine.core.memory.signals.spacy_service import ParsedMessage

            return ParsedMessage(
                tokens=[], entities=[], intention="unknown", raw_text=text
            )
        return await self.spacy_service.parse_message(text)

    # DistilBERT service methods
    async def get_embeddings(
        self, texts: str | list[str], normalize: bool = True
    ) -> list[float] | list[list[float]]:
        """Generate embeddings using DistilBERT service."""
        if self.distilbert_service is None:
            # Consistent fallback length for DistilBERT
            if isinstance(texts, str):
                return [0.0] * 768
            return [[0.0] * 768 for _ in texts]
        return await self.distilbert_service.get_embeddings(texts, normalize)

    async def batch_embeddings(
        self, texts: list[str], batch_size: int | None = None
    ) -> list[list[float]]:
        """Generate embeddings for multiple texts in batches."""
        return await self.distilbert_service.batch_embeddings(texts, batch_size)

    # Small Language Model service methods
    async def generate_scaffold(
        self,
        text: str,
        scaffold_type: str = "reasoning",
        max_tokens: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> ScaffoldResult:
        """Generate scaffolding using Small Language Model service."""
        if self.small_language_model_service is None:
            from ai_karen_engine.core.memory.signals.spacy_service import ScaffoldResult

            return ScaffoldResult(
                content=f"[Degraded Mode] Placeholder for {scaffold_type}"
            )
        return await self.small_language_model_service.generate_scaffold(
            text, scaffold_type, max_tokens, context
        )

    async def generate_outline(
        self, text: str, outline_style: str = "bullet", max_points: int = 5
    ) -> OutlineResult:
        """Generate outline using Small Language Model service."""
        if self.small_language_model_service is None:
            from ai_karen_engine.core.memory.signals.spacy_service import OutlineResult

            return OutlineResult(points=["[Degraded Mode] Outline unavailable"])
        return await self.small_language_model_service.generate_outline(
            text, outline_style, max_points
        )

    async def summarize_context(
        self, text: str, summary_type: str = "concise", max_tokens: int | None = None
    ) -> SummaryResult:
        """Summarize context using Small Language Model service."""
        if self.small_language_model_service is None:
            from ai_karen_engine.core.memory.signals.spacy_service import SummaryResult

            return SummaryResult(content="[Degraded Mode] Summary unavailable")
        return await self.small_language_model_service.summarize_context(
            text, summary_type, max_tokens
        )

    async def generate_short_fill(
        self,
        context: str,
        prompt: str,
        max_tokens: int | None = None,
        fill_type: str = "continuation",
    ) -> ScaffoldResult:
        """Generate short fill using Small Language Model service."""
        if self.small_language_model_service is None:
            from ai_karen_engine.core.memory.signals.spacy_service import ScaffoldResult

            return ScaffoldResult(content="[Degraded Mode] Short fill unavailable")
        return await self.small_language_model_service.generate_short_fill(
            context, prompt, max_tokens, fill_type
        )

    async def augment_response(
        self,
        user_message: str,
        main_response: str,
        augmentation_type: str = "enhancement",
    ) -> dict[str, Any]:
        """Augment response using Small Language Model service."""
        if self.small_language_model_service is None:
            return {"augmented_content": main_response, "status": "degraded"}
        return await self.small_language_model_service.augment_response(
            user_message, main_response, augmentation_type
        )

    # Combined NLP operations
    async def process_message_full(self, text: str) -> dict[str, Any]:
        """Process message with both spaCy parsing and DistilBERT embeddings."""
        try:
            # Run both operations concurrently
            parse_task = self.parse_message(text)
            embedding_task = self.get_embeddings(text)

            parsed_message, embeddings = await asyncio.gather(
                parse_task, embedding_task
            )

            return {
                "text": text,
                "parsed": {
                    "tokens": parsed_message.tokens,
                    "lemmas": parsed_message.lemmas,
                    "entities": parsed_message.entities,
                    "pos_tags": parsed_message.pos_tags,
                    "noun_phrases": parsed_message.noun_phrases,
                    "sentences": parsed_message.sentences,
                    "dependencies": parsed_message.dependencies,
                    "language": parsed_message.language,
                    "processing_time": parsed_message.processing_time,
                    "used_fallback": parsed_message.used_fallback,
                },
                "embeddings": embeddings,
                "embedding_dimension": len(embeddings) if embeddings else 0,
            }

        except Exception as e:
            logger.error(f"Full message processing failed: {e}")
            raise

    async def extract_entities_with_embeddings(self, text: str) -> list[dict[str, Any]]:
        """Extract entities and generate embeddings for each entity."""
        parsed_message = await self.parse_message(text)

        if not parsed_message.entities:
            return []

        # Extract entity texts
        entity_texts = [entity[0] for entity in parsed_message.entities]

        # Generate embeddings for all entities
        entity_embeddings = await self.batch_embeddings(entity_texts)

        # Combine entities with their embeddings
        entities_with_embeddings = []
        for (entity_text, entity_label), embedding in zip(
            parsed_message.entities, entity_embeddings
        ):
            entities_with_embeddings.append(
                {"text": entity_text, "label": entity_label, "embedding": embedding}
            )

        return entities_with_embeddings

    async def semantic_similarity(self, text1: str, text2: str) -> float:
        """Calculate semantic similarity between two texts using embeddings."""
        embeddings = await self.get_embeddings([text1, text2])

        if len(embeddings) != 2:
            raise ValueError("Failed to generate embeddings for both texts")

        # Calculate cosine similarity
        import numpy as np

        vec1 = np.array(embeddings[0])
        vec2 = np.array(embeddings[1])

        # Cosine similarity
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        similarity = dot_product / (norm1 * norm2)
        return float(similarity)

    # Health and monitoring methods
    async def get_health_status(self) -> NLPSystemHealth:
        """Get current health status of all NLP services."""
        return await self.health_monitor.check_health()

    def get_health_summary(self) -> dict[str, Any]:
        """Get health summary."""
        return self.health_monitor.get_health_summary()

    def get_health_trends(self, hours: int = 24) -> dict[str, Any]:
        """Get health trends over specified time period."""
        return self.health_monitor.get_health_trends(hours)

    async def run_diagnostic(self) -> dict[str, Any]:
        """Run comprehensive diagnostic tests."""
        return await self.health_monitor.run_diagnostic()

    # Configuration methods
    def configure_services(
        self,
        enable_spacy: bool = True,
        enable_distilbert: bool = True,
        enable_small_language_model: bool = True,
    ):
        """Configure which NLP services should be enabled.

        Args:
            enable_spacy: Whether to enable spaCy service
            enable_distilbert: Whether to enable DistilBERT service
            enable_small_language_model: Whether to enable Small Language Model service
        """
        # Update configuration
        self.config.spacy.enabled = enable_spacy
        self.config.distilbert.enabled = enable_distilbert
        self.config.small_language_model.enabled = enable_small_language_model

        # Log the configuration
        logger.info(
            f"NLP services configured: spaCy={enable_spacy}, DistilBERT={enable_distilbert}, Small Language Model={enable_small_language_model}"
        )

    def get_config(self) -> NLPConfig:
        """Get current NLP configuration."""
        return self.config

    async def update_config(self, new_config: dict[str, Any]):
        """Update NLP configuration."""
        try:
            # Update main config
            from ai_karen_engine.config.config_manager import save_config

            current_config = config_manager.get_config()
            current_config["nlp"] = new_config
            save_config(current_config)

            # Reload configuration
            self.config = self._load_config()

            # Reload services with new config
            await self.spacy_service.reload_model()
            await self.distilbert_service.reload_model()

            logger.info("NLP configuration updated successfully")

        except Exception as e:
            logger.error(f"Failed to update NLP configuration: {e}")
            raise

    # Cache management
    def clear_all_caches(self):
        """Clear all service caches."""
        self.spacy_service.clear_cache()
        self.distilbert_service.clear_cache()
        self.small_language_model_service.clear_cache()
        logger.info("All NLP service caches cleared")

    def reset_all_metrics(self):
        """Reset all service metrics."""
        self.spacy_service.reset_metrics()
        self.distilbert_service.reset_metrics()
        self.small_language_model_service.reset_metrics()
        logger.info("All NLP service metrics reset")

    # Utility methods
    def is_ready(self) -> bool:
        """Check if NLP services are ready for use."""
        spacy_status = self.spacy_service.get_health_status()
        distilbert_status = self.distilbert_service.get_health_status()
        small_language_model_status = (
            self.small_language_model_service.get_health_status()
        )

        return (
            spacy_status.is_healthy
            and distilbert_status.is_healthy
            and small_language_model_status.is_healthy
        ) or (
            spacy_status.fallback_mode
            and distilbert_status.fallback_mode
            and small_language_model_status.fallback_mode
        )

    def get_service_info(self) -> dict[str, Any]:
        """Get information about all NLP services."""
        spacy_status = self.spacy_service.get_health_status()
        distilbert_status = self.distilbert_service.get_health_status()
        small_language_model_status = (
            self.small_language_model_service.get_health_status()
        )

        return {
            "spacy": {
                "model_name": self.config.spacy.model_name,
                "model_loaded": spacy_status.model_loaded,
                "fallback_mode": spacy_status.fallback_mode,
                "cache_size": spacy_status.cache_size,
                "disabled_components": self.config.spacy.disabled_components,
            },
            "distilbert": {
                "model_name": self.config.distilbert.model_name,
                "model_loaded": distilbert_status.model_loaded,
                "fallback_mode": distilbert_status.fallback_mode,
                "device": distilbert_status.device,
                "cache_size": distilbert_status.cache_size,
                "embedding_dimension": self.config.distilbert.embedding_dimension,
            },
            "small_language_model": {
                "model_name": self.config.small_language_model.model_name,
                "model_loaded": small_language_model_status.model_loaded,
                "fallback_mode": small_language_model_status.fallback_mode,
                "cache_size": small_language_model_status.cache_size,
                "max_tokens": self.config.small_language_model.max_tokens,
                "temperature": self.config.small_language_model.temperature,
            },
            "monitoring_enabled": self.config.enable_monitoring,
            "ready": self.is_ready(),
        }


_nlp_manager_lock = threading.RLock()
_nlp_manager_instance: NLPServiceManager | None = None


def get_nlp_service_manager() -> NLPServiceManager:
    """Return the lazily-created :class:`NLPServiceManager` singleton."""
    global _nlp_manager_instance
    if _nlp_manager_instance is None:
        with _nlp_manager_lock:
            if _nlp_manager_instance is None:
                logger.info("Initializing NLPServiceManager (lazy singleton)")
                _nlp_manager_instance = NLPServiceManager()
    return _nlp_manager_instance


class _LazyNLPServiceManagerProxy:
    """Attribute proxy that lazily instantiates the underlying manager on use."""

    def _resolve(self) -> NLPServiceManager:
        return get_nlp_service_manager()

    def __getattr__(self, item):
        return getattr(self._resolve(), item)

    def __setattr__(self, key, value):
        if key.startswith("_"):
            super().__setattr__(key, value)
        else:
            setattr(self._resolve(), key, value)

    def __repr__(self) -> str:
        return f"<LazyNLPServiceManagerProxy wrapping {self._resolve()!r}>"

    def __dir__(self):
        return sorted(set(dir(self._resolve())))


nlp_service_manager = _LazyNLPServiceManagerProxy()


def reset_nlp_service_manager() -> None:
    """Reset the cached manager instance (primarily for tests)."""
    global _nlp_manager_instance
    with _nlp_manager_lock:
        _nlp_manager_instance = None


__all__ = [
    "NLPServiceManager",
    "get_nlp_service_manager",
    "nlp_service_manager",
    "reset_nlp_service_manager",
]

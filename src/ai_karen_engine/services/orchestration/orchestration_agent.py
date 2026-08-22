"""
OrchestrationAgent: health-aware, preference-first LLM orchestration with helper models.

Implements requirements:
- User preference honoring with health/auth checks and graceful fallbacks
- Configurable provider hierarchy with hard final fallback and degraded mode
- Helper models (SmallLanguageModel scaffolding, DistilBERT, spaCy) to augment responses
- Dynamic prompt suggestions included in a strict response envelope
- Intelligent routing for simple classification and extraction tasks
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ai_karen_engine.core.model_runtime.model_selection_algorithm import ModelSelectionAlgorithm
from ai_karen_engine.core.runtime.degraded_mode import (
    get_degraded_mode_manager,
    DegradedModeReason,
)
from ai_karen_engine.integrations.llm_utils import LLMUtils, GenerationFailed
from ai_karen_engine.integrations.llm_registry import get_registry
from ai_karen_engine.core.model_runtime.provider_registry_service import (
    get_provider_registry_service,
    ProviderRegistryService,
    ProviderCapability,
)
from ai_karen_engine.core.model_runtime.model_manager import ModelManager
from ai_karen_engine.core.memory.signals.distilbert_service import DistilBertService
from ai_karen_engine.core.memory.signals.spacy_service import SpacyService
from ai_karen_engine.core.reasoning.synthesis.small_language_model_service import (
    SmallLanguageModelService,
)

logger = logging.getLogger(__name__)


@dataclass
class OrchestrationInput:
    message: str
    conversation_history: Optional[List[Dict[str, Any]]] = None
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    llm_preferences: Optional[Dict[str, str]] = (
        None  # {preferred_llm_provider, preferred_model}
    )
    context: Optional[Dict[str, Any]] = None


class OrchestrationAgent:
    """Central orchestration agent for Kari's chat with helper integrations."""

    def __init__(
        self,
        provider_registry: Optional[ProviderRegistryService] = None,
        llm_utils: Optional[LLMUtils] = None,
        distilbert: Optional[DistilBertService] = None,
        spacy_service: Optional[SpacyService] = None,
        small_language_model_service: Optional[SmallLanguageModelService] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Configuration for orchestration behavior (must be first)
        self.config = config or {}

        self.provider_registry = provider_registry or get_provider_registry_service()
        self.llm_utils = llm_utils or LLMUtils()
        self.degraded_manager = get_degraded_mode_manager()
        self.distilbert = distilbert or DistilBertService()
        self.spacy_service = spacy_service or SpacyService()
        self.small_language_model_service = (
            small_language_model_service or SmallLanguageModelService()
        )
        self._response_formatter = None

        # Initialize model selection algorithm
        self.model_selector = ModelSelectionAlgorithm(
            provider_registry=self.provider_registry,
            config=self.config,
        )

        # Configurable system default fallback hierarchy [Local GGUF, Transformers, OpenAI, Gemini, DeepSeek]
        # Requirements 1.1, 1.2, 2.1, 2.2
        self.default_hierarchy = self.config.get(
            "default_hierarchy",
            [
                "local_gguf",  # Local GGUF runtime
                "transformers",  # Transformers
                "openai",  # OpenAI
                "gemini",  # Gemini
                "deepseek",  # DeepSeek
                "huggingface",  # HuggingFace fallback
            ],
        )

        # Hard final fallback model - last resort before degraded mode
        try:
            from ai_karen_engine.config.config_manager import get_config

            cfg = get_config()
            default_lightweight = cfg.llm.default_lightweight_model_id
        except Exception:
            default_lightweight = "default-lightweight-model"

        self.hard_final_fallback = self.config.get(
            "hard_final_fallback",
            {"provider": "local_gguf", "model": default_lightweight},
        )

        # User preference validation settings
        self.preference_validation = self.config.get(
            "preference_validation",
            {
                "validate_provider_exists": True,
                "validate_model_exists": True,
                "fallback_on_invalid": True,
            },
        )

    async def orchestrate_response(self, data: OrchestrationInput) -> Dict[str, Any]:
        """
        Main orchestration entrypoint: returns strict JSON envelope.

        Implements 4-step model selection:
        1. User preference → 2. System defaults → 3. Hard fallback → 4. Degraded mode
        Requirements: 1.1, 1.2, 2.1, 2.2
        """
        t0 = time.time()

        # Validate and extract user preferences (Requirement 1.1)
        validated_preferences = self._validate_user_preferences(
            data.llm_preferences or {}
        )

        # DEBUG: Force fallback for specific test message
        if data.message == "Force fallback test":
            logger.warning("FORCING DEGRADED MODE FOR TEST")
            self.degraded_manager.activate_degraded_mode(
                DegradedModeReason.ALL_PROVIDERS_FAILED,
                failed_providers=["forced_test_failure"],
            )
            return await self.degraded_manager.generate_degraded_response(
                data.message,
                requested_provider="forced_test_failure",
                failure_reason="Forced test failure"
            )

        # Quick task routing using helpers (Requirement 6)
        task_type = await self._infer_task_type(data)

        # If classification-only, prefer DistilBERT
        if task_type == "classification":
            classification = await self._run_classification(data.message)
            suggestions = self._generate_suggestions(
                data, familiarity=self._estimate_familiarity(data)
            )
            meta = {
                "annotations": ["AI Enhanced", "Helper: DistilBERT"],
                "routing": {
                    "task": task_type,
                    "rationale": "Classification task routed to DistilBERT",
                    "selection_path": "helper_model_routing",
                },
                "latency": time.time() - t0,
                "confidence": 0.8,
            }
            return self._response_formatter_pipeline().build_response_envelope(
                classification,
                "Helper",
                "distilbert",
                metadata=meta,
                suggestions=suggestions,
            )

        # If extraction, prefer spaCy
        if task_type == "extraction":
            extracted = await self._run_extraction(data.message)
            suggestions = self._generate_suggestions(
                data, familiarity=self._estimate_familiarity(data)
            )
            meta = {
                "annotations": ["AI Enhanced", "Helper: spaCy"],
                "routing": {
                    "task": task_type,
                    "rationale": "Extraction task routed to spaCy",
                    "selection_path": "helper_model_routing",
                },
                "latency": time.time() - t0,
                "confidence": 0.75,
            }
            return self._response_formatter_pipeline().build_response_envelope(
                extracted, "Helper", "spacy", metadata=meta, suggestions=suggestions
            )

        # If scaffolding, prefer SmallLanguageModel
        if task_type == "scaffolding":
            scaffolded = await self._run_scaffolding(data.message)
            suggestions = self._generate_suggestions(
                data, familiarity=self._estimate_familiarity(data)
            )
            meta = {
                "annotations": ["AI Enhanced", "Helper: SmallLanguageModel"],
                "routing": {
                    "task": task_type,
                    "rationale": "Scaffolding task routed to SmallLanguageModel",
                    "selection_path": "helper_model_routing",
                },
                "latency": time.time() - t0,
                "confidence": 0.8,
            }
            return self._response_formatter_pipeline().build_response_envelope(
                scaffolded,
                "Helper",
                "small_language_model",
                metadata=meta,
                suggestions=suggestions,
            )

        # General/complex chat → main LLM with 4-step selection process
        selection_result = await self.model_selector.select_provider_and_model(
            user_preferences=validated_preferences,
            context={"message": data.message, "session_id": data.session_id},
        )

        if selection_result.provider is None:
            # Enter degraded mode (Requirement 8/9)
            self.degraded_manager.activate_degraded_mode(
                DegradedModeReason.ALL_PROVIDERS_FAILED,
                failed_providers=self.default_hierarchy,
            )
            degraded = await self.degraded_manager.generate_degraded_response(
                data.message,
                requested_provider=validated_preferences.get("provider", "primary"),
                requested_model=validated_preferences.get("model", "unknown"),
                failure_reason="No available providers found in selection hierarchy"
            )
            # Ensure suggestions for recovery are present
            if not degraded.get("suggestions"):
                degraded["suggestions"] = [
                    "Retry later when providers recover",
                    "Switch provider in settings",
                    "Ask for a shorter or simpler response",
                ]
            return degraded

        # Invoke the selected provider
        try:
            final_text, latency, usage = await self._invoke_provider(
                selection_result.provider, selection_result.model, data
            )
        except GenerationFailed as exc:
            logger.error(
                "LLM generation failed after fallback chain (provider=%s, model=%s): %s",
                selection_result.provider,
                selection_result.model,
                exc,
            )
            return await self._handle_generation_failure(
                data,
                failure_reason="llm_generation_failed",
                error=str(exc),
                failed_provider=selection_result.provider,
            )
        except Exception as exc:  # pragma: no cover - safety net for provider errors
            logger.exception(
                "Unexpected error during provider invocation (provider=%s, model=%s)",
                selection_result.provider,
                selection_result.model,
            )
            return await self._handle_generation_failure(
                data,
                failure_reason="unexpected_invocation_error",
                error=str(exc),
                failed_provider=selection_result.provider,
            )

        # Add dynamic suggestions
        suggestions = self._generate_suggestions(
            data, familiarity=self._estimate_familiarity(data)
        )

        # Confidence calibration: base + helper corroboration
        confidence = 0.7
        if self.distilbert and self.spacy_service:
            confidence += 0.05  # small boost when helpers are available
        confidence = min(confidence, 0.95)

        meta = {
            "provider": selection_result.provider,
            "model": selection_result.model or "default",
            "latency": latency,
            "usage": usage or {},
            "confidence": confidence,
            "annotations": ["AI Enhanced"],
            "routing": {
                "task": task_type,
                "rationale": selection_result.rationale,
                "selection_path": selection_result.selection_path,
                "fallback_attempts": selection_result.fallback_attempts,
                "health_checks_performed": selection_result.health_checks_performed,
                "selection_time_ms": selection_result.total_selection_time_ms,
                "helper_models": self._get_available_helpers(),
            },
        }

        return self._response_formatter_pipeline().build_response_envelope(
            final_text,
            selection_result.provider,
            selection_result.model or "default",
            metadata=meta,
            suggestions=suggestions,
        )

    async def _handle_generation_failure(
        self,
        data: OrchestrationInput,
        *,
        failure_reason: str,
        error: Optional[str] = None,
        failed_provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gracefully degrade when all provider attempts fail."""

        logger.warning(
            "Falling back to degraded mode (reason=%s, provider=%s)",
            failure_reason,
            failed_provider,
        )

        failed_chain = self.default_hierarchy.copy()
        if failed_provider and failed_provider not in failed_chain:
            failed_chain.insert(0, failed_provider)

        self.degraded_manager.activate_degraded_mode(
            DegradedModeReason.ALL_PROVIDERS_FAILED,
            failed_providers=failed_chain,
        )

        degraded = await self.degraded_manager.generate_degraded_response(
            data.message,
            requested_provider=failed_provider or "primary",
            failure_reason=failure_reason
        )
        meta = degraded.setdefault("meta", {})
        annotations = meta.setdefault("annotations", [])
        if "LLM Fallback" not in annotations:
            annotations.append("LLM Fallback")

        meta["fallback_reason"] = failure_reason
        if error:
            meta["error"] = error
        if failed_provider:
            meta["failed_provider"] = failed_provider

        routing_info = meta.setdefault("routing", {})
        routing_info.update(
            {
                "selection_path": "degraded_mode",
                "failure_reason": failure_reason,
                "failed_provider": failed_provider,
            }
        )

        suggestions = degraded.setdefault("suggestions", [])
        fallback_suggestions = [
            "Retry in a few minutes once providers recover.",
            "Switch to a different preferred provider in settings.",
            "Ask for a shorter or more focused response.",
        ]
        for suggestion in fallback_suggestions:
            if suggestion not in suggestions:
                suggestions.append(suggestion)

        if len(suggestions) > 5:
            degraded["suggestions"] = suggestions[:5]

        return degraded

    def _response_formatter_pipeline(self):
        if self._response_formatter is None:
            from ai_karen_engine.core.langgraph_orchestrator.formatting.response_formatter_pipeline import (
                ResponseFormatterPipeline,
            )

            self._response_formatter = ResponseFormatterPipeline()
        return self._response_formatter

    def _validate_user_preferences(
        self, llm_preferences: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Validate and polish user preference extraction.
        Requirements: 1.1, 1.2
        """
        validated = {}

        # Extract and normalize provider preference
        provider = (
            llm_preferences.get("preferred_llm_provider")
            or llm_preferences.get("provider", "").strip()
        )
        if provider:
            # Normalize common variations
            provider_mapping = {
                "openai": "openai",
                "gpt": "openai",
                "gemini": "gemini",
                "google": "gemini",
                "deepseek": "deepseek",
                "huggingface": "huggingface",
                "hf": "huggingface",
                "transformers": "transformers",
            }
            normalized_provider = provider_mapping.get(
                provider.lower(), provider.lower()
            )

            # Validate provider exists if configured to do so
            if self.preference_validation["validate_provider_exists"]:
                available_providers = self.provider_registry.get_available_providers()
                if normalized_provider in available_providers:
                    validated["provider"] = normalized_provider
                else:
                    logger.warning(
                        f"User preferred provider '{provider}' not available. Available: {available_providers}"
                    )
                    if self.preference_validation["fallback_on_invalid"]:
                        validated["provider"] = None  # Will trigger fallback
            else:
                validated["provider"] = normalized_provider

        # Extract and validate model preference
        model = (
            llm_preferences.get("preferred_model")
            or llm_preferences.get("model", "").strip()
        )
        if model and validated.get("provider"):
            # Basic model validation - could be enhanced with registry lookup
            if self.preference_validation["validate_model_exists"] and validated.get(
                "provider"
            ):
                provider_name = validated["provider"]
                if provider_name:
                    is_available = self.provider_registry.is_model_available(
                        provider_name,
                        model,
                        healthy_only=self.preference_validation.get(
                            "validate_provider_exists",
                            True,
                        ),
                    )
                else:
                    is_available = False

                if is_available:
                    validated["model"] = model
                else:
                    logger.warning(
                        "User preferred model '%s' not available for provider '%s'",
                        model,
                        provider_name,
                    )
                    if not self.preference_validation["fallback_on_invalid"]:
                        validated["model"] = model
            else:
                validated["model"] = model

        logger.debug(f"Validated user preferences: {validated}")
        return validated

    async def _infer_task_type(self, data: OrchestrationInput) -> str:
        """Infer task type: classification, extraction, scaffolding, or chat."""
        text = (data.message or "").lower()
        # Simple heuristics; can be enhanced using helpers
        if any(
            k in text for k in ["classify", "is this", "label this", "sentiment of"]
        ):
            return "classification"
        if any(
            k in text
            for k in [
                "extract",
                "pull entities",
                "ner",
                "find names",
                "find entities",
                "structured",
            ]
        ):
            return "extraction"
        if any(
            k in text
            for k in [
                "outline",
                "scaffold",
                "structure",
                "organize",
                "break down",
                "summarize",
            ]
        ):
            return "scaffolding"
        return "chat"

    async def _run_classification(self, text: str) -> str:
        """Use DistilBERT embeddings to produce simple sentiment/intent classification."""
        try:
            emb = await self.distilbert.get_embeddings(text)

            # Handle different embedding types
            if isinstance(emb, list) and len(emb) > 0:
                if isinstance(emb[0], list):
                    # It's a list of lists (batch embeddings), flatten the first one
                    emb_flat = [
                        x
                        for sublist in emb[:1]
                        for x in sublist
                        if isinstance(x, (int, float))
                    ]
                else:
                    # It's a flat list of floats, filter out non-numeric values
                    emb_flat = [x for x in emb if isinstance(x, (int, float))]

                # Calculate average embedding value
                if emb_flat:
                    score = sum(emb_flat) / max(1, len(emb_flat))
                else:
                    score = 0.0
            else:
                score = 0.0

            sentiment = (
                "positive" if score > 0.1 else "negative" if score < -0.1 else "neutral"
            )
            intent = (
                "question"
                if "?" in text
                else (
                    "task"
                    if any(w in text.lower() for w in ["build", "create", "make"])
                    else "statement"
                )
            )
            return f"Classification -> intent: {intent}, sentiment: {sentiment}"
        except Exception as e:
            logger.debug(f"DistilBERT classification failed: {e}")
            return "Classification unavailable; falling back to main LLM would be appropriate."

    async def _run_extraction(self, text: str) -> str:
        """Use spaCy to extract entities and key phrases."""
        try:
            parsed = await self.spacy_service.parse_message(text)
            ents = ", ".join([f"{t}({l})" for t, l in parsed.entities]) or "none"
            nouns = ", ".join(parsed.noun_phrases[:5]) or "none"
            return f"Entities: {ents}\nKey phrases: {nouns}"
        except Exception as e:
            logger.debug(f"spaCy extraction failed: {e}")
            return (
                "Extraction unavailable; falling back to main LLM would be appropriate."
            )

    async def _run_scaffolding(self, text: str) -> str:
        """Use SmallLanguageModel to generate scaffolding, outlines, and quick structures."""
        try:
            # Determine scaffolding type based on content
            text_lower = text.lower()
            if "outline" in text_lower:
                outline_result = (
                    await self.small_language_model_service.generate_outline(
                        text, max_points=5
                    )
                )
                if outline_result.outline:
                    formatted_outline = "\n".join(
                        [f"• {point}" for point in outline_result.outline]
                    )
                    return f"Generated outline:\n{formatted_outline}"
                else:
                    return "Outline generation completed but no points extracted."

            elif "summarize" in text_lower or "summary" in text_lower:
                summary_result = (
                    await self.small_language_model_service.summarize_context(
                        text, summary_type="concise"
                    )
                )
                if summary_result.summary:
                    return f"Summary: {summary_result.summary}"
                else:
                    return "Summary generation completed but no content extracted."

            else:
                # General scaffolding
                scaffold_result = (
                    await self.small_language_model_service.generate_scaffold(
                        text, scaffold_type="structure"
                    )
                )
                if scaffold_result.content:
                    return f"Structure scaffold:\n{scaffold_result.content}"
                else:
                    return (
                        "Scaffolding generation completed but no structure extracted."
                    )

        except Exception as e:
            logger.debug(f"SmallLanguageModel scaffolding failed: {e}")
            return "Scaffolding unavailable; falling back to main LLM would be appropriate."

    async def orchestrate_stream(self, data: OrchestrationInput) -> AsyncIterator[str]:
        """
        Streaming version of orchestration.
        Yields text chunks directly.
        """
        # Validate and extract user preferences
        validated_preferences = self._validate_user_preferences(
            data.llm_preferences or {}
        )

        # DEBUG: Force fallback for specific test message
        if data.message == "Force fallback test":
            logger.warning("FORCING DEGRADED MODE FOR STREAM TEST")
            degraded = await self.degraded_manager.generate_degraded_response(
                data.message,
                requested_provider="forced_test_failure",
                failure_reason="Forced test failure"
            )
            yield degraded.get("final") or "Degraded mode active."
            return

        # General/complex chat → main LLM with 4-step selection process
        selection_result = await self.model_selector.select_provider_and_model(
            user_preferences=validated_preferences,
            context={"message": data.message, "session_id": data.session_id},
        )

        if selection_result.provider is None:
            # Entering degraded mode for streaming
            degraded = await self.degraded_manager.generate_degraded_response(
                data.message,
                requested_provider=validated_preferences.get("provider", "primary"),
                failure_reason="No available providers found in hierarchy"
            )
            yield degraded.get("final") or "All providers are currently unavailable. Entering degraded mode..."
            return

        # Invoke the selected provider in streaming mode
        try:
            async for chunk in self._invoke_provider_stream(
                selection_result.provider, selection_result.model, data
            ):
                yield chunk
        except Exception as e:
            logger.error(f"Orchestration streaming failed: {e}")
            yield f"\n[Streaming error: {e}]"

    async def _invoke_provider_stream(
        self, provider: str, model: Optional[str], data: OrchestrationInput
    ) -> AsyncIterator[str]:
        """Call provider with fail-fast and immediate fallback to next in chain (Streaming)."""
        # Build an augmented prompt using helper insights
        helper_prefix = await self._build_helper_prefix(data)
        prompt = f"{helper_prefix}\n\nUser: {data.message}"

        for attempt_provider in self._iter_provider_chain(provider):
            try:
                # Use ModelManager for streaming as LLMUtils doesn't support it yet
                prov_obj = self.llm_utils.get_provider(attempt_provider)
                
                kwargs: Dict[str, Any] = {"model": model} if model else {}
                
                async for chunk in ModelManager.stream_provider(
                    prov_obj,
                    prompt,
                    **kwargs,
                ):
                    yield chunk
                
                return # Successfully streamed
                
            except Exception as e:
                logger.warning(f"Provider {attempt_provider} streaming failed, trying next: {e}")
                continue

        # If we reached here, all providers failed
        yield "\n[Error: All providers in chain failed to stream response]"

    def _default_model_for(self, provider: str) -> Optional[str]:
        try:
            reg = get_registry()
            info = reg._registrations.get(provider)
            return info.default_model if info else None
        except Exception:
            return None

    async def _invoke_provider(
        self, provider: str, model: Optional[str], data: OrchestrationInput
    ) -> Tuple[str, float, Optional[Dict[str, Any]]]:
        """Call provider with fail-fast and immediate fallback to next in chain."""
        start = time.time()
        usage: Optional[Dict[str, Any]] = None

        # Build an augmented prompt using helper insights
        helper_prefix = await self._build_helper_prefix(data)
        prompt = f"{helper_prefix}\n\nUser: {data.message}"

        for attempt_provider in self._iter_provider_chain(provider):
            try:
                kwargs: Dict[str, Any] = {"model": model} if model else {}
                text = self.llm_utils.generate_text(
                    prompt,
                    provider=attempt_provider,
                    user_ctx={
                        "session_id": data.session_id,
                        "conversation_id": data.conversation_id,
                    },
                    **kwargs,
                )
                latency = time.time() - start
                # Try to pull usage if provider exposes it
                try:
                    prov_obj = self.llm_utils.get_provider(attempt_provider)
                    usage = getattr(prov_obj, "last_usage", None)
                except Exception:
                    usage = None
                return text, latency, usage
            except Exception as e:
                logger.warning(f"Provider {attempt_provider} failed, trying next: {e}")
                continue

        # If we reached here, all providers failed
        raise GenerationFailed("All providers failed in chain")

    def _iter_provider_chain(self, first: str):
        """Yield providers starting from `first`, then remaining defaults."""
        seen = set()
        if first:
            seen.add(first)
            yield first
        for p in self.default_hierarchy:
            if p not in seen:
                seen.add(p)
                yield p

    async def _build_helper_prefix(self, data: OrchestrationInput) -> str:
        """Use helper models to build brief scaffolding and context."""
        parts: List[str] = []

        # SmallLanguageModel scaffolding for reasoning and outline generation
        try:
            if self.small_language_model_service:
                scaffold_result = (
                    await self.small_language_model_service.generate_scaffold(
                        data.message, scaffold_type="reasoning", max_tokens=50
                    )
                )
                if scaffold_result.content:
                    parts.append(f"Reasoning scaffold: {scaffold_result.content}")
        except Exception as e:
            logger.debug(f"SmallLanguageModel scaffolding failed, using fallback: {e}")
            # Fallback to simple outline
            outline = self._scaffold_outline(data.message)
            if outline:
                parts.append(f"Outline: {outline}")

        # spaCy entities
        try:
            parsed = await self.spacy_service.parse_message(data.message)
            if parsed.entities:
                ents = ", ".join([t for t, _ in parsed.entities[:5]])
                parts.append(f"Entities: {ents}")
        except Exception:
            pass

        return "\n".join(parts) if parts else ""

    def _scaffold_outline(self, text: str) -> str:
        """Lightweight outline heuristic to reduce latency."""
        text = text.strip()
        if not text:
            return ""
        # Break into 2-3 bullet points based on punctuation
        cuts = [seg.strip() for seg in text.replace("?", ".").split(".") if seg.strip()]
        bullets = [f"- {seg[:60]}" for seg in cuts[:3]]
        return " ".join(bullets)

    def _estimate_familiarity(self, data: OrchestrationInput) -> str:
        """Derive user familiarity (novice↔expert) from history length and question ratio."""
        history = data.conversation_history or []
        if not history:
            return "novice"
        questions = sum(1 for m in history if "?" in (m.get("content") or ""))
        ratio = questions / max(1, len(history))
        return (
            "novice"
            if ratio > 0.5
            else "expert"
            if len(history) > 10 and ratio < 0.2
            else "intermediate"
        )

    def _get_available_helpers(self) -> List[str]:
        """Get list of available helper models."""
        helpers = []

        # Check SmallLanguageModel availability
        if self.small_language_model_service:
            try:
                health = self.small_language_model_service.get_health_status()
                if health.is_healthy:
                    helpers.append("SmallLanguageModel")
            except Exception:
                pass

        # Check DistilBERT availability
        if self.distilbert:
            try:
                health = self.distilbert.get_health_status()
                if health.is_healthy:
                    helpers.append("DistilBERT")
            except Exception:
                pass

        # Check spaCy availability
        if self.spacy_service:
            try:
                health = self.spacy_service.get_health_status()
                if health.is_healthy:
                    helpers.append("spaCy")
            except Exception:
                pass

        return helpers

    def _generate_suggestions(
        self, data: OrchestrationInput, familiarity: str
    ) -> List[str]:
        """Generate 3-5 concise, contextual next-step prompts."""
        msg = (data.message or "").lower()
        base: List[str] = []
        if "code" in msg or "error" in msg:
            base = [
                "Show me the minimal reproducible example",
                "What versions and platform are you using?",
                "List the exact error message",
                "Try a smaller scope to isolate the issue",
            ]
        elif any(k in msg for k in ["explain", "how", "what is"]):
            base = [
                "Could you give a concrete example?",
                "Summarize the key points",
                "Compare alternatives with pros/cons",
                "Suggest next steps for me",
            ]
        else:
            base = [
                "Would you like a brief summary?",
                "Should I draft an outline?",
                "Do you want actionable steps?",
                "Any preferences for tone or detail?",
            ]
        # Tailor for familiarity
        if familiarity == "novice":
            base.append("Explain like I'm new to this topic")
        elif familiarity == "expert":
            base.append("Skip basics; focus on edge cases")
        # Ensure 3-5 unique suggestions
        seen, out = set(), []
        for s in base:
            if s not in seen:
                seen.add(s)
                out.append(s)
            if len(out) >= 5:
                break
        return out[:5]


def get_orchestration_agent(
    config: Optional[Dict[str, Any]] = None,
) -> OrchestrationAgent:
    """Factory for default orchestration agent instance with optional configuration."""
    return OrchestrationAgent(config=config)

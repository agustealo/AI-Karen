from __future__ import annotations

"""Neutral local runtime backed by optional Transformers support."""

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from ai_karen_engine.core.model_runtime.provider_contracts import (
    GenerationFailed,
    LLMProviderBase,
    ModelRuntimeCapabilities,
    ProviderNotAvailable,
)

logger = logging.getLogger(__name__)


def _lazy_import_transformers() -> bool:
    try:
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


class TransformersRuntime(LLMProviderBase):
    """Best-effort first-party local text runtime.

    The runtime does not manufacture assistant text when the model is unavailable.
    Callers receive a typed provider failure and decide whether fallback is allowed.
    Specialized runtime adapters may borrow the warmed model/tokenizer through
    ``generation_components`` while sharing the same generation lock.
    """

    _instance: Optional["TransformersRuntime"] = None

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: str = "auto",
        torch_dtype: str = "auto",
        quantization: Optional[str] = None,
        use_flash_attention: bool = False,
        **kwargs: Any,
    ) -> None:
        self.model_path = model_path
        self.device = device
        self.torch_dtype = torch_dtype
        self.quantization = quantization
        self.use_flash_attention = use_flash_attention
        self.options = dict(kwargs)
        self.provider_name = kwargs.get("provider_name", "builtin_transformers")
        self._transformers_available = _lazy_import_transformers()
        self._model_name = self._resolve_model_name(model_path)
        self._pipeline = None
        self._lock = threading.Lock()
        self._generation_lock = threading.RLock()

        if not self._transformers_available:
            logger.info("Transformers not installed; runtime unavailable")
        elif model_path:
            threading.Thread(target=self.warm, args=(model_path,), daemon=True).start()

    def _resolve_model_name(self, model_path: Optional[str]) -> str:
        if not model_path or model_path == "auto":
            return "auto"
        name = Path(model_path).name
        return name[:-5] if name.endswith(".gguf") else name

    def warm(self, model_path: Optional[str] = None) -> bool:
        if not self._transformers_available:
            return False

        target_path = model_path or self.model_path
        if not target_path or target_path == "auto":
            from ai_karen_engine.config.config_manager import get_default_model

            target_path = get_default_model("builtin_transformers")
            logger.info("Resolved 'auto' model to %s from config", target_path)
            if not target_path or target_path == "auto":
                logger.warning("No local builtin transformers model available")
                return False

        with self._lock:
            if self._pipeline and (not model_path or target_path == self.model_path):
                return True

            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

            device_idx = -1
            if self.device == "auto":
                try:
                    if torch.cuda.is_available():
                        _ = torch.cuda.get_device_properties(0)
                        device_idx = 0
                except Exception as exc:
                    logger.warning("CUDA probe failed; using CPU: %s", exc)
            elif self.device.startswith("cuda"):
                try:
                    device_idx = int(self.device.split(":")[1]) if ":" in self.device else 0
                except (ValueError, IndexError):
                    device_idx = 0

            dtype = (
                torch.float16
                if torch.cuda.is_available() and self.torch_dtype == "auto"
                else "auto"
            )
            offline_mode = os.getenv("TRANSFORMERS_OFFLINE", "false").lower() == "true"
            candidate_paths: List[str] = []

            def _add_candidate(value: Optional[str]) -> None:
                if value:
                    normalized = str(value).strip()
                    if normalized and normalized not in candidate_paths:
                        candidate_paths.append(normalized)

            _add_candidate(target_path)
            _add_candidate(str(Path.cwd() / "models/transformers/gpt2"))
            _add_candidate("models/transformers/gpt2")
            _add_candidate("gpt2")

            last_error: Optional[Exception] = None
            for candidate in candidate_paths:
                try:
                    abs_path = os.path.abspath(candidate)
                    resolved_path = abs_path if os.path.isdir(abs_path) else candidate
                    tokenizer = AutoTokenizer.from_pretrained(
                        resolved_path,
                        local_files_only=offline_mode,
                    )
                    model = AutoModelForCausalLM.from_pretrained(
                        resolved_path,
                        torch_dtype=dtype if dtype != "auto" else None,
                        low_cpu_mem_usage=True,
                        local_files_only=offline_mode,
                    )
                    self._pipeline = pipeline(
                        "text-generation",
                        model=model,
                        tokenizer=tokenizer,
                        device=device_idx,
                    )
                    self.model_path = resolved_path
                    self._model_name = self._resolve_model_name(resolved_path)
                    logger.info("Transformers pipeline warmed for %s", self._model_name)
                    return True
                except Exception as exc:
                    last_error = exc
                    logger.warning("Failed transformers candidate %s: %s", candidate, exc)

            logger.error("Failed to warm Transformers pipeline: %s", last_error)
            return False

    def load_model(self, model_path: Optional[str] = None) -> bool:
        return self.warm(model_path)

    def load_model_by_path(self, model_path: str) -> bool:
        return self.load_model(model_path)

    def generation_components(self) -> tuple[Any, Any, threading.RLock]:
        """Return warmed model, tokenizer, and the shared generation lock.

        This does not select a model or provider. It exposes an already-resolved
        local runtime to specialized execution adapters that must coordinate
        model-forward hooks with ordinary generation.
        """

        if not self._pipeline and self._transformers_available:
            self.warm(self.model_path)
        if not self._pipeline:
            if not self._transformers_available:
                raise ProviderNotAvailable("Transformers runtime is not available")
            raise ProviderNotAvailable("Transformers model is not warmed")
        return self._pipeline.model, self._pipeline.tokenizer, self._generation_lock

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if not self._pipeline and self._transformers_available:
            self.warm(self.model_path)

        if self._pipeline:
            try:
                max_new_tokens = kwargs.get("max_new_tokens") or kwargs.get("max_tokens") or 128
                temperature = float(kwargs.get("temperature", 0.7))
                with self._generation_lock:
                    result = self._pipeline(
                        prompt,
                        max_new_tokens=max_new_tokens,
                        temperature=temperature,
                        do_sample=temperature > 0,
                        pad_token_id=self._pipeline.tokenizer.eos_token_id,
                    )
                if result and isinstance(result, list) and "generated_text" in result[0]:
                    generated = str(result[0]["generated_text"])
                    if generated.startswith(prompt):
                        generated = generated[len(prompt):].strip()
                    elif prompt in generated:
                        generated = generated.split(prompt)[-1].strip()
                    return generated or str(result[0]["generated_text"]).strip()
            except Exception as exc:
                raise GenerationFailed(f"Transformers generation failed: {exc}") from exc

        if not self._transformers_available:
            raise ProviderNotAvailable("Transformers runtime is not available")
        raise GenerationFailed("Transformers generation failed")

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        text = self.generate(prompt, **kwargs)
        if text:
            yield text

    def stream_generate(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        yield from self.stream(prompt, **kwargs)

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        return self.generate(prompt, **kwargs)

    def embed(
        self,
        text: Union[str, List[str]],
        **kwargs: Any,
    ) -> Union[List[float], List[List[float]]]:
        is_single = isinstance(text, str)
        texts = [text] if is_single else text
        results: List[List[float]] = []
        for item in texts:
            digest = hashlib.sha256(item.encode()).hexdigest()
            results.append([float(int(digest[i % 64], 16)) / 15.0 for i in range(384)])
        return results[0] if is_single else results

    def runtime_capabilities(self) -> ModelRuntimeCapabilities:
        """Report base Transformers capabilities.

        First-token embedding control intentionally remains false here. Only a
        validated specialized adapter may advertise that capability.
        """

        return ModelRuntimeCapabilities(
            runtime_engine="transformers",
            model_id=self._model_name or "unknown",
            supports_streaming=True,
            supports_seed=False,
            supports_embeddings=False,
            supports_logprobs=False,
            supports_first_token_embedding_control=False,
        )

    @classmethod
    def get_instance(cls, **kwargs: Any) -> "TransformersRuntime":
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "name": self.provider_name,
            "provider_type": "local",
            "runtime": "transformers",
            "requires_api_key": False,
            "has_api_key": True,
            "api_key_valid": True,
            "available_models": [self._model_name],
            "default_model": self._model_name,
            "model": self._model_name,
            "device": self.device,
            "quantization": self.quantization,
            "transformers_available": self._transformers_available,
            "supports_streaming": True,
            "supports_first_token_embedding_control": False,
        }

    def shutdown(self) -> None:
        logger.info("Shutting down Transformers runtime")


__all__ = ["TransformersRuntime"]

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
    """Best-effort local text runtime backed by Transformers when installed."""

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
        self.model = self._model_name
        self._pipeline: Any = None
        self._lock = threading.Lock()

        if not self._transformers_available:
            logger.info("Transformers not installed; local runtime is unavailable")
        elif model_path:
            threading.Thread(target=self.warm, args=(model_path,), daemon=True).start()

    @staticmethod
    def _resolve_model_name(model_path: Optional[str]) -> str:
        if not model_path or model_path == "auto":
            return "auto"
        name = Path(model_path).name
        return name[:-5] if name.endswith(".gguf") else name

    def warm(self, model_path: Optional[str] = None) -> bool:
        """Pre-load the model pipeline to avoid cold-start latency."""
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
                    logger.warning("CUDA initialization failed; using CPU: %s", exc)
                    device_idx = -1
            elif self.device.startswith("cuda"):
                try:
                    device_idx = int(self.device.split(":")[1]) if ":" in self.device else 0
                except (ValueError, IndexError):
                    device_idx = 0

            dtype = (
                torch.float16
                if torch.cuda.is_available() and self.torch_dtype == "auto"
                else None
            )
            offline_mode = os.getenv("TRANSFORMERS_OFFLINE", "false").lower() == "true"

            candidates: List[str] = []
            for value in (
                target_path,
                str(Path.cwd() / "models/transformers/gpt2"),
                "models/transformers/gpt2",
                "gpt2",
            ):
                normalized = str(value or "").strip()
                if normalized and normalized not in candidates:
                    candidates.append(normalized)

            last_error: Optional[Exception] = None
            for candidate in candidates:
                try:
                    absolute = os.path.abspath(candidate)
                    resolved = absolute if os.path.isdir(absolute) else candidate
                    tokenizer = AutoTokenizer.from_pretrained(
                        resolved,
                        local_files_only=offline_mode,
                    )
                    model = AutoModelForCausalLM.from_pretrained(
                        resolved,
                        torch_dtype=dtype,
                        low_cpu_mem_usage=True,
                        local_files_only=offline_mode,
                    )
                    self._pipeline = pipeline(
                        "text-generation",
                        model=model,
                        tokenizer=tokenizer,
                        device=device_idx,
                    )
                    self.model_path = resolved
                    self._model_name = self._resolve_model_name(resolved)
                    self.model = self._model_name
                    logger.info("Transformers runtime warmed for %s", self._model_name)
                    return True
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Failed to warm Transformers candidate %s: %s",
                        candidate,
                        exc,
                    )

            logger.error("Failed to warm Transformers runtime: %s", last_error)
            return False

    def load_model(self, model_path: Optional[str] = None) -> bool:
        return self.warm(model_path)

    def load_model_by_path(self, model_path: str) -> bool:
        return self.load_model(model_path)

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text using the active local Transformers pipeline."""
        if not self._pipeline and self._transformers_available:
            self.warm(self.model_path)

        if self._pipeline:
            try:
                max_new_tokens = kwargs.get("max_new_tokens") or kwargs.get("max_tokens") or 128
                temperature = kwargs.get("temperature")
                temperature = 0.7 if temperature is None else float(temperature)
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
                        generated = generated[len(prompt) :].strip()
                    elif prompt in generated:
                        generated = generated.split(prompt)[-1].strip()
                    else:
                        generated = generated.strip()
                    return generated or str(result[0]["generated_text"]).strip()
                return ""
            except Exception as exc:
                logger.warning("Transformers generation failed: %s", exc)
                raise GenerationFailed(f"Transformers generation failed: {exc}") from exc

        if not self._transformers_available:
            raise ProviderNotAvailable("Transformers runtime is not available")
        raise GenerationFailed("Transformers generation failed")

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        raise ProviderNotAvailable("Streaming unavailable without active transformers pipeline")
        yield ""  # pragma: no cover

    def stream_generate(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        yield from self.stream(prompt, **kwargs)

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        return self.generate(prompt, **kwargs)

    def generate_response(self, prompt: str, **kwargs: Any) -> str:
        return self.generate(prompt, **kwargs)

    def embed(
        self,
        text: Union[str, List[str]],
        **kwargs: Any,
    ) -> Union[List[float], List[List[float]]]:
        """Return deterministic local embeddings until a dedicated embedding port owns this path."""
        is_single = isinstance(text, str)
        texts = [text] if is_single else text
        results: List[List[float]] = []
        for item in texts:
            digest = hashlib.sha256(item.encode()).hexdigest()
            results.append([float(int(digest[i % 64], 16)) / 15.0 for i in range(384)])
        return results[0] if is_single else results

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
            "supports_streaming": False,
        }

    def shutdown(self) -> None:
        logger.info("Shutting down Transformers runtime")
        self._pipeline = None


__all__ = ["TransformersRuntime"]

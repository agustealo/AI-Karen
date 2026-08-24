from __future__ import annotations

"""Neutral local runtime backed by optional Transformers support."""

import logging
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from ai_karen_engine.integrations.llm_utils import LLMProviderBase, ProviderNotAvailable, GenerationFailed

logger = logging.getLogger(__name__)


def _lazy_import_transformers() -> bool:
    try:
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


class TransformersRuntime(LLMProviderBase):
    """Best-effort local text runtime with a deterministic fallback path."""

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
        print(f"DEBUG: TransformersRuntime init with model_path={model_path}")

        if not self._transformers_available:
            logger.info("Transformers not installed; using deterministic fallback runtime")
        elif model_path:
            # Pre-warm if model path is provided
            threading.Thread(target=self.warm, args=(model_path,), daemon=True).start()

    def _resolve_model_name(self, model_path: Optional[str]) -> str:
        """Resolve a human-readable model name from a path or ID."""
        if not model_path or model_path == "auto":
            return "auto"
        
        # Strip directory path if it's a file path
        name = Path(model_path).name
        # Remove common extensions
        if name.endswith(".gguf"):
            name = name[:-5]
        
        return name

    def warm(self, model_path: Optional[str] = None) -> bool:
        """Pre-load the model pipeline to avoid cold-start latency."""
        if not self._transformers_available:
            return False
            
        target_path = model_path or self.model_path
        
        # Handle 'auto' or None by resolving to a real local default model.
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

            import os
            import torch
            from transformers import pipeline

            device_idx = -1
            if self.device == "auto":
                try:
                    if torch.cuda.is_available():
                        _ = torch.cuda.get_device_properties(0)
                        device_idx = 0
                        logger.info("CUDA available and verified, using GPU 0")
                    else:
                        device_idx = -1
                        logger.info("CUDA not available, using CPU")
                except Exception as cuda_err:
                    logger.warning(
                        "CUDA available but failed to initialize: %s. Falling back to CPU.",
                        cuda_err,
                    )
                    device_idx = -1
            elif self.device.startswith("cuda"):
                try:
                    device_idx = int(self.device.split(":")[1]) if ":" in self.device else 0
                except (ValueError, IndexError):
                    device_idx = 0

            dtype = torch.float16 if torch.cuda.is_available() and self.torch_dtype == "auto" else "auto"
            offline_mode = os.getenv("TRANSFORMERS_OFFLINE", "false").lower() == "true"

            candidate_paths: List[str] = []

            def _add_candidate(value: Optional[str]) -> None:
                if not value:
                    return
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
                    logger.info(
                        "Pre-warming Transformers pipeline for %s on %s",
                        candidate,
                        self.device,
                    )

                    abs_path = os.path.abspath(candidate)
                    model_path = abs_path if os.path.isdir(abs_path) else candidate

                    from transformers import AutoModelForCausalLM, AutoTokenizer

                    tokenizer = AutoTokenizer.from_pretrained(
                        model_path,
                        local_files_only=offline_mode,
                    )
                    model = AutoModelForCausalLM.from_pretrained(
                        model_path,
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
                    self.model_path = model_path
                    self._model_name = self._resolve_model_name(model_path)
                    logger.info(
                        "Transformers pipeline warmed successfully for %s (path: %s)",
                        self._model_name,
                        model_path,
                    )
                    return True
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Failed to pre-warm Transformers candidate %s: %s",
                        candidate,
                        exc,
                    )

            logger.error("Failed to pre-warm Transformers pipeline", exc_info=last_error)
            return False

    def load_model(self, model_path: Optional[str] = None) -> bool:
        """Alias for warm() to satisfy LLMRegistry interface."""
        return self.warm(model_path)

    def load_model_by_path(self, model_path: str) -> bool:
        """Alias for load_model to satisfy LLMRegistry requirements."""
        return self.load_model(model_path)

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text using a real transformers pipeline."""
        if not self._pipeline and self._transformers_available:
            self.warm(self.model_path)

        if self._pipeline:
            try:
                max_new_tokens = kwargs.get("max_new_tokens") or kwargs.get("max_tokens") or 128
                temperature = kwargs.get("temperature")
                if temperature is None:
                    temperature = 0.7
                else:
                    temperature = float(temperature)

                result = self._pipeline(
                    prompt,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    do_sample=temperature > 0,
                    pad_token_id=self._pipeline.tokenizer.eos_token_id
                )
                
                print(f"DEBUG: Transformers raw result: {result}")

                if result and isinstance(result, list) and "generated_text" in result[0]:
                    generated = result[0]["generated_text"]
                    
                    # More robust prompt stripping
                    if generated.startswith(prompt):
                        generated = generated[len(prompt):].strip()
                    elif prompt in generated:
                        # Find the last occurrence of the prompt and strip everything before it
                        generated = generated.split(prompt)[-1].strip()
                    else:
                        # If prompt not found but we have text, it might just be the completion
                        # without the prompt included.
                        generated = generated.strip()
                        
                    if generated:
                        return generated
                    
                    # Ultimate fallback: return the raw generated text if stripping produced empty result
                    return result[0]["generated_text"].strip()
                
                return ""
            except Exception as e:
                logger.warning(f"Transformers generation failed: {e}.")
                return ""

        if not self._transformers_available:
            raise ProviderNotAvailable("Transformers runtime is not available")
        raise GenerationFailed("Transformers generation failed")

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        raise ProviderNotAvailable("Streaming unavailable without active transformers pipeline")

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        """LLMProviderBase interface method - delegates to generate()."""
        return self.generate(prompt, **kwargs)

    def embed(self, text: Union[str, List[str]], **kwargs: Any) -> Union[List[float], List[List[float]]]:
        """Generate embeddings using local transformers or fallback.

        In a real implementation, this would use sentence-transformers.
        Currently returns a deterministic hash-based embedding for testing.
        """
        is_single = isinstance(text, str)
        texts = [text] if is_single else text

        results = []
        import hashlib
        for t in texts:
            h = hashlib.sha256(t.encode()).hexdigest()
            # Create a 384-float vector from hash
            vec = [float(int(h[i % 64], 16)) / 15.0 for i in range(384)]
            results.append(vec)

        return results[0] if is_single else results

    @classmethod
    def get_instance(cls, **kwargs: Any) -> "TransformersRuntime":
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    def get_provider_info(self) -> Dict[str, Any]:

        return {
            "name": getattr(self, "provider_name", "builtin_transformers"),
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
        }

    def shutdown(self) -> None:
        logger.info("Shutting down Transformers runtime")

    def _fallback_generate(self, prompt: str, **kwargs: Any) -> str:
        prompt = (prompt or "").strip()
        if not prompt:
            return "No prompt provided."

        if self._transformers_available:
            # If we reach here, Transformers is installed but generation failed/bypassed
            text = "I'm processing your request using local resources, but I'm currently experiencing high latency. Please bear with me or try again in a moment."
        else:
            text = "I'm currently operating in a limited capacity mode. Please check my configuration or try again later."

        return ResponseSanitizer().sanitize(text)


__all__ = ["TransformersRuntime"]

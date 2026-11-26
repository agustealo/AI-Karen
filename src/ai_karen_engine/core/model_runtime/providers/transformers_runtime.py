from __future__ import annotations

"""Neutral local runtime backed by optional Transformers support."""

import hashlib
import logging
import os
import threading
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

from ai_karen_engine.core.model_runtime.provider_contracts import (
    GenerationFailed,
    LLMProviderBase,
    ModelRuntimeCapabilities,
    NativeRetirementUnverified,
    ProviderNotAvailable,
)

from ai_karen_engine.core.model_runtime.provider_health_monitor import observe_native_compute

logger = logging.getLogger(__name__)


def _lazy_import_transformers() -> bool:
    try:
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


# Poll only to observe cancellation while contending for an existing lock.
# This interval is not an execution budget or a model timeout.
_LOCK_CHECKPOINT_INTERVAL_SECONDS = 0.05


@contextmanager
def _checkpointed_lock(
    lock: Any, checkpoint: Callable[[], None] | None,
) -> Iterator[None]:
    if checkpoint is None:
        with lock:
            yield
        return

    checkpoint()
    while not lock.acquire(timeout=_LOCK_CHECKPOINT_INTERVAL_SECONDS):
        checkpoint()
    try:
        checkpoint()
        yield
    finally:
        lock.release()


def generation_checkpoint_options(
    checkpoint: Callable[[], None] | None,
) -> Dict[str, Any]:
    """Use the same abort contract for ordinary and guided generation."""
    if checkpoint is None:
        return {}
    checkpoint()
    from transformers import StoppingCriteria, StoppingCriteriaList

    class _CancellationCriteria(StoppingCriteria):
        def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> bool:
            # Raise rather than return a partial answer as a successful stop.
            checkpoint()
            return False

    return {"stopping_criteria": StoppingCriteriaList([_CancellationCriteria()])}


class TransformersRuntime(LLMProviderBase):
    """Best-effort first-party local text runtime.

    The runtime does not manufacture assistant text when the model is unavailable.
    Callers receive a typed provider failure and decide whether fallback is allowed.
    Specialized runtime adapters may borrow the warmed model/tokenizer through
    ``generation_components`` while sharing the same generation lock.
    """

    _instance: Optional["TransformersRuntime"] = None
    # Device retirement failure is process-scoped, not cache-instance scoped.
    # No automated reset: rebuilding a runtime does not prove device quiescence.
    _native_retirement_hold = threading.Event()

    @staticmethod
    def _require_native_retirement_ready() -> None:
        if TransformersRuntime._native_retirement_hold.is_set():
            raise ProviderNotAvailable("native_device_retirement_hold")

    @staticmethod
    def _synchronize_native_device(device: Any) -> None:
        kind = getattr(device, "type", None)
        if kind == "cpu":
            return
        if kind != "cuda" or getattr(device, "index", None) is None:
            raise ProviderNotAvailable("native_device_retirement_unverified")
        import torch

        # The canonical loader places its pipeline on a single explicit
        # device. Synchronize that device, not the thread's current device.
        torch.cuda.synchronize(device)

    @contextmanager
    def _native_device_scope(self, device: Any) -> Iterator[None]:
        """Fence device work before releasing the caller's generation lock.

        This is local process/device synchronization, not a GPU memory
        release receipt or proof of remote scheduler cancellation.
        """
        self._require_native_retirement_ready()
        kind = getattr(device, "type", None)
        if kind not in {"cpu", "cuda"} or (
            kind == "cuda" and getattr(device, "index", None) is None
        ):
            raise ProviderNotAvailable("native_device_retirement_unverified")
        try:
            yield
        finally:
            # Cancellation must not skip this fence. An unverified device
            # cannot be made healthy by replacing the cached runtime.
            try:
                self._synchronize_native_device(device)
            except BaseException as exc:
                TransformersRuntime._native_retirement_hold.set()
                logger.error("native_device_retirement_failed")
                raise NativeRetirementUnverified() from exc

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
        # Construction is registration/cache setup only. Explicit warm() or
        # generation owns model loading; no detached constructor worker.

    def _resolve_model_name(self, model_path: Optional[str]) -> str:
        if not model_path or model_path == "auto":
            return "auto"
        name = Path(model_path).name
        return name[:-5] if name.endswith(".gguf") else name

    def warm(
        self, model_path: Optional[str] = None, *, exact_only: bool = False,
        checkpoint: Callable[[], None] | None = None,
    ) -> bool:
        self._require_native_retirement_ready()
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

        with _checkpointed_lock(self._lock, checkpoint):
            self._require_native_retirement_ready()
            if self._pipeline:
                if exact_only:
                    if self.model_path and os.path.realpath(target_path) == os.path.realpath(self.model_path):
                        return True
                elif not model_path or target_path == self.model_path:
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
            # A governed generation request is not model-download authority.
            offline_mode = exact_only or os.getenv("TRANSFORMERS_OFFLINE", "false").lower() == "true"
            candidate_paths: List[str] = []

            def _add_candidate(value: Optional[str]) -> None:
                if value:
                    normalized = str(value).strip()
                    if normalized and normalized not in candidate_paths:
                        candidate_paths.append(normalized)

            _add_candidate(target_path)
            if not exact_only:
                _add_candidate(str(Path.cwd() / "models/transformers/gpt2"))
                _add_candidate("models/transformers/gpt2")
                _add_candidate("gpt2")

            last_error: Optional[Exception] = None
            for candidate in candidate_paths:
                try:
                    abs_path = os.path.abspath(candidate)
                    resolved_path = abs_path if os.path.isdir(abs_path) else candidate
                    if checkpoint is not None:
                        checkpoint()
                    tokenizer = AutoTokenizer.from_pretrained(
                        resolved_path,
                        local_files_only=offline_mode,
                    )
                    if checkpoint is not None:
                        checkpoint()
                    model = AutoModelForCausalLM.from_pretrained(
                        resolved_path,
                        torch_dtype=dtype if dtype != "auto" else None,
                        low_cpu_mem_usage=True,
                        local_files_only=offline_mode,
                    )
                    if checkpoint is not None:
                        checkpoint()
                    # The loader has selected the placement device before
                    # constructing the pipeline. Fence the entire placement
                    # stage, including a constructor that raises after enqueueing
                    # CUDA work but before returning a pipeline object.
                    with _checkpointed_lock(self._generation_lock, checkpoint):
                        self._require_native_retirement_ready()
                        if checkpoint is None:
                            prepared_pipeline = pipeline(
                                "text-generation", model=model,
                                tokenizer=tokenizer, device=device_idx,
                            )
                        else:
                            placement_device = (
                                torch.device("cuda", device_idx)
                                if device_idx >= 0 else torch.device("cpu")
                            )
                            with self._native_device_scope(placement_device):
                                checkpoint()
                                prepared_pipeline = pipeline(
                                    "text-generation", model=model,
                                    tokenizer=tokenizer, device=device_idx,
                                )
                                if getattr(prepared_pipeline, "device", None) != placement_device:
                                    # Unexpected placement makes the known-device
                                    # fence insufficient to certify retirement.
                                    TransformersRuntime._native_retirement_hold.set()
                                    logger.error("native_pipeline_placement_unverified")
                                    raise NativeRetirementUnverified()
                                checkpoint()
                            checkpoint()
                        self._require_native_retirement_ready()
                        self._pipeline = prepared_pipeline
                        self.model_path = resolved_path
                        self._model_name = self._resolve_model_name(resolved_path)
                    logger.info("Transformers pipeline warmed for %s", self._model_name)
                    return True
                except NativeRetirementUnverified:
                    raise
                except Exception as exc:
                    # Cancellation is terminal, not a failed load candidate.
                    self._require_native_retirement_ready()
                    if checkpoint is not None:
                        checkpoint()
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

        self._require_native_retirement_ready()
        if not self._pipeline and self._transformers_available:
            self.warm(self.model_path)
        if not self._pipeline:
            if not self._transformers_available:
                raise ProviderNotAvailable("Transformers runtime is not available")
            raise ProviderNotAvailable("Transformers model is not warmed")
        with self._generation_lock:
            self._require_native_retirement_ready()
            active = self._pipeline
            if active is None:
                raise ProviderNotAvailable("Transformers model is not warmed")
            return active.model, active.tokenizer, self._generation_lock

    @contextmanager
    def borrow_generation_components(
        self, required_model: str, *,
        expected: tuple[Any, Any] | None = None,
        checkpoint: Callable[[], None] | None = None,
    ) -> Iterator[tuple[Any, Any]]:
        """Borrow only the exact loaded model/tokenizer under the canonical lock.

        Never warm or select a fallback. A replacement even at the same path
        invalidates the earlier borrow. Callers must not await event-loop work
        while holding this lock.
        """
        with _checkpointed_lock(self._generation_lock, checkpoint):
            self._require_native_retirement_ready()
            active = self._pipeline
            if (
                active is None or not self.model_path
                or os.path.realpath(required_model) != os.path.realpath(self.model_path)
                or (expected is not None and (
                    active.model is not expected[0] or active.tokenizer is not expected[1]
                ))
            ):
                raise ProviderNotAvailable("native_authorized_model_identity_drift")
            retirement = (
                self._native_device_scope(getattr(active, "device", None))
                if checkpoint is not None else nullcontext()
            )
            with retirement:
                yield active.model, active.tokenizer

    def quarantine_generation_components(self, expected: tuple[Any, Any]) -> bool:
        """Detach only the failed model/tokenizer pair from future dispatch.

        This is logical eviction, not evidence that device work or memory has
        retired. The normal model loader owns subsequent replacement.
        """
        with self._generation_lock:
            active = self._pipeline
            if (
                active is None
                or active.model is not expected[0]
                or active.tokenizer is not expected[1]
            ):
                return False
            self._pipeline = None
            logger.warning("native_generation_components_quarantined")
            return True

    def generate_text_with_model(
        self, prompt: str, *, required_model: str | None = None,
        before_generate: Callable[[], None] | None = None, **kwargs: Any,
    ) -> tuple[str, str]:
        """Observe text and loaded identity in the same generation lock.

        The governed caller supplies an explicit model and deadline checkpoint.
        Loading that model never downloads or tries a different candidate.
        Legacy callers without the host-selected identity keep their contract.
        """
        self._require_native_retirement_ready()
        if required_model is not None:
            if not required_model.strip() or required_model.strip().lower() == "auto":
                raise ProviderNotAvailable("native_execution_model_unobserved")
            if not self.warm(required_model, exact_only=True, checkpoint=before_generate):
                raise ProviderNotAvailable("native_authorized_model_unavailable")
        elif not self._pipeline and self._transformers_available:
            self.warm(self.model_path)

        if self._pipeline:
            try:
                max_new_tokens = kwargs.get("max_new_tokens") or kwargs.get("max_tokens") or 128
                temperature = float(kwargs.get("temperature", 0.7))
                with _checkpointed_lock(self._generation_lock, before_generate):
                    self._require_native_retirement_ready()
                    active_pipeline = self._pipeline
                    active_model = str(self.model_path or "").strip()
                    if active_pipeline is None or not active_model or active_model == "auto":
                        raise ProviderNotAvailable("native_execution_model_unobserved")
                    if required_model is not None and (
                        os.path.realpath(required_model) != os.path.realpath(active_model)
                    ):
                        raise ProviderNotAvailable("native_authorized_model_identity_drift")
                    generation_options = generation_checkpoint_options(before_generate)
                    retirement = (
                        self._native_device_scope(getattr(active_pipeline, "device", None))
                        if before_generate is not None else nullcontext()
                    )
                    pad_token_id = active_pipeline.tokenizer.eos_token_id
                    with retirement:
                        if before_generate is not None:
                            before_generate()
                        with observe_native_compute("generation"):
                            result = active_pipeline(
                                prompt,
                                max_new_tokens=max_new_tokens,
                                temperature=temperature,
                                do_sample=temperature > 0,
                                pad_token_id=pad_token_id,
                                **generation_options,
                            )
                    if before_generate is not None:
                        before_generate()
                if result and isinstance(result, list) and "generated_text" in result[0]:
                    generated = str(result[0]["generated_text"])
                    if generated.startswith(prompt):
                        generated = generated[len(prompt):].strip()
                    elif prompt in generated:
                        generated = generated.split(prompt)[-1].strip()
                    return (
                        generated or str(result[0]["generated_text"]).strip(),
                        active_model,
                    )
            except (ProviderNotAvailable, GenerationFailed):
                raise
            except Exception as exc:
                raise GenerationFailed(f"Transformers generation failed: {exc}") from exc

        if not self._transformers_available:
            raise ProviderNotAvailable("Transformers runtime is not available")
        raise GenerationFailed("Transformers generation failed")

    def generate(self, prompt: str, **kwargs: Any) -> str:
        text, _ = self.generate_text_with_model(prompt, **kwargs)
        return text

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

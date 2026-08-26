from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Mapping


def infer_model_format(path: Path, metadata_files: set[str]) -> str:
    name = path.name.lower()
    suffixes = {suffix.lower() for suffix in path.suffixes}

    if path.is_file():
        if ".gguf" in suffixes or name.endswith(".gguf"):
            return "gguf"
        if ".onnx" in suffixes or name.endswith(".onnx"):
            return "onnx"

    if "adapter_config.json" in metadata_files or "modules.json" in metadata_files:
        return "transformers"
    if "config.json" in metadata_files or "tokenizer.json" in metadata_files:
        return "transformers"
    if any(item.endswith(".gguf") for item in metadata_files):
        return "gguf"
    return "unknown"


def infer_model_artifact_kind(model_format: str, metadata_files: set[str]) -> str:
    if "adapter_config.json" in metadata_files:
        return "adapter"
    if "modules.json" in metadata_files:
        return "sentence_transformer"
    if "1_Pooling/config.json" in metadata_files:
        return "embedding_pipeline"
    if model_format == "gguf":
        return "gguf"
    if model_format == "onnx":
        return "onnx"
    if model_format == "transformers":
        return "transformers"
    return "unknown"


def probe_runtime_compatibility(
    model_format: str,
    artifact_kind: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    adapter_only = bool(metadata.get("adapter_only"))
    capabilities = {str(item).lower() for item in (metadata.get("capabilities") or [])}
    model_type = str(metadata.get("model_type") or "").lower()
    hf_model_type = str(metadata.get("hf_model_type") or "").lower()
    architectures = {str(item).lower() for item in (metadata.get("architectures") or [])}

    compatible_runtimes: list[str] = []
    preferred_runtime = "openai_compatible"
    confidence = "external_only"
    security_flags: list[str] = []
    runtime_notes: list[str] = []

    vllm_available = bool(metadata.get("vllm_available"))

    if model_format == "transformers":
        unsupported_transformer_model = (
            hf_model_type == "qwen3_5"
            or "qwen3_5" in architectures
            or any(name.startswith("qwen3_5") for name in architectures)
        )
        embedding_like = artifact_kind in {"embedding_pipeline", "sentence_transformer"} or any(
            flag in capabilities for flag in {"embedding", "reranking", "classification"}
        )
        multimodal_like = any(flag in capabilities for flag in {"vision", "vlm_helper"})
        text_generation_like = model_type in {"text_generation", "generation", "chat"}

        if unsupported_transformer_model:
            compatible_runtimes = []
            preferred_runtime = "unsupported"
            confidence = "unsupported"
            runtime_notes.append(
                "Qwen3.5 checkpoints are not supported by this local Transformers/vLLM stack."
            )
            security_flags.append("unsupported_architecture")
        elif adapter_only:
            compatible_runtimes = ["builtin_transformers"]
            preferred_runtime = "builtin_transformers"
            confidence = "config_inferred"
            security_flags.append("adapter_only_without_base")
            runtime_notes.append("Adapter-only model; requires a configured base model for vLLM.")
        elif embedding_like or (multimodal_like and not text_generation_like) or not text_generation_like:
            compatible_runtimes = ["builtin_transformers"]
            preferred_runtime = "builtin_transformers"
            confidence = "config_inferred"
            if embedding_like:
                runtime_notes.append("Embedding or reranking model should use direct transformer runtime.")
            elif multimodal_like:
                runtime_notes.append("Multimodal helper model should use direct transformer runtime.")
            else:
                runtime_notes.append("Transformer model type not suitable for vLLM selection.")
        else:
            compatible_runtimes = ["builtin_transformers"]
            preferred_runtime = "builtin_transformers"
            confidence = "runtime_verified"
            runtime_notes.append(
                "Transformers model can run in direct fallback mode."
            )
    elif model_format == "gguf":
        compatible_runtimes = ["openai_compatible"]
        preferred_runtime = "openai_compatible"
        confidence = "runtime_verified"
        runtime_notes.append("GGUF is exposed through an OpenAI-compatible endpoint only.")
        security_flags.append("external_endpoint_only")
    elif model_format == "onnx":
        compatible_runtimes = ["builtin_transformers"]
        preferred_runtime = "builtin_transformers"
        confidence = "config_inferred"
        runtime_notes.append("ONNX is handled via direct runtime helpers.")
    else:
        compatible_runtimes = ["openai_compatible"]
        preferred_runtime = "openai_compatible"
        confidence = "external_only"
        security_flags.append("unknown_format")
        runtime_notes.append("Unknown format; treat as external endpoint only.")

    if artifact_kind == "adapter":
        security_flags.append("adapter_only_without_base")
    if not metadata.get("tokenizer_present", True):
        security_flags.append("missing_tokenizer")
    if not metadata.get("weights_present", True):
        security_flags.append("missing_weights")
    if not metadata.get("config_present", True):
        security_flags.append("missing_config")

    return {
        "compatible_runtimes": compatible_runtimes,
        "preferred_runtime": preferred_runtime,
        "compatibility_confidence": confidence,
        "security_flags": sorted(set(security_flags)),
        "runtime_notes": runtime_notes,
    }


def is_vllm_available() -> bool:
    # Local library presence
    if find_spec("vllm") is not None:
        return True
    
    # Remote/Container presence - check environment variables
    if os.getenv("VLLM_BASE_URL") or os.getenv("KAREN_VLLM_BASE_URL") or os.getenv("KAREN_VLLM_ENABLED") == "true":
        return True
        
    return False


def infer_quantization(metadata_files: set[str], path: Path) -> str | None:
    tokens = " ".join({path.name.lower(), *(item.lower() for item in metadata_files)})
    for marker in ("q4", "q5", "q6", "q8", "fp16", "bf16", "int8", "int4"):
        if marker in tokens:
            return marker
    return None


def estimate_vram_gb(size_bytes: int, model_format: str, quantization: str | None) -> float | None:
    if size_bytes <= 0:
        return None

    base = size_bytes / (1024 ** 3)
    if model_format == "gguf":
        factor = 1.1
    elif model_format == "transformers":
        factor = 1.7
    else:
        factor = 1.2

    if quantization and quantization.startswith("q"):
        factor *= 0.85
    elif quantization in {"fp16", "bf16"}:
        factor *= 1.15

    return round(base * factor, 2)

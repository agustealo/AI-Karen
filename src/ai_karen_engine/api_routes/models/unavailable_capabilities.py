"""Honest compatibility routes for removed local model capabilities.

These endpoints intentionally expose capability unavailability instead of
resurrecting the removed internal GGUF tool/provider stack or allowing legacy
routes to fail with ``NameError`` at runtime.

Remove this compatibility router once callers have migrated to governed model
artifact workflows backed by a canonical model-management service.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/api/models/local", tags=["model-management"])

_CAPABILITY_UNAVAILABLE = status.HTTP_503_SERVICE_UNAVAILABLE


def _unavailable_detail(capability: str) -> dict[str, Any]:
    return {
        "code": "MODEL_CAPABILITY_UNAVAILABLE",
        "capability": capability,
        "message": (
            f"Local {capability} is unavailable because the legacy internal GGUF "
            "toolchain was removed."
        ),
        "replacement": (
            "Use supported model artifacts directly or an explicitly configured "
            "external OpenAI-compatible model endpoint."
        ),
        "degraded_mode": True,
        "response_source": "capability_status",
    }


def _raise_unavailable(capability: str) -> None:
    raise HTTPException(
        status_code=_CAPABILITY_UNAVAILABLE,
        detail=_unavailable_detail(capability),
    )


@router.post("/convert-to-gguf")
async def convert_to_gguf_unavailable() -> None:
    _raise_unavailable("model_conversion")


@router.post("/quantize")
async def quantize_unavailable() -> None:
    _raise_unavailable("model_quantization")


@router.post("/convert-to-gguf/validate")
async def validate_conversion_unavailable() -> None:
    _raise_unavailable("model_conversion")


@router.post("/quantize/validate")
async def validate_quantization_unavailable() -> None:
    _raise_unavailable("model_quantization")


@router.get("/formats")
async def get_supported_model_formats() -> dict[str, Any]:
    """Report artifact formats without inventing removed runtime ownership."""

    return {
        "supported_formats": {
            "gguf": {
                "description": "GGUF model artifact for external compatible runtimes",
                "extensions": [".gguf"],
                "runtime_ownership": "external_openai_compatible",
                "internal_provider": False,
                "conversion_support": False,
                "quantization_support": False,
            },
            "safetensors": {
                "description": "Safe tensor format for supported local model runtimes",
                "extensions": [".safetensors"],
                "runtime_ownership": "model_runtime",
                "internal_provider": False,
                "conversion_support": False,
                "quantization_support": False,
            },
            "pytorch": {
                "description": "PyTorch-compatible model artifact",
                "extensions": [".bin", ".pt", ".pth"],
                "runtime_ownership": "model_runtime",
                "internal_provider": False,
                "conversion_support": False,
                "quantization_support": False,
            },
        },
        "recommended_format": "safetensors",
        "conversion_available": False,
        "quantization_available": False,
        "degraded_mode": False,
        "response_source": "capability_status",
    }


__all__ = ["router"]

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .runtime_metadata import RuntimeMetadata


@dataclass(frozen=True, slots=True)
class RuntimeResponseEnvelope:
    output: Any
    metadata: RuntimeMetadata
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def degraded(self) -> bool:
        return self.metadata.degraded_mode

    @property
    def response_source(self) -> str:
        return self.metadata.response_source

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "metadata": self.metadata.to_public_dict(),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

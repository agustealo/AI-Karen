from __future__ import annotations

"""Canonical, read-only platform resource snapshot authority.

This service owns safe machine-resource observation for reusable consumers such
as chat, settings, side rails, and runtime policy. It deliberately does not own
model-download queues, security policy, or automatic optimization.
"""

import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ResourceMetric:
    available: bool
    usage_percent: float | None = None
    used_bytes: int | None = None
    available_bytes: int | None = None
    total_bytes: int | None = None


@dataclass(frozen=True)
class PlatformResourceSnapshot:
    timestamp: float
    cpu: ResourceMetric
    memory: ResourceMetric
    gpu: ResourceMetric
    vram: ResourceMetric
    disk: ResourceMetric

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlatformResourceService:
    """Collect one truthful, side-effect-free resource snapshot."""

    def snapshot(self, *, disk_path: str | Path | None = None) -> PlatformResourceSnapshot:
        cpu = self._cpu()
        memory = self._memory()
        gpu, vram = self._gpu()
        disk = self._disk(Path(disk_path) if disk_path is not None else Path.cwd())
        return PlatformResourceSnapshot(
            timestamp=time.time(),
            cpu=cpu,
            memory=memory,
            gpu=gpu,
            vram=vram,
            disk=disk,
        )

    @staticmethod
    def _cpu() -> ResourceMetric:
        try:
            import psutil  # type: ignore

            return ResourceMetric(
                available=True,
                usage_percent=float(psutil.cpu_percent(interval=0.05)),
            )
        except Exception as exc:
            logger.debug("CPU utilization telemetry unavailable: %s", exc)
            return ResourceMetric(available=False)

    @staticmethod
    def _memory() -> ResourceMetric:
        try:
            import psutil  # type: ignore

            memory = psutil.virtual_memory()
            return ResourceMetric(
                available=True,
                usage_percent=float(memory.percent),
                used_bytes=int(memory.used),
                available_bytes=int(memory.available),
                total_bytes=int(memory.total),
            )
        except Exception as exc:
            logger.debug("psutil memory telemetry unavailable: %s", exc)

        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            total_pages = int(os.sysconf("SC_PHYS_PAGES"))
            available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
            total = page_size * total_pages
            available = page_size * available_pages
            used = max(0, total - available)
            percent = (used / total * 100.0) if total else None
            return ResourceMetric(
                available=True,
                usage_percent=percent,
                used_bytes=used,
                available_bytes=available,
                total_bytes=total,
            )
        except (AttributeError, OSError, ValueError) as exc:
            logger.debug("Fallback memory telemetry unavailable: %s", exc)
            return ResourceMetric(available=False)

    @staticmethod
    def _gpu() -> tuple[ResourceMetric, ResourceMetric]:
        try:
            import GPUtil  # type: ignore

            gpus = GPUtil.getGPUs()
            if not gpus:
                return ResourceMetric(available=False), ResourceMetric(available=False)

            gpu_usage = sum(float(gpu.load) * 100.0 for gpu in gpus) / len(gpus)
            total_mb = sum(float(gpu.memoryTotal) for gpu in gpus)
            used_mb = sum(float(gpu.memoryUsed) for gpu in gpus)
            free_mb = sum(float(gpu.memoryFree) for gpu in gpus)
            vram_usage = (used_mb / total_mb * 100.0) if total_mb else None
            mb = 1024 * 1024

            return (
                ResourceMetric(available=True, usage_percent=gpu_usage),
                ResourceMetric(
                    available=True,
                    usage_percent=vram_usage,
                    used_bytes=int(used_mb * mb),
                    available_bytes=int(free_mb * mb),
                    total_bytes=int(total_mb * mb),
                ),
            )
        except Exception as exc:
            logger.debug("GPU telemetry unavailable: %s", exc)
            return ResourceMetric(available=False), ResourceMetric(available=False)

    @staticmethod
    def _disk(path: Path) -> ResourceMetric:
        try:
            path.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(path)
            percent = (usage.used / usage.total * 100.0) if usage.total else None
            return ResourceMetric(
                available=True,
                usage_percent=percent,
                used_bytes=int(usage.used),
                available_bytes=int(usage.free),
                total_bytes=int(usage.total),
            )
        except OSError as exc:
            logger.debug("Disk telemetry unavailable for %s: %s", path, exc)
            return ResourceMetric(available=False)


_platform_resource_service = PlatformResourceService()


def get_platform_resource_service() -> PlatformResourceService:
    return _platform_resource_service


__all__ = [
    "PlatformResourceService",
    "PlatformResourceSnapshot",
    "ResourceMetric",
    "get_platform_resource_service",
]

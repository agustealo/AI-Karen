from __future__ import annotations

try:
    from pydantic import BaseModel
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel


class SpacyConfig(BaseModel):
    model_name: str = "en_core_web_sm"
    disabled_components: list[str] = ["textcat"]
    enable_fallback: bool = True
    cache_size: int = 1000
    cache_ttl: int = 3600
    download_missing: bool = True
    enabled: bool = True

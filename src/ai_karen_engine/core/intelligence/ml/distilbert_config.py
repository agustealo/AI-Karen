from __future__ import annotations

try:
    from pydantic import BaseModel
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel


class DistilBertConfig(BaseModel):
    model_name: str = "distilbert-base-uncased"
    local_model_root: str = "models/transformers"
    transformers_cache_dir: str = ""
    hf_home: str = ""
    max_length: int = 512
    batch_size: int = 32
    enable_gpu: bool = False
    enable_fallback: bool = True
    cache_size: int = 5000
    cache_ttl: int = 7200
    embedding_dimension: int = 768
    pooling_strategy: str = "mean"
    enabled: bool = True

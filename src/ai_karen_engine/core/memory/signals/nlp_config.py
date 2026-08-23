"""
Configuration models for NLP services (spaCy and DistilBERT).
"""

from __future__ import annotations

import os

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, Field


class SpacyConfig(BaseModel):
    """Configuration for spaCy service."""
    
    def __init__(self, **data):
        try:
            from ai_karen_engine.config.config_manager import get_config
            config = get_config()
            model_name = config.spacy_model
        except Exception:
            # Fallback to environment variable or hardcoded system default
            model_name = os.getenv("SPACY_MODEL", "en_core_web_sm")
        
        # Set defaults - enable parser for dependency parsing as required by task 3.2
        # Allow toggling auto-download behavior via env var (defaults to auto-download missing models)
        download_missing_env = os.getenv("SPACY_DOWNLOAD_MISSING", "true").lower() in ("1", "true", "yes")

        defaults = {
            "model_name": model_name,
            "disabled_components": ["textcat"],  # Keep parser enabled for dependency parsing
            "enable_fallback": True,
            "cache_size": 1000,
            "cache_ttl": 3600,
            "download_missing": download_missing_env,
            "local_model_root": "models/spacy",
        }
        defaults.update(data)
        super().__init__(**defaults)
    
    model_name: str = "en_core_web_sm"
    disabled_components: list[str] = ["textcat"]  # Keep parser enabled for dependency parsing
    enable_fallback: bool = True
    cache_size: int = 1000
    cache_ttl: int = 3600
    download_missing: bool = True
    local_model_root: str = "models/spacy"
    enabled: bool = True


class DistilBertConfig(BaseModel):
    """Configuration for DistilBERT service."""
    
    def __init__(self, **data):
        # Set defaults
        local_model_root = os.getenv("KARI_TRANSFORMERS_DIR", "models/transformers")
        transformers_cache_dir = os.getenv("TRANSFORMERS_CACHE_DIR", "")
        hf_home = os.getenv("HF_HOME", "")
        try:
            from ai_karen_engine.config.config_manager import get_config
            config = get_config()
            model_name = config.llm.default_nlp_model_id
            local_model_root = getattr(config.llm, "transformers_dir", local_model_root) or local_model_root
        except Exception:
            model_name = os.getenv("TRANSFORMER_MODEL", "distilbert-base-uncased")

        defaults = {
            "model_name": model_name,
            "local_model_root": local_model_root,
            "transformers_cache_dir": transformers_cache_dir,
            "hf_home": hf_home,
            "max_length": 512,
            "batch_size": 32,
            "enable_gpu": os.getenv("DISTILBERT_ENABLE_GPU", "false").lower() in ("1", "true", "yes"),
            "enable_fallback": True,
            "cache_size": 5000,
            "cache_ttl": 7200,
            "embedding_dimension": 768,
            "pooling_strategy": "mean"
        }
        defaults.update(data)
        super().__init__(**defaults)
    
    model_name: str = "default-nlp-model"
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


class SmallLanguageModelConfig(BaseModel):
    """Configuration for Small Language Model service."""
    
    def __init__(self, **data):
        # Set defaults
        model_name = "default-lightweight-model"
        try:
            from ai_karen_engine.config.config_manager import get_config
            config = get_config()
            model_name = config.llm.default_lightweight_model_id
        except Exception:
            model_name = os.getenv("SMALL_LANGUAGE_MODEL_NAME", "default-lightweight-model")

        defaults = {
            "model_name": model_name,
            "max_tokens": 150,
            "temperature": 0.7,
            "enable_fallback": True,
            "cache_size": 1000,
            "cache_ttl": 1800,
            "scaffold_max_tokens": 100,
            "outline_max_tokens": 80,
            "summary_max_tokens": 120
        }
        defaults.update(data)
        super().__init__(**defaults)
    
    model_name: str = "default-lightweight-model"
    max_tokens: int = 150
    temperature: float = 0.7
    enable_fallback: bool = True
    cache_size: int = 1000
    cache_ttl: int = 1800
    scaffold_max_tokens: int = 100
    outline_max_tokens: int = 80
    summary_max_tokens: int = 120
    enabled: bool = True


class NLPConfig(BaseModel):
    """Combined NLP configuration."""
    
    def __init__(self, **data):
        # Set defaults
        defaults = {
            "spacy": SpacyConfig(),
            "distilbert": DistilBertConfig(),
            "small_language_model": SmallLanguageModelConfig(),
            "enable_monitoring": True,
            "health_check_interval": 60,
            "retry_attempts": 3,
            "retry_backoff_factor": 2.0
        }
        
        # Handle nested config objects
        for key, value in data.items():
            if key == "spacy" and isinstance(value, dict):
                defaults[key] = SpacyConfig(**value)
            elif key == "distilbert" and isinstance(value, dict):
                defaults[key] = DistilBertConfig(**value)
            elif key == "small_language_model" and isinstance(value, dict):
                defaults[key] = SmallLanguageModelConfig(**value)
            else:
                defaults[key] = value
        
        super().__init__(**defaults)
    
    spacy: SpacyConfig = Field(default_factory=SpacyConfig)
    distilbert: DistilBertConfig = Field(default_factory=DistilBertConfig)
    small_language_model: SmallLanguageModelConfig = Field(default_factory=SmallLanguageModelConfig)
    enable_monitoring: bool = True
    health_check_interval: int = 60
    retry_attempts: int = 3
    retry_backoff_factor: float = 2.0

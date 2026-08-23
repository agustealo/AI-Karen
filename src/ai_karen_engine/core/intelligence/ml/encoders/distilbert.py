from __future__ import annotations

import asyncio
import hashlib
import importlib
import logging
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from ai_karen_engine.core.intelligence.ml.contracts import (
    EncoderHealthStatus,
    SemanticEncoder,
    SemanticEncoding,
)
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry

try:
    from ai_karen_engine.core.memory.signals.nlp_config import DistilBertConfig
except ImportError:
    from ai_karen_engine.core.intelligence.ml.distilbert_config import DistilBertConfig

try:
    from cachetools import TTLCache
except ImportError:
    class TTLCache(dict):
        def __init__(self, maxsize: int, ttl: float):
            super().__init__()
            self.maxsize = maxsize
            self.ttl = ttl
            self._expires: dict[Any, float] = {}

        def _purge_expired(self) -> None:
            now = time.time()
            expired = [key for key, deadline in self._expires.items() if deadline <= now]
            for key in expired:
                self._expires.pop(key, None)
                super().pop(key, None)

        def __contains__(self, key) -> bool:
            self._purge_expired()
            return super().__contains__(key)

        def __getitem__(self, key):
            self._purge_expired()
            return super().__getitem__(key)

        def get(self, key, default=None):
            self._purge_expired()
            return super().get(key, default)

        def __setitem__(self, key, value) -> None:
            self._purge_expired()
            if key not in self and len(self) >= self.maxsize:
                oldest_key = min(self._expires, key=self._expires.get)
                self._expires.pop(oldest_key, None)
                super().pop(oldest_key, None)
            self._expires[key] = time.time() + self.ttl
            super().__setitem__(key, value)

        def __len__(self) -> int:
            self._purge_expired()
            return super().__len__()

logger = logging.getLogger(__name__)

torch = None
AutoTokenizer = None
AutoModel = None
_TRANSFORMERS_STACK_STATUS: bool | None = None


def _ensure_transformers_stack() -> bool:
    global torch, AutoTokenizer, AutoModel, _TRANSFORMERS_STACK_STATUS
    if _TRANSFORMERS_STACK_STATUS is not None:
        return _TRANSFORMERS_STACK_STATUS
    try:
        torch = importlib.import_module("torch")
        transformers_module = importlib.import_module("transformers")
        AutoTokenizer = transformers_module.AutoTokenizer
        AutoModel = transformers_module.AutoModel
        _TRANSFORMERS_STACK_STATUS = True
    except Exception as exc:
        torch = None
        AutoTokenizer = None
        AutoModel = None
        _TRANSFORMERS_STACK_STATUS = False
        logger.info("Transformers stack unavailable; using fallback mode (%s)", exc)
    return _TRANSFORMERS_STACK_STATUS


def _default_huggingface_hub_dir() -> Path:
    return Path.home() / ".cache" / "huggingface" / "hub"


class DistilBertSemanticEncoder(SemanticEncoder):
    def __init__(self, config: DistilBertConfig | None = None, registry: MLModelRegistry | None = None) -> None:
        self.config = config or DistilBertConfig()
        self.registry = registry or MLModelRegistry()
        self.tokenizer = None
        self.model = None
        self.device = None
        self.fallback_mode = False
        self.cache = TTLCache(maxsize=self.config.cache_size, ttl=self.config.cache_ttl)
        self.lock = threading.RLock()
        self._cache_hits = 0
        self._cache_misses = 0
        self._processing_times: list[float] = []
        self._error_count = 0
        self._last_error: str | None = None
        self._initialize()

    def _initialize(self) -> None:
        if not _ensure_transformers_stack():
            logger.info("DistilBERT encoder running in lightweight fallback mode")
            self.fallback_mode = True
            return
        try:
            self.device = self._setup_device()
            self.tokenizer, self.model = self._load_model()
            if self.tokenizer is None or self.model is None:
                self.fallback_mode = True
        except Exception as exc:
            logger.error("Failed to initialize DistilBERT encoder: %s", exc)
            self._last_error = str(exc)
            self._error_count += 1
            if self.config.enable_fallback:
                self.fallback_mode = True
            else:
                raise

    def _setup_device(self):
        if torch is None:
            return "cpu"
        try:
            if self.config.enable_gpu and torch.cuda.is_available():
                return torch.device("cuda")
        except Exception:
            pass
        return torch.device("cpu")

    def _load_model(self):
        try:
            resolved = self._resolve_model_source(
                self.config.model_name,
                self.config.transformers_cache_dir,
                self.config.hf_home,
            )
            if AutoTokenizer is None or AutoModel is None:
                raise RuntimeError("Transformers library is unavailable")
            tokenizer = AutoTokenizer.from_pretrained(resolved, local_files_only=True)
            model = AutoModel.from_pretrained(resolved, local_files_only=True)
            model.to(self.device)
            model.eval()
            for param in model.parameters():
                param.requires_grad = False
            return tokenizer, model
        except Exception as exc:
            logger.error("Failed to load DistilBERT model: %s", exc)
            return None, None

    def _resolve_model_source(self, model_name: str, transformers_cache_dir: str, hf_home: str) -> str:
        huggingface_hub_dir = _default_huggingface_hub_dir()
        candidate_dirs = [
            Path(self.config.local_model_root) / model_name,
            Path(transformers_cache_dir) / model_name if transformers_cache_dir else None,
            Path(transformers_cache_dir) / "models--" / model_name if transformers_cache_dir else None,
            Path(transformers_cache_dir) / "hub" / f"models--{model_name.replace('/', '--')}" if transformers_cache_dir else None,
            Path(hf_home) / "hub" / f"models--{model_name.replace('/', '--')}" if hf_home else None,
            huggingface_hub_dir / f"models--{model_name.replace('/', '--')}",
        ]
        for candidate in candidate_dirs:
            if candidate and candidate.exists():
                if (candidate / "config.json").exists():
                    return str(candidate)
                snapshots_dir = candidate / "snapshots"
                if snapshots_dir.exists():
                    for snapshot in sorted(snapshots_dir.iterdir()):
                        if (snapshot / "config.json").exists():
                            return str(snapshot)
        return model_name

    async def encode(self, text: str) -> SemanticEncoding:
        if not text or not text.strip():
            return SemanticEncoding(vector=[], dimensions=0, model_id="", model_version="", fallback_used=True)
        cache_key = self._get_cache_key(text)
        with self.lock:
            if cache_key in self.cache:
                self._cache_hits += 1
                cached = self.cache[cache_key]
                return SemanticEncoding(
                    vector=cached.embeddings,
                    dimensions=len(cached.embeddings),
                    model_id=self.config.model_name if not cached.used_fallback else "fallback",
                    model_version="current",
                    normalized=cached.normalized if hasattr(cached, 'normalized') else False,
                    fallback_used=cached.used_fallback,
                    latency_ms=cached.processing_time * 1000.0,
                )
            self._cache_misses += 1

        start = time.time()
        try:
            if self.fallback_mode or not self.model:
                embedding = await self._fallback_embedding(text)
                used_fallback = True
                model_id = "fallback"
            else:
                embedding = await self._generate_embedding(text)
                used_fallback = False
                model_id = self.config.model_name
            latency = (time.time() - start) * 1000.0
            return SemanticEncoding(
                vector=embedding,
                dimensions=len(embedding),
                model_id=model_id,
                model_version="current",
                normalized=True,
                fallback_used=used_fallback,
                latency_ms=latency,
            )
        except Exception as exc:
            logger.error("Encode failed: %s", exc)
            self._error_count += 1
            self._last_error = str(exc)
            if not self.fallback_mode and self.config.enable_fallback:
                embedding = await self._fallback_embedding(text)
                latency = (time.time() - start) * 1000.0
                return SemanticEncoding(
                    vector=embedding,
                    dimensions=len(embedding),
                    model_id="fallback",
                    model_version="current",
                    fallback_used=True,
                    latency_ms=latency,
                )
            raise

    async def encode_batch(self, texts: list[str]) -> list[SemanticEncoding]:
        return [await self.encode(text) for text in texts]

    async def _generate_embedding(self, text: str) -> list[float]:
        if self.tokenizer is None:
            raise RuntimeError("Tokenizer not initialized")
        inputs = self.tokenizer(text, truncation=True, padding=True, return_tensors="pt", max_length=self.config.max_length)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        loop = asyncio.get_event_loop()
        outputs = await loop.run_in_executor(None, self._model_forward, inputs)
        if self.config.pooling_strategy == "mean":
            embeddings = outputs.last_hidden_state.mean(dim=1).squeeze()
        elif self.config.pooling_strategy == "cls":
            embeddings = outputs.last_hidden_state[:, 0, :].squeeze()
        elif self.config.pooling_strategy == "max":
            embeddings = outputs.last_hidden_state.max(dim=1)[0].squeeze()
        else:
            embeddings = outputs.last_hidden_state.mean(dim=1).squeeze()
        return embeddings.cpu().numpy().tolist()

    def _model_forward(self, inputs):
        if self.model is None:
            raise RuntimeError("Model not initialized")
        if torch is not None:
            with torch.no_grad():
                return self.model(**inputs)
        return self.model(**inputs)

    async def _fallback_embedding(self, text: str) -> list[float]:
        hash_functions = [
            lambda x: hashlib.md5(x.encode()).digest(),
            lambda x: hashlib.sha1(x.encode()).digest(),
            lambda x: hashlib.sha256(x.encode()).digest(),
        ]
        embedding = []
        for hash_func in hash_functions:
            hash_bytes = hash_func(text)
            for i in range(0, len(hash_bytes), 4):
                chunk = hash_bytes[i:i + 4]
                if len(chunk) == 4:
                    value = int.from_bytes(chunk, byteorder='big', signed=True)
                    embedding.append(float(value) / (2**31))
        target_dim = self.config.embedding_dimension
        while len(embedding) < target_dim:
            remaining = target_dim - len(embedding)
            to_add = min(remaining, len(embedding))
            embedding.extend(embedding[:to_add])
        return embedding[:target_dim]

    def _normalize_embedding(self, embedding: list[float]) -> list[float]:
        arr = np.array(embedding)
        norm = np.linalg.norm(arr)
        if norm > 0:
            return (arr / norm).tolist()
        return embedding

    def _get_cache_key(self, text: str) -> str:
        config_hash = hashlib.md5(f"{self.config.model_name}_{self.config.pooling_strategy}_{self.config.max_length}".encode()).hexdigest()[:8]
        return f"distilbert:{config_hash}:{hashlib.md5(text.encode()).hexdigest()}"

    async def health(self) -> dict[str, Any]:
        with self.lock:
            cache_total = self._cache_hits + self._cache_misses
            cache_hit_rate = self._cache_hits / cache_total if cache_total > 0 else 0.0
            avg_processing_time = sum(self._processing_times) / len(self._processing_times) if self._processing_times else 0.0
            status = EncoderHealthStatus.DEGRADED.value if self.fallback_mode else EncoderHealthStatus.READY.value
            return {
                "status": status,
                "model_loaded": self.model is not None,
                "fallback_mode": self.fallback_mode,
                "device": str(self.device) if self.device else "unknown",
                "cache_size": len(self.cache),
                "cache_hit_rate": cache_hit_rate,
                "avg_processing_time": avg_processing_time,
                "error_count": self._error_count,
                "last_error": self._last_error,
            }

    async def metadata(self) -> dict[str, Any]:
        return {
            "model_id": self.config.model_name,
            "model_version": "current",
            "fallback_used": self.fallback_mode,
            "device": str(self.device) if self.device else "unknown",
        }

    def clear_cache(self) -> None:
        with self.lock:
            self.cache.clear()

    def reset_metrics(self) -> None:
        with self.lock:
            self._cache_hits = 0
            self._cache_misses = 0
            self._processing_times = []
            self._error_count = 0
            self._last_error = None

"""
Unified Model Store System

This module implements a unified model store that serves as the single source of truth
for all models in the system. It tracks model metadata, manages compatibility detection
between models and runtimes, and provides operations for model registration, scanning,
and deletion.

Key Features:
- Unified model registry for all formats (GGUF, safetensors, etc.)
- Automatic compatibility detection between models and runtimes
- Local model scanning and metadata extraction
- Model registration and deletion operations
- Integration with provider and runtime registry
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from ai_karen_engine.integrations.registry import ModelMetadata, get_registry

logger = logging.getLogger(__name__)

# -----------------------------
# Data Models
# -----------------------------

@dataclass
class ModelDescriptor:
    """Extended model descriptor with additional metadata for the model store."""
    # Core identification
    id: str
    name: str
    family: str = ""  # llama, mistral, qwen, phi, etc.
    format: str = ""  # gguf, safetensors, fp16, etc.
    
    # Size and quantization info
    size: Optional[int] = None  # Size in bytes
    parameters: Optional[str] = None  # 7B, 13B, etc.
    quantization: Optional[str] = None  # Q4_K_M, fp16, etc.
    context_length: Optional[int] = None
    
    # Source and location
    source: str = ""  # huggingface, local, openai, etc.
    provider: str = ""  # Provider that manages this model
    local_path: Optional[str] = None
    download_url: Optional[str] = None
    
    # Metadata
    license: Optional[str] = None
    description: str = ""
    tags: Set[str] = field(default_factory=set)
    capabilities: Set[str] = field(default_factory=set)
    
    # Store metadata
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    last_used: Optional[float] = None
    usage_count: int = 0
    
    # Computed fields
    compatible_runtimes: List[str] = field(default_factory=list)
    optimal_runtime: Optional[str] = None
    
    def __post_init__(self):
        """Initialize computed fields and timestamps."""
        if self.created_at is None:
            self.created_at = time.time()
        if self.updated_at is None:
            self.updated_at = time.time()
    
    def to_model_metadata(self) -> ModelMetadata:
        """Convert to ModelMetadata for registry compatibility."""
        return ModelMetadata(
            id=self.id,
            name=self.name,
            provider=self.provider,
            family=self.family,
            format=self.format,
            size=self.size,
            parameters=self.parameters,
            quantization=self.quantization,
            context_length=self.context_length,
            capabilities=self.capabilities.copy(),
            local_path=self.local_path,
            download_url=self.download_url,
            license=self.license,
            description=self.description
        )
    
    @classmethod
    def from_model_metadata(cls, meta: ModelMetadata, **kwargs) -> ModelDescriptor:
        """Create ModelDescriptor from ModelMetadata."""
        return cls(
            id=meta.id,
            name=meta.name,
            family=meta.family,
            format=meta.format,
            size=meta.size,
            parameters=meta.parameters,
            quantization=meta.quantization,
            context_length=meta.context_length,
            source=kwargs.get("source", ""),
            provider=meta.provider,
            local_path=meta.local_path,
            download_url=meta.download_url,
            license=meta.license,
            description=meta.description,
            tags=set(kwargs.get("tags", [])),
            capabilities=meta.capabilities.copy(),
            **kwargs
        )


@dataclass
class LocalModel:
    """Information about a locally available model file."""
    path: str
    name: str
    format: str
    size: int
    checksum: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Extract metadata from file if not provided."""
        if self.checksum is None:
            self.checksum = self._calculate_checksum()
        
        if self.metadata is None:
            self.metadata = self._extract_metadata()
    
    def _calculate_checksum(self) -> str:
        """Calculate SHA256 checksum of the model file."""
        try:
            sha256_hash = hashlib.sha256()
            with open(self.path, "rb") as f:
                # Read in chunks to handle large files
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.warning(f"Failed to calculate checksum for {self.path}: {e}")
            return ""
    
    def _extract_metadata(self) -> Dict[str, Any]:
        """Extract metadata from model file."""
        metadata = {}
        
        try:
            if self.format == "gguf":
                metadata.update(self._extract_gguf_metadata())
            elif self.format in ["safetensors", "bin"]:
                metadata.update(self._extract_safetensors_metadata())
        except Exception as e:
            logger.debug(f"Failed to extract metadata from {self.path}: {e}")
        
        return metadata
    
    def _extract_gguf_metadata(self) -> Dict[str, Any]:
        """Extract metadata from GGUF file."""
        filename = Path(self.path).stem
        metadata: Dict[str, Any] = {}

        # Attempt to use gguf reader if available for accurate header parsing
        try:
            try:
                import gguf  # type: ignore
            except Exception:  # pragma: no cover
                gguf = None  # type: ignore
            if gguf is not None:
                try:
                    # Newer gguf versions may accept just (path), older: (path, 'r')
                    try:
                        reader = gguf.GGUFReader(self.path)  # type: ignore
                    except TypeError:
                        reader = gguf.GGUFReader(self.path, 'r')  # type: ignore

                    # Try a few common metadata keys
                    possible_maps = []
                    for attr in ("metadata", "kv_data", "kv", "fields"):
                        if hasattr(reader, attr):
                            val = getattr(reader, attr)
                            if isinstance(val, dict):
                                possible_maps.append(val)
                    # Fallback: attempt get_field like accessors
                    def _get_from_reader(key: str):
                        for method in ("get_field", "get_kv", "get"):
                            if hasattr(reader, method):
                                fn = getattr(reader, method)
                                try:
                                    return fn(key)
                                except Exception:
                                    pass
                        for m in possible_maps:
                            if key in m:
                                return m[key]
                        return None

                    ctx = None
                    for k in ("general.context_length", "llama.context_length", "context_length"):
                        v = _get_from_reader(k)
                        if isinstance(v, int):
                            ctx = v
                            break
                    if ctx:
                        metadata["context_length"] = ctx

                    arch = None
                    for k in ("general.architecture", "llama.architecture", "architecture"):
                        v = _get_from_reader(k)
                        if isinstance(v, str):
                            arch = v
                            break
                    if arch:
                        metadata["family"] = arch
                except Exception:
                    pass  # Fall back to filename inference
        except Exception:
            # Any import/runtime issues: continue with filename-based hints
            pass

        # Filename-based hints for quantization/parameters as fallback or complement
        try:
            quant_patterns = ["Q2_K", "Q3_K", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0", "IQ2_M", "IQ3_M", "IQ4_M"]
            for pattern in quant_patterns:
                if pattern.lower() in filename.lower():
                    metadata.setdefault("quantization", pattern)
                    break
            param_patterns = ["1.1B", "7B", "13B", "30B", "65B", "70B"]
            for pattern in param_patterns:
                if pattern.lower() in filename.lower():
                    metadata.setdefault("parameters", pattern)
                    break
        except Exception:
            pass

        return metadata
    
    def _extract_safetensors_metadata(self) -> Dict[str, Any]:
        """Extract metadata from safetensors file."""
        # This would require safetensors library
        # For now, return basic info
        return {}


# -----------------------------
# Model Store Implementation
# -----------------------------

class ModelStore:
    """
    Unified model store that serves as the single source of truth for all models.
    
    This store manages model metadata, tracks compatibility with runtimes,
    and provides operations for model registration, scanning, and deletion.
    """
    
    def __init__(self, db_path: Optional[str] = None, models_dir: Optional[str] = None):
        """
        Initialize the model store.
        
        Args:
            db_path: Path to SQLite database file (default: ~/.ai_karen/models.db)
            models_dir: Directory to scan for local models (default: ~/.ai_karen/models)
        """
        self.db_path = db_path or self._get_default_db_path()
        self.models_dir = Path(models_dir or self._get_default_models_dir())
        self._lock = threading.RLock()
        
        # Ensure directories exist
        self.models_dir.mkdir(parents=True, exist_ok=True)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
        
        # Cache for frequently accessed data
        self._model_cache: Dict[str, ModelDescriptor] = {}
        self._cache_timestamp = 0
        self._cache_ttl = 300  # 5 minutes
    
    def _get_default_db_path(self) -> str:
        """Get default database path."""
        home = Path.home()
        return str(home / ".ai_karen" / "models.db")
    
    def _get_default_models_dir(self) -> str:
        """Get default models directory."""
        home = Path.home()
        return str(home / ".ai_karen" / "models")
    
    def _init_database(self) -> None:
        """Initialize SQLite database with model tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS models (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    family TEXT,
                    format TEXT,
                    size INTEGER,
                    parameters TEXT,
                    quantization TEXT,
                    context_length INTEGER,
                    source TEXT,
                    provider TEXT,
                    local_path TEXT,
                    download_url TEXT,
                    license TEXT,
                    description TEXT,
                    tags TEXT,  -- JSON array
                    capabilities TEXT,  -- JSON array
                    created_at REAL,
                    updated_at REAL,
                    last_used REAL,
                    usage_count INTEGER DEFAULT 0,
                    compatible_runtimes TEXT,  -- JSON array
                    optimal_runtime TEXT
                )
            """)
            
            # Create indexes for common queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_models_family ON models(family)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_models_format ON models(format)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_models_provider ON models(provider)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_models_source ON models(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_models_local_path ON models(local_path)")
            
            conn.commit()
    
    # ---------- Model Registration ----------
    
    def register_model(self, descriptor: ModelDescriptor) -> str:
        """
        Register a model in the store.
        
        Args:
            descriptor: Model descriptor with metadata
            
        Returns:
            Model ID
        """
        with self._lock:
            # Update compatibility information
            self._update_compatibility(descriptor)
            
            # Update timestamps
            descriptor.updated_at = time.time()
            if descriptor.created_at is None:
                descriptor.created_at = descriptor.updated_at
            
            # Store in database
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO models (
                        id, name, family, format, size, parameters, quantization,
                        context_length, source, provider, local_path, download_url,
                        license, description, tags, capabilities, created_at,
                        updated_at, last_used, usage_count, compatible_runtimes,
                        optimal_runtime
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    descriptor.id, descriptor.name, descriptor.family, descriptor.format,
                    descriptor.size, descriptor.parameters, descriptor.quantization,
                    descriptor.context_length, descriptor.source, descriptor.provider,
                    descriptor.local_path, descriptor.download_url, descriptor.license,
                    descriptor.description, json.dumps(list(descriptor.tags)),
                    json.dumps(list(descriptor.capabilities)), descriptor.created_at,
                    descriptor.updated_at, descriptor.last_used, descriptor.usage_count,
                    json.dumps(descriptor.compatible_runtimes), descriptor.optimal_runtime
                ))
                conn.commit()
            
            # Update cache
            self._model_cache[descriptor.id] = descriptor
            
            logger.info(f"Registered model: {descriptor.id} ({descriptor.name})")
            return descriptor.id
    
    def register_from_metadata(self, metadata: ModelMetadata, **kwargs) -> str:
        """Register a model from ModelMetadata."""
        descriptor = ModelDescriptor.from_model_metadata(metadata, **kwargs)
        return self.register_model(descriptor)
    
    def unregister_model(self, model_id: str) -> bool:
        """
        Unregister a model from the store.
        
        Args:
            model_id: Model ID to unregister
            
        Returns:
            True if model was unregistered, False if not found
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM models WHERE id = ?", (model_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
            
            # Remove from cache
            self._model_cache.pop(model_id, None)
            
            if deleted:
                logger.info(f"Unregistered model: {model_id}")
            
            return deleted
    
    # ---------- Model Retrieval ----------
    
    def get_model(self, model_id: str) -> Optional[ModelDescriptor]:
        """Get model descriptor by ID."""
        with self._lock:
            # Check cache first
            if model_id in self._model_cache:
                return self._model_cache[model_id]
            
            # Query database
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,))
                row = cursor.fetchone()
            
            if not row:
                return None
            
            descriptor = self._row_to_descriptor(row)
            self._model_cache[model_id] = descriptor
            return descriptor
    
    def list_models(self, 
                   family: Optional[str] = None,
                   format: Optional[str] = None,
                   provider: Optional[str] = None,
                   source: Optional[str] = None,
                   local_only: bool = False,
                   tags: Optional[List[str]] = None) -> List[ModelDescriptor]:
        """
        List models with optional filtering.
        
        Args:
            family: Filter by model family
            format: Filter by model format
            provider: Filter by provider
            source: Filter by source
            local_only: Only return models with local files
            tags: Filter by tags (all must match)
            
        Returns:
            List of matching model descriptors
        """
        with self._lock:
            query = "SELECT * FROM models WHERE 1=1"
            params = []
            
            if family:
                query += " AND family = ?"
                params.append(family)
            
            if format:
                query += " AND format = ?"
                params.append(format)
            
            if provider:
                query += " AND provider = ?"
                params.append(provider)
            
            if source:
                query += " AND source = ?"
                params.append(source)
            
            if local_only:
                query += " AND local_path IS NOT NULL"
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()
            
            models = []
            for row in rows:
                descriptor = self._row_to_descriptor(row)
                
                # Filter by tags if specified
                if tags:
                    if not all(tag in descriptor.tags for tag in tags):
                        continue
                
                models.append(descriptor)
            
            return models
    
    def search_models(self, query: str, limit: int = 50) -> List[ModelDescriptor]:
        """
        Search models by name, description, or tags.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching model descriptors
        """
        with self._lock:
            search_query = """
                SELECT * FROM models 
                WHERE name LIKE ? OR description LIKE ? OR tags LIKE ?
                ORDER BY usage_count DESC, name ASC
                LIMIT ?
            """
            search_term = f"%{query}%"
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(search_query, (search_term, search_term, search_term, limit))
                rows = cursor.fetchall()
            
            return [self._row_to_descriptor(row) for row in rows]
    
    # ---------- Compatibility Detection ----------
    
    def compatible_runtimes(self, model_id: str) -> List[str]:
        """Get compatible runtimes for a model."""
        descriptor = self.get_model(model_id)
        if not descriptor:
            return []
        
        return descriptor.compatible_runtimes
    
    def optimal_runtime(self, model_id: str, requirements: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Get optimal runtime for a model."""
        descriptor = self.get_model(model_id)
        if not descriptor:
            return None
        
        if requirements:
            # Re-evaluate with specific requirements
            registry = get_registry()
            metadata = descriptor.to_model_metadata()
            return registry.optimal_runtime(metadata, requirements)
        
        return descriptor.optimal_runtime
    
    def _update_compatibility(self, descriptor: ModelDescriptor) -> None:
        """Update compatibility information for a model."""
        try:
            registry = get_registry()
            metadata = descriptor.to_model_metadata()
            
            # Get compatible runtimes
            descriptor.compatible_runtimes = registry.compatible_runtimes(metadata)
            
            # Get optimal runtime
            descriptor.optimal_runtime = registry.optimal_runtime(metadata)
            
        except Exception as e:
            logger.warning(f"Failed to update compatibility for {descriptor.id}: {e}")
            descriptor.compatible_runtimes = []
            descriptor.optimal_runtime = None
    
    # ---------- Local Model Scanning ----------
    
    def scan_local_models(self, directory: Optional[str] = None) -> List[LocalModel]:
        """
        Scan directory for local model files.
        
        Args:
            directory: Directory to scan (default: models_dir)
            
        Returns:
            List of discovered local models
        """
        scan_dir = Path(directory) if directory else self.models_dir
        local_models = []
        
        if not scan_dir.exists():
            logger.debug(f"Scan directory does not exist: {scan_dir}")
            return local_models
        
        # Supported model file extensions
        extensions = {
            ".gguf": "gguf",
            ".safetensors": "safetensors",
            ".bin": "bin",
            ".pt": "pytorch",
            ".pth": "pytorch"
        }
        
        try:
            for file_path in scan_dir.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in extensions:
                    try:
                        format_type = extensions[file_path.suffix.lower()]
                        size = file_path.stat().st_size
                        
                        local_model = LocalModel(
                            path=str(file_path),
                            name=file_path.stem,
                            format=format_type,
                            size=size
                        )
                        
                        local_models.append(local_model)
                        
                    except Exception as e:
                        logger.warning(f"Failed to process model file {file_path}: {e}")
                        continue
        
        except Exception as e:
            logger.error(f"Failed to scan directory {scan_dir}: {e}")
        
        logger.info(f"Scanned {len(local_models)} local models from {scan_dir}")
        return local_models
    
    def register_local_models(self, directory: Optional[str] = None) -> List[str]:
        """
        Scan and register all local models in directory.
        
        Args:
            directory: Directory to scan (default: models_dir)
            
        Returns:
            List of registered model IDs
        """
        local_models = self.scan_local_models(directory)
        registered_ids = []
        
        for local_model in local_models:
            try:
                # Create model descriptor from local model
                model_id = self._generate_model_id(local_model.name, "local")
                
                descriptor = ModelDescriptor(
                    id=model_id,
                    name=local_model.name,
                    format=local_model.format,
                    size=local_model.size,
                    source="local",
                    provider="local",
                    local_path=local_model.path,
                    description=f"Local {local_model.format.upper()} model"
                )
                
                # Extract metadata if available
                if local_model.metadata:
                    if "quantization" in local_model.metadata:
                        descriptor.quantization = local_model.metadata["quantization"]
                    if "parameters" in local_model.metadata:
                        descriptor.parameters = local_model.metadata["parameters"]
                    if "family" in local_model.metadata:
                        descriptor.family = local_model.metadata["family"]
                
                # Try to infer family from name if not set
                if not descriptor.family:
                    descriptor.family = self._infer_model_family(local_model.name)
                
                registered_id = self.register_model(descriptor)
                registered_ids.append(registered_id)
                
            except Exception as e:
                logger.warning(f"Failed to register local model {local_model.path}: {e}")
                continue
        
        logger.info(f"Registered {len(registered_ids)} local models")
        return registered_ids
    
    def _generate_model_id(self, name: str, source: str) -> str:
        """Generate a unique model ID."""
        # Create a hash-based ID to ensure uniqueness
        content = f"{source}:{name}:{time.time()}"
        hash_obj = hashlib.md5(content.encode())
        return f"{source}_{name}_{hash_obj.hexdigest()[:8]}"
    
    def _infer_model_family(self, name: str) -> str:
        """Infer model family from name."""
        name_lower = name.lower()
        
        families = {
            "llama": ["llama", "alpaca", "vicuna"],
            "mistral": ["mistral", "mixtral"],
            "qwen": ["qwen", "qwen2"],
            "phi": ["phi", "phi-2", "phi-3"],
            "gemma": ["gemma"],
            "codellama": ["codellama", "code-llama"],
            "small_llm": ["tinyllama", "tiny-llama", "phi-3-mini", "phi3-mini", "default-lightweight-model", "default-instruct-model", "default-base-model"],
            "bert": ["bert", "distilbert", "default-nlp-model", "default-classifier-model"],
            "gpt": ["gpt", "dialogpt"]
        }
        
        for family, patterns in families.items():
            if any(pattern in name_lower for pattern in patterns):
                return family
        
        return "unknown"
    
    # ---------- Model Deletion ----------
    
    def delete_model(self, model_id: str, delete_files: bool = False) -> bool:
        """
        Delete a model from the store.
        
        Args:
            model_id: Model ID to delete
            delete_files: Whether to delete local files as well
            
        Returns:
            True if model was deleted, False if not found
        """
        with self._lock:
            descriptor = self.get_model(model_id)
            if not descriptor:
                return False
            
            # Delete local files if requested
            if delete_files and descriptor.local_path:
                try:
                    file_path = Path(descriptor.local_path)
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"Deleted model file: {descriptor.local_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete model file {descriptor.local_path}: {e}")
            
            # Remove from database
            return self.unregister_model(model_id)
    
    # ---------- Usage Tracking ----------
    
    def record_usage(self, model_id: str) -> None:
        """Record usage of a model."""
        with self._lock:
            current_time = time.time()
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE models 
                    SET last_used = ?, usage_count = usage_count + 1
                    WHERE id = ?
                """, (current_time, model_id))
                conn.commit()
            
            # Update cache if present
            if model_id in self._model_cache:
                self._model_cache[model_id].last_used = current_time
                self._model_cache[model_id].usage_count += 1
    
    def get_popular_models(self, limit: int = 10) -> List[ModelDescriptor]:
        """Get most popular models by usage count."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM models 
                    ORDER BY usage_count DESC, last_used DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
            
            return [self._row_to_descriptor(row) for row in rows]
    
    # ---------- Statistics ----------
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get model store statistics."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM models")
                total_models = cursor.fetchone()[0]
                
                cursor = conn.execute("SELECT COUNT(*) FROM models WHERE local_path IS NOT NULL")
                local_models = cursor.fetchone()[0]
                
                cursor = conn.execute("SELECT family, COUNT(*) FROM models GROUP BY family")
                families = dict(cursor.fetchall())
                
                cursor = conn.execute("SELECT format, COUNT(*) FROM models GROUP BY format")
                formats = dict(cursor.fetchall())
                
                cursor = conn.execute("SELECT provider, COUNT(*) FROM models GROUP BY provider")
                providers = dict(cursor.fetchall())
                
                cursor = conn.execute("SELECT SUM(size) FROM models WHERE size IS NOT NULL")
                total_size = cursor.fetchone()[0] or 0
        
        return {
            "total_models": total_models,
            "local_models": local_models,
            "remote_models": total_models - local_models,
            "total_size_bytes": total_size,
            "families": families,
            "formats": formats,
            "providers": providers
        }
    
    # ---------- Internal Methods ----------
    
    def _row_to_descriptor(self, row: sqlite3.Row) -> ModelDescriptor:
        """Convert database row to ModelDescriptor."""
        return ModelDescriptor(
            id=row["id"],
            name=row["name"],
            family=row["family"] or "",
            format=row["format"] or "",
            size=row["size"],
            parameters=row["parameters"],
            quantization=row["quantization"],
            context_length=row["context_length"],
            source=row["source"] or "",
            provider=row["provider"] or "",
            local_path=row["local_path"],
            download_url=row["download_url"],
            license=row["license"],
            description=row["description"] or "",
            tags=set(json.loads(row["tags"] or "[]")),
            capabilities=set(json.loads(row["capabilities"] or "[]")),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used=row["last_used"],
            usage_count=row["usage_count"] or 0,
            compatible_runtimes=json.loads(row["compatible_runtimes"] or "[]"),
            optimal_runtime=row["optimal_runtime"]
        )


# -----------------------------
# Global Model Store Instance
# -----------------------------

_global_store: Optional[ModelStore] = None
_global_store_lock = threading.RLock()


def get_model_store() -> ModelStore:
    """Get the global model store instance."""
    global _global_store
    if _global_store is None:
        with _global_store_lock:
            if _global_store is None:
                _global_store = ModelStore()
    return _global_store


def initialize_model_store(db_path: Optional[str] = None, models_dir: Optional[str] = None) -> ModelStore:
    """Initialize a fresh global model store."""
    global _global_store
    with _global_store_lock:
        _global_store = ModelStore(db_path=db_path, models_dir=models_dir)
    return _global_store


# Convenience functions
def register_model(descriptor: ModelDescriptor) -> str:
    """Register a model in the global store."""
    return get_model_store().register_model(descriptor)


def get_model(model_id: str) -> Optional[ModelDescriptor]:
    """Get model from the global store."""
    return get_model_store().get_model(model_id)


def list_models(**kwargs) -> List[ModelDescriptor]:
    """List models from the global store."""
    return get_model_store().list_models(**kwargs)


def scan_local_models(directory: Optional[str] = None) -> List[LocalModel]:
    """Scan for local models."""
    return get_model_store().scan_local_models(directory)


__all__ = [
    "ModelDescriptor",
    "LocalModel",
    "ModelStore",
    "get_model_store",
    "initialize_model_store",
    "register_model",
    "get_model",
    "list_models",
    "scan_local_models",
]

"""
System Model Manager

Manages configuration and monitoring for system models including:
- local GGUF models
- default-nlp-model (transformer model)
- default-classifier-model (classification model)

This service provides:
- Model status monitoring and health checks
- Configuration management with validation
- Performance metrics collection
- Hardware compatibility checking
"""

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import psutil

logger = logging.getLogger("kari.system_model_manager")

@dataclass
class ModelStatus:
    """Model status information."""
    id: str
    name: str
    family: str
    format: str
    status: str  # "healthy", "unhealthy", "loading", "unknown"
    size: Optional[int] = None
    parameters: Optional[str] = None
    local_path: Optional[str] = None
    last_health_check: Optional[float] = None
    error_message: Optional[str] = None
    memory_usage: Optional[int] = None
    load_time: Optional[float] = None
    inference_time: Optional[float] = None

@dataclass
class LocalGGUFConfig:
    """Configuration for local GGUF models."""
    quantization: str = "Q4_K_M"
    context_length: int = 2048
    gpu_layers: int = 0
    threads: int = 4
    batch_size: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    mmap: bool = True
    mlock: bool = False

@dataclass
class TransformerConfig:
    """Configuration for transformer models."""
    # Precision settings
    precision: str = "fp16"  # fp16, bf16, int8, int4, fp32
    torch_dtype: str = "auto"
    load_in_8bit: bool = False
    load_in_4bit: bool = False
    
    # Device and memory settings
    device: str = "auto"  # auto, cpu, cuda, cuda:0, etc.
    device_map: str = "auto"  # auto, balanced, sequential, or custom mapping
    low_cpu_mem_usage: bool = True
    max_memory: Optional[Dict[str, str]] = None  # Per-device memory limits
    
    # Batch and sequence settings
    batch_size: int = 1
    max_length: int = 512
    dynamic_batch_size: bool = True  # Enable dynamic batch size recommendations
    
    # Performance optimizations
    use_cache: bool = True
    attention_implementation: str = "eager"  # eager, flash_attention_2, sdpa
    use_flash_attention: bool = False
    gradient_checkpointing: bool = False
    mixed_precision: bool = False
    compile_model: bool = False  # PyTorch 2.0 compilation
    
    # Multi-GPU settings
    multi_gpu_strategy: str = "auto"  # auto, data_parallel, model_parallel, pipeline_parallel
    gpu_memory_fraction: float = 0.9  # Fraction of GPU memory to use
    enable_cpu_offload: bool = False
    
    # Quantization settings (for 4-bit/8-bit)
    bnb_4bit_compute_dtype: str = "float16"
    bnb_4bit_use_double_quant: bool = False
    bnb_4bit_quant_type: str = "nf4"  # nf4, fp4
    
    # Advanced optimization flags
    use_bettertransformer: bool = False
    optimize_for_inference: bool = True
    enable_xformers: bool = False

@dataclass
class BasicClsConfig:
    """Configuration for basic classification models."""
    threshold: float = 0.5
    max_features: int = 10000
    ngram_range: tuple = (1, 2)
    min_df: int = 2
    max_df: float = 0.95
    use_idf: bool = True
    smooth_idf: bool = True
    sublinear_tf: bool = True

class SystemModelManager:
    """Manages system models and their configurations."""
    
    def __init__(self, models_dir: str = "models"):
        self.models_dir = Path(models_dir)
        self.config_dir = self.models_dir / "configs"
        self.config_dir.mkdir(exist_ok=True)
        
        # Get dynamic lightweight model info
        try:
            from ai_karen_engine.config.config_manager import get_config
            config = get_config()
            default_lightweight = config.llm.default_lightweight_model_id
            default_nlp = config.llm.default_nlp_model_id
            default_classifier = config.llm.default_classifier_model_id
        except Exception:
            default_lightweight = "default-lightweight-model"
            default_nlp = "default-nlp-model"
            default_classifier = "default-classifier-model"

        # System model definitions
        self.system_models = {
            "default-lightweight-model": {
                "name": "Default Lightweight Model",
                "family": "gguf",
                "format": "gguf",
                "path": self.models_dir / "local-gguf" / f"{default_lightweight}-v2.0.Q4_K_M.gguf",
                "config_class": LocalGGUFConfig,
                "capabilities": ["text-generation", "chat", "local-inference"],
                "runtime_compatibility": ["local_gguf"]
            },
            "default-nlp-model": {
                "name": "Default NLP Model",
                "family": "bert",
                "format": "safetensors",
                "path": self.models_dir / "nlp" / default_nlp,
                "config_class": TransformerConfig,
                "capabilities": ["text-classification", "embeddings", "feature-extraction"],
                "runtime_compatibility": ["transformers", "pytorch"]
            },
            "default-classifier-model": {
                "name": "Default Classifier Model",
                "family": "sklearn",
                "format": "joblib",
                "path": self.models_dir / "classifiers" / default_classifier,
                "config_class": BasicClsConfig,
                "capabilities": ["text-classification", "intent-detection"],
                "runtime_compatibility": ["sklearn", "joblib"]
            }
        }
        
        # Load existing configurations
        self._load_configurations()
    
    def _load_configurations(self):
        """Load existing model configurations."""
        self.configurations = {}
        
        for model_id, model_info in self.system_models.items():
            config_file = self.config_dir / f"{model_id}.json"
            
            if config_file.exists():
                try:
                    with open(config_file, 'r') as f:
                        config_data = json.load(f)
                    
                    # Create config object from data
                    config_class = model_info["config_class"]
                    self.configurations[model_id] = config_class(**config_data)
                    
                except Exception as e:
                    logger.error(f"Failed to load config for {model_id}: {e}")
                    # Use default configuration
                    self.configurations[model_id] = model_info["config_class"]()
            else:
                # Use default configuration
                self.configurations[model_id] = model_info["config_class"]()
    
    def get_system_models(self) -> List[Dict[str, Any]]:
        """Get all system models with their status and configuration."""
        models = []
        
        for model_id, model_info in self.system_models.items():
            status = self._check_model_health(model_id)
            config = self.configurations.get(model_id)
            
            model_data = {
                "id": model_id,
                "name": model_info["name"],
                "family": model_info["family"],
                "format": model_info["format"],
                "capabilities": model_info["capabilities"],
                "runtime_compatibility": model_info["runtime_compatibility"],
                "local_path": str(model_info["path"]),
                "status": status.status,
                "size": status.size,
                "parameters": status.parameters,
                "last_health_check": status.last_health_check,
                "error_message": status.error_message,
                "memory_usage": status.memory_usage,
                "load_time": status.load_time,
                "inference_time": status.inference_time,
                "configuration": asdict(config) if config else {},
                "is_system_model": True
            }
            
            models.append(model_data)
        
        return models
    
    def _check_model_health(self, model_id: str) -> ModelStatus:
        """Check the health status of a system model."""
        model_info = self.system_models.get(model_id)
        if not model_info:
            return ModelStatus(
                id=model_id,
                name="Unknown",
                family="unknown",
                format="unknown",
                status="unknown",
                error_message="Model not found"
            )
        
        model_path = model_info["path"]
        
        # Check if model files exist
        if not model_path.exists():
            return ModelStatus(
                id=model_id,
                name=model_info["name"],
                family=model_info["family"],
                format=model_info["format"],
                status="unhealthy",
                error_message=f"Model files not found at {model_path}",
                last_health_check=time.time()
            )
        
        # Get model size
        try:
            if model_path.is_file():
                size = model_path.stat().st_size
            else:
                # Directory - sum all files
                size = sum(f.stat().st_size for f in model_path.rglob('*') if f.is_file())
        except Exception as e:
            logger.warning(f"Failed to get size for {model_id}: {e}")
            size = None
        
        # Determine parameters based on model
        parameters = None
        if model_id == "default-lightweight-model":
            parameters = "1.1B"
        elif model_id == "default-nlp-model":
            parameters = "66M"
        elif model_id == "default-classifier-model":
            parameters = "Variable"
        
        return ModelStatus(
            id=model_id,
            name=model_info["name"],
            family=model_info["family"],
            format=model_info["format"],
            status="healthy",
            size=size,
            parameters=parameters,
            local_path=str(model_path),
            last_health_check=time.time()
        )
    
    def get_model_configuration(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific model."""
        config = self.configurations.get(model_id)
        if config:
            return asdict(config)
        return None
    
    def update_model_configuration(self, model_id: str, config_data: Dict[str, Any]) -> bool:
        """Update configuration for a specific model."""
        if model_id not in self.system_models:
            return False
        
        try:
            # Validate configuration
            model_info = self.system_models[model_id]
            config_class = model_info["config_class"]
            
            # Create new config object to validate
            new_config = config_class(**config_data)
            
            # Validate hardware compatibility
            validation_result = self._validate_configuration(model_id, new_config)
            if not validation_result["valid"]:
                logger.error(f"Configuration validation failed for {model_id}: {validation_result['error']}")
                return False
            
            # Save configuration
            self.configurations[model_id] = new_config
            self._save_configuration(model_id, new_config)
            
            logger.info(f"Updated configuration for {model_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update configuration for {model_id}: {e}")
            return False
    
    def _validate_configuration(self, model_id: str, config) -> Dict[str, Any]:
        """Validate model configuration against hardware constraints."""
        try:
            if model_id == "default-lightweight-model":
                return self._validate_local_gguf_config(config)
            elif model_id == "default-nlp-model":
                return self._validate_transformer_config(config)
            elif model_id == "default-classifier-model":
                return self._validate_basic_cls_config(config)
            
            return {"valid": True}
            
        except Exception as e:
            return {"valid": False, "error": str(e)}
    
    def _validate_local_gguf_config(self, config: LocalGGUFConfig) -> Dict[str, Any]:
        """Validate local GGUF configuration."""
        # Check GPU availability for GPU layers
        if config.gpu_layers > 0:
            try:
                import torch
                if not torch.cuda.is_available():
                    return {
                        "valid": False,
                        "error": "GPU layers requested but CUDA not available"
                    }
            except ImportError:
                return {
                    "valid": False,
                    "error": "GPU layers requested but PyTorch not available"
                }
        
        # Check memory requirements
        memory_gb = psutil.virtual_memory().total / (1024**3)
        if config.context_length > 4096 and memory_gb < 8:
            return {
                "valid": False,
                "error": f"Context length {config.context_length} requires at least 8GB RAM, but only {memory_gb:.1f}GB available"
            }
        
        # Validate quantization format
        valid_quantizations = ["Q2_K", "Q3_K", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0"]
        if config.quantization not in valid_quantizations:
            return {
                "valid": False,
                "error": f"Invalid quantization format. Valid options: {', '.join(valid_quantizations)}"
            }
        
        return {"valid": True}
    
    def _validate_transformer_config(self, config: TransformerConfig) -> Dict[str, Any]:
        """Validate transformer configuration with comprehensive hardware checks."""
        validation_errors = []
        warnings = []
        
        try:
            import torch
            torch_available = True
        except ImportError:
            torch_available = False
            validation_errors.append("PyTorch not available")
        
        # Device validation
        if torch_available:
            if "cuda" in config.device.lower():
                if not torch.cuda.is_available():
                    validation_errors.append("CUDA device requested but not available")
                else:
                    # Check specific GPU device
                    if ":" in config.device:
                        try:
                            device_id = int(config.device.split(":")[1])
                            if device_id >= torch.cuda.device_count():
                                validation_errors.append(f"GPU device {device_id} not available (only {torch.cuda.device_count()} GPUs found)")
                        except (ValueError, IndexError):
                            validation_errors.append(f"Invalid device specification: {config.device}")
        
        # Precision validation
        if config.precision == "bf16":
            if config.device == "cpu":
                validation_errors.append("bf16 precision not supported on CPU")
            elif torch_available and torch.cuda.is_available():
                # Check if GPU supports bf16
                if not torch.cuda.is_bf16_supported():
                    validation_errors.append("bf16 precision not supported on this GPU")
        
        if config.precision == "int4" and not config.load_in_4bit:
            warnings.append("int4 precision specified but load_in_4bit is False")
        
        if config.precision == "int8" and not config.load_in_8bit:
            warnings.append("int8 precision specified but load_in_8bit is False")
        
        # Quantization validation
        if config.load_in_4bit and config.load_in_8bit:
            validation_errors.append("Cannot use both 4-bit and 8-bit quantization")
        
        if (config.load_in_4bit or config.load_in_8bit) and config.device == "cpu":
            validation_errors.append("Quantization (4-bit/8-bit) requires GPU")
        
        # Memory validation
        memory_gb = psutil.virtual_memory().total / (1024**3)
        if config.batch_size > 1 and memory_gb < 8:
            warnings.append(f"Batch size {config.batch_size} may cause memory issues with {memory_gb:.1f}GB RAM")
        
        # Multi-GPU validation
        if torch_available and torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
            if config.multi_gpu_strategy != "auto" and gpu_count < 2:
                warnings.append("Multi-GPU strategy specified but only one GPU available")
        
        # Flash attention validation
        if config.use_flash_attention or config.attention_implementation == "flash_attention_2":
            try:
                import flash_attn
            except ImportError:
                warnings.append("Flash attention requested but flash-attn not installed")
        
        # Compilation validation
        if config.compile_model:
            if not torch_available:
                validation_errors.append("Model compilation requires PyTorch")
            elif hasattr(torch, 'compile'):
                # PyTorch 2.0+ required
                pass
            else:
                warnings.append("Model compilation requires PyTorch 2.0+")
        
        # GPU memory fraction validation
        if config.gpu_memory_fraction <= 0 or config.gpu_memory_fraction > 1:
            validation_errors.append("GPU memory fraction must be between 0 and 1")
        
        if validation_errors:
            return {
                "valid": False,
                "error": "; ".join(validation_errors),
                "warnings": warnings
            }
        
        return {
            "valid": True,
            "warnings": warnings
        }
    
    def _validate_basic_cls_config(self, config: BasicClsConfig) -> Dict[str, Any]:
        """Validate basic classifier configuration."""
        # Check threshold range
        if not 0.0 <= config.threshold <= 1.0:
            return {
                "valid": False,
                "error": "Threshold must be between 0.0 and 1.0"
            }
        
        # Check feature limits
        if config.max_features < 100:
            return {
                "valid": False,
                "error": "max_features should be at least 100"
            }
        
        return {"valid": True}
    
    def _save_configuration(self, model_id: str, config):
        """Save model configuration to file."""
        config_file = self.config_dir / f"{model_id}.json"
        
        try:
            with open(config_file, 'w') as f:
                json.dump(asdict(config), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save configuration for {model_id}: {e}")
    
    def reset_model_configuration(self, model_id: str) -> bool:
        """Reset model configuration to defaults."""
        if model_id not in self.system_models:
            return False
        
        try:
            # Create default configuration
            model_info = self.system_models[model_id]
            default_config = model_info["config_class"]()
            
            # Update and save
            self.configurations[model_id] = default_config
            self._save_configuration(model_id, default_config)
            
            logger.info(f"Reset configuration for {model_id} to defaults")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reset configuration for {model_id}: {e}")
            return False
    
    def get_hardware_recommendations(self, model_id: str) -> Dict[str, Any]:
        """Get hardware-specific recommendations for model configuration."""
        try:
            # Get system info
            memory_gb = psutil.virtual_memory().total / (1024**3)
            cpu_count = psutil.cpu_count()
            
            # Check GPU availability and capabilities
            gpu_available = False
            gpu_memory_gb = 0
            gpu_count = 0
            gpu_compute_capability = None
            bf16_supported = False
            
            try:
                import torch
                if torch.cuda.is_available():
                    gpu_available = True
                    gpu_count = torch.cuda.device_count()
                    gpu_memory_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                    gpu_compute_capability = torch.cuda.get_device_capability(0)
                    bf16_supported = torch.cuda.is_bf16_supported()
            except ImportError:
                pass
            
            recommendations = {
                "system_info": {
                    "memory_gb": memory_gb,
                    "cpu_count": cpu_count,
                    "gpu_available": gpu_available,
                    "gpu_memory_gb": gpu_memory_gb,
                    "gpu_count": gpu_count,
                    "gpu_compute_capability": gpu_compute_capability,
                    "bf16_supported": bf16_supported
                }
            }
            
            if model_id == "default-lightweight-model":
                recommendations.update({
                    "recommended_threads": min(cpu_count, 8),
                    "recommended_gpu_layers": 32 if gpu_available and gpu_memory_gb >= 4 else 0,
                    "recommended_context_length": 4096 if memory_gb >= 16 else 2048,
                    "recommended_batch_size": 1024 if memory_gb >= 16 else 512
                })
            elif model_id == "default-nlp-model":
                transformer_recommendations = self._get_transformer_recommendations(
                    memory_gb, gpu_available, gpu_memory_gb, gpu_count, bf16_supported
                )
                recommendations.update(transformer_recommendations)
            elif model_id == "default-classifier-model":
                recommendations.update({
                    "recommended_max_features": min(50000, int(memory_gb * 5000)),
                    "recommended_ngram_range": (1, 2) if memory_gb >= 8 else (1, 1)
                })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Failed to get hardware recommendations for {model_id}: {e}")
            return {"error": str(e)}
    
    def _get_transformer_recommendations(self, memory_gb: float, gpu_available: bool, 
                                       gpu_memory_gb: float, gpu_count: int, 
                                       bf16_supported: bool) -> Dict[str, Any]:
        """Get transformer-specific hardware recommendations."""
        recommendations = {}
        
        # Device recommendations
        if gpu_available:
            if gpu_count > 1:
                recommendations["recommended_device"] = "auto"
                recommendations["recommended_device_map"] = "auto"
                recommendations["recommended_multi_gpu_strategy"] = "model_parallel" if gpu_memory_gb < 8 else "data_parallel"
            else:
                recommendations["recommended_device"] = "cuda"
                recommendations["recommended_device_map"] = "auto"
        else:
            recommendations["recommended_device"] = "cpu"
            recommendations["recommended_device_map"] = None
        
        # Precision recommendations
        if gpu_available:
            if bf16_supported and gpu_memory_gb >= 8:
                recommendations["recommended_precision"] = "bf16"
            elif gpu_memory_gb >= 6:
                recommendations["recommended_precision"] = "fp16"
            elif gpu_memory_gb >= 4:
                recommendations["recommended_precision"] = "int8"
                recommendations["recommended_load_in_8bit"] = True
            else:
                recommendations["recommended_precision"] = "int4"
                recommendations["recommended_load_in_4bit"] = True
        else:
            recommendations["recommended_precision"] = "fp32"
        
        # Batch size recommendations
        batch_size = self._calculate_optimal_batch_size(memory_gb, gpu_available, gpu_memory_gb)
        recommendations["recommended_batch_size"] = batch_size
        recommendations["dynamic_batch_sizes"] = self._get_dynamic_batch_sizes(memory_gb, gpu_available, gpu_memory_gb)
        
        # Memory optimization recommendations
        if memory_gb < 16 or (gpu_available and gpu_memory_gb < 8):
            recommendations["recommended_low_cpu_mem_usage"] = True
            recommendations["recommended_gradient_checkpointing"] = True
            recommendations["recommended_cpu_offload"] = gpu_available and gpu_memory_gb < 6
        
        # Performance optimization recommendations
        if gpu_available:
            recommendations["recommended_mixed_precision"] = True
            recommendations["recommended_compile_model"] = gpu_memory_gb >= 8
            recommendations["recommended_use_flash_attention"] = gpu_memory_gb >= 8
            recommendations["recommended_attention_implementation"] = "flash_attention_2" if gpu_memory_gb >= 8 else "sdpa"
        
        # GPU memory management
        if gpu_available:
            if gpu_memory_gb <= 4:
                recommendations["recommended_gpu_memory_fraction"] = 0.8
            elif gpu_memory_gb <= 8:
                recommendations["recommended_gpu_memory_fraction"] = 0.85
            else:
                recommendations["recommended_gpu_memory_fraction"] = 0.9
        
        return recommendations
    
    def _calculate_optimal_batch_size(self, memory_gb: float, gpu_available: bool, gpu_memory_gb: float) -> int:
        """Calculate optimal batch size based on available memory."""
        if gpu_available:
            # GPU memory-based calculation
            if gpu_memory_gb >= 24:
                return 32
            elif gpu_memory_gb >= 16:
                return 16
            elif gpu_memory_gb >= 8:
                return 8
            elif gpu_memory_gb >= 4:
                return 4
            else:
                return 1
        else:
            # CPU memory-based calculation
            if memory_gb >= 32:
                return 8
            elif memory_gb >= 16:
                return 4
            elif memory_gb >= 8:
                return 2
            else:
                return 1
    
    def _get_dynamic_batch_sizes(self, memory_gb: float, gpu_available: bool, gpu_memory_gb: float) -> Dict[str, int]:
        """Get dynamic batch size recommendations for different scenarios."""
        base_batch = self._calculate_optimal_batch_size(memory_gb, gpu_available, gpu_memory_gb)
        
        return {
            "training": max(1, base_batch // 2),  # Training uses more memory
            "inference": base_batch,
            "evaluation": base_batch,
            "fine_tuning": max(1, base_batch // 4),  # Fine-tuning uses most memory
            "memory_constrained": 1,
            "performance_optimized": min(base_batch * 2, 32) if gpu_available else base_batch
        }
    
    def get_multi_gpu_configuration(self, model_id: str) -> Dict[str, Any]:
        """Get multi-GPU configuration recommendations."""
        try:
            import torch
            if not torch.cuda.is_available():
                return {"error": "CUDA not available"}
            
            gpu_count = torch.cuda.device_count()
            if gpu_count < 2:
                return {"error": "Multi-GPU requires at least 2 GPUs"}
            
            gpu_info = []
            total_memory = 0
            
            for i in range(gpu_count):
                props = torch.cuda.get_device_properties(i)
                memory_gb = props.total_memory / (1024**3)
                gpu_info.append({
                    "device_id": i,
                    "name": props.name,
                    "memory_gb": memory_gb,
                    "compute_capability": f"{props.major}.{props.minor}"
                })
                total_memory += memory_gb
            
            # Determine optimal strategy
            min_memory = min(gpu["memory_gb"] for gpu in gpu_info)
            max_memory = max(gpu["memory_gb"] for gpu in gpu_info)
            
            if max_memory / min_memory > 2:
                strategy = "sequential"  # Unbalanced GPUs
            elif total_memory >= 32:
                strategy = "model_parallel"  # Enough memory for model parallelism
            else:
                strategy = "data_parallel"  # Default to data parallelism
            
            return {
                "gpu_count": gpu_count,
                "gpu_info": gpu_info,
                "total_memory_gb": total_memory,
                "recommended_strategy": strategy,
                "device_map": self._generate_device_map(gpu_info, strategy),
                "load_balancing": self._calculate_load_balancing(gpu_info)
            }
            
        except ImportError:
            return {"error": "PyTorch not available"}
        except Exception as e:
            return {"error": str(e)}
    
    def _generate_device_map(self, gpu_info: List[Dict], strategy: str) -> Dict[str, Any]:
        """Generate device map for multi-GPU setup."""
        if strategy == "sequential":
            # Place layers sequentially across GPUs
            return {
                "strategy": "sequential",
                "device_assignment": {f"cuda:{i}": f"layers_{i*10}-{(i+1)*10-1}" for i in range(len(gpu_info))}
            }
        elif strategy == "model_parallel":
            # Distribute model layers based on GPU memory
            total_memory = sum(gpu["memory_gb"] for gpu in gpu_info)
            assignments = {}
            for i, gpu in enumerate(gpu_info):
                memory_fraction = gpu["memory_gb"] / total_memory
                assignments[f"cuda:{i}"] = f"{memory_fraction:.2f} of model"
            return {
                "strategy": "model_parallel",
                "device_assignment": assignments
            }
        else:  # data_parallel
            return {
                "strategy": "data_parallel",
                "device_assignment": {f"cuda:{i}": "full_model_replica" for i in range(len(gpu_info))}
            }
    
    def _calculate_load_balancing(self, gpu_info: List[Dict]) -> Dict[str, Any]:
        """Calculate load balancing recommendations."""
        total_memory = sum(gpu["memory_gb"] for gpu in gpu_info)
        
        balancing = {}
        for i, gpu in enumerate(gpu_info):
            memory_fraction = gpu["memory_gb"] / total_memory
            balancing[f"cuda:{i}"] = {
                "memory_fraction": memory_fraction,
                "recommended_batch_fraction": memory_fraction,
                "priority": "high" if memory_fraction > 0.3 else "medium" if memory_fraction > 0.2 else "low"
            }
        
        return balancing
    
    def get_performance_metrics(self, model_id: str) -> Dict[str, Any]:
        """Get performance metrics for a model."""
        # This would be implemented to collect actual performance metrics
        # For now, return mock data
        return {
            "model_id": model_id,
            "last_inference_time": 0.15,
            "average_inference_time": 0.18,
            "memory_usage_mb": 512,
            "gpu_utilization": 0.0,
            "throughput_tokens_per_second": 45.2,
            "last_updated": time.time()
        }

# Global instance
_system_model_manager = None

def get_system_model_manager() -> SystemModelManager:
    """Get the global system model manager instance."""
    global _system_model_manager
    if _system_model_manager is None:
        _system_model_manager = SystemModelManager()
    return _system_model_manager

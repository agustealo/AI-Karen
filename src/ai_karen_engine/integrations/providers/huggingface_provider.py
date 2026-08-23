"""
HuggingFace LLM Provider Implementation

Supports both Inference API and local model execution for HuggingFace models.
"""

import logging
import time
import os
from typing import Any, Dict, List, Optional, Union

from ai_karen_engine.integrations.llm_utils import LLMProviderBase, GenerationFailed, EmbeddingFailed, record_llm_metric

logger = logging.getLogger("kari.huggingface_provider")


class HuggingFaceProvider(LLMProviderBase):
    """HuggingFace provider supporting both Inference API and local execution."""
    
    def __init__(
        self,
        model: str = "microsoft/DialoGPT-large",
        api_token: Optional[str] = None,
        use_local: bool = False,
        inference_endpoint: str = "https://api-inference.huggingface.co/models"
    ):
        """
        Initialize HuggingFace provider.
        
        Args:
            model: Model name/path (e.g., "microsoft/DialoGPT-large")
            api_token: HuggingFace API token (from env HUGGINGFACE_API_TOKEN if not provided)
            use_local: Whether to use local model execution instead of API
            inference_endpoint: Base URL for HuggingFace Inference API
        """
        self.model = model
        self.api_token = api_token or os.getenv("HUGGINGFACE_API_TOKEN")
        self.use_local = use_local
        self.inference_endpoint = inference_endpoint
        self._local_pipeline = None
        
        if self.use_local:
            self._initialize_local_model()
        elif not self.api_token:
            logger.warning("No HuggingFace API token provided. Set HUGGINGFACE_API_TOKEN environment variable.")
    
    def _initialize_local_model(self):
        """Initialize local transformers pipeline."""
        try:
            from transformers import pipeline
            logger.info(f"Loading local HuggingFace model: {self.model}")
            
            # Determine task based on model name
            task = self._get_task_for_model(self.model)
            
            self._local_pipeline = pipeline(
                task=task,
                model=self.model,
                tokenizer=self.model,
                device_map="auto" if self._has_gpu() else None
            )
            logger.info(f"Successfully loaded local model: {self.model}")
            
        except ImportError:
            raise GenerationFailed(
                "transformers library not installed. Install with: pip install transformers torch"
            )
        except Exception as ex:
            raise GenerationFailed(f"Failed to load local HuggingFace model {self.model}: {ex}")
    
    def _get_task_for_model(self, model_name: str) -> str:
        """Determine the appropriate task based on model name."""
        model_lower = model_name.lower()
        
        if "dialog" in model_lower or "chat" in model_lower:
            return "text-generation"
        elif "t5" in model_lower or "flan" in model_lower:
            return "text2text-generation"
        elif "code" in model_lower:
            return "text-generation"
        else:
            return "text-generation"  # Default fallback
    
    def _has_gpu(self) -> bool:
        """Check if GPU is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
    
    def generate_text(self, prompt: str, **kwargs) -> str:
        """Generate text using HuggingFace model."""
        t0 = time.time()
        
        try:
            if self.use_local:
                return self._generate_local(prompt, **kwargs)
            else:
                return self._generate_api(prompt, **kwargs)
                
        except Exception as ex:
            record_llm_metric(
                "generate_text", time.time() - t0, False, "huggingface", error=str(ex)
            )
            raise GenerationFailed(f"HuggingFace generation failed: {ex}")
    
    def _generate_local(self, prompt: str, **kwargs) -> str:
        """Generate text using local transformers pipeline."""
        if not self._local_pipeline:
            raise GenerationFailed("Local pipeline not initialized")
        
        # Extract generation parameters
        max_length = kwargs.get("max_tokens", kwargs.get("max_length", 100))
        temperature = kwargs.get("temperature", 0.7)
        do_sample = temperature > 0
        
        try:
            # Generate text
            result = self._local_pipeline(
                prompt,
                max_length=max_length,
                temperature=temperature,
                do_sample=do_sample,
                pad_token_id=self._local_pipeline.tokenizer.eos_token_id,
                **{k: v for k, v in kwargs.items() if k not in ["max_tokens", "temperature"]}
            )
            
            # Extract generated text
            if isinstance(result, list) and len(result) > 0:
                generated = result[0].get("generated_text", "")
                # Remove the original prompt from the response
                if generated.startswith(prompt):
                    generated = generated[len(prompt):].strip()
                return generated
            
            return ""
            
        except Exception as ex:
            raise GenerationFailed(f"Local generation failed: {ex}")
    
    def _generate_api(self, prompt: str, **kwargs) -> str:
        """Generate text using HuggingFace Inference API."""
        if not self.api_token:
            raise GenerationFailed("HuggingFace API token required for API usage")
        
        try:
            import requests
        except ImportError:
            raise GenerationFailed("requests library required for API usage")
        
        # Prepare request
        url = f"{self.inference_endpoint}/{self.model}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
        # Prepare payload
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": kwargs.get("max_tokens", 100),
                "temperature": kwargs.get("temperature", 0.7),
                "do_sample": kwargs.get("temperature", 0.7) > 0,
                **{k: v for k, v in kwargs.items() if k not in ["max_tokens", "temperature"]}
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            # Handle different response formats
            if isinstance(result, list) and len(result) > 0:
                if "generated_text" in result[0]:
                    generated = result[0]["generated_text"]
                    # Remove original prompt if present
                    if generated.startswith(prompt):
                        generated = generated[len(prompt):].strip()
                    return generated
                elif "text" in result[0]:
                    return result[0]["text"]
            
            # Handle error responses
            if isinstance(result, dict) and "error" in result:
                raise GenerationFailed(f"API error: {result['error']}")
            
            return str(result) if result else ""
            
        except requests.exceptions.RequestException as ex:
            raise GenerationFailed(f"API request failed: {ex}")
        except Exception as ex:
            raise GenerationFailed(f"API response parsing failed: {ex}")
    
    def embed(self, text: Union[str, List[str]], **kwargs) -> List[float]:
        """Generate embeddings using HuggingFace models."""
        t0 = time.time()
        
        try:
            if self.use_local:
                return self._embed_local(text, **kwargs)
            else:
                return self._embed_api(text, **kwargs)
                
        except Exception as ex:
            record_llm_metric(
                "embed", time.time() - t0, False, "huggingface", error=str(ex)
            )
            raise EmbeddingFailed(f"HuggingFace embedding failed: {ex}")
    
    def _embed_local(self, text: Union[str, List[str]], **kwargs) -> List[float]:
        """Generate embeddings using local sentence-transformers."""
        try:
            from sentence_transformers import SentenceTransformer
            
            # Use a default embedding model if current model isn't suitable
            embedding_model = kwargs.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
            
            model = SentenceTransformer(embedding_model)
            
            if isinstance(text, str):
                embeddings = model.encode([text])
                return embeddings[0].tolist()
            else:
                embeddings = model.encode(text)
                return embeddings.tolist()
                
        except ImportError:
            raise EmbeddingFailed(
                "sentence-transformers library required for local embeddings. "
                "Install with: pip install sentence-transformers"
            )
        except Exception as ex:
            raise EmbeddingFailed(f"Local embedding failed: {ex}")
    
    def _embed_api(self, text: Union[str, List[str]], **kwargs) -> List[float]:
        """Generate embeddings using HuggingFace Inference API."""
        if not self.api_token:
            raise EmbeddingFailed("HuggingFace API token required for API usage")
        
        try:
            import requests
        except ImportError:
            raise EmbeddingFailed("requests library required for API usage")
        
        # Use a suitable embedding model
        embedding_model = kwargs.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
        url = f"{self.inference_endpoint}/{embedding_model}"
        
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
        # Handle single string or list
        inputs = [text] if isinstance(text, str) else text
        
        payload = {"inputs": inputs}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            # Return first embedding if single string input
            if isinstance(text, str) and isinstance(result, list) and len(result) > 0:
                return result[0]
            
            return result if isinstance(result, list) else []
            
        except requests.exceptions.RequestException as ex:
            raise EmbeddingFailed(f"Embedding API request failed: {ex}")
        except Exception as ex:
            raise EmbeddingFailed(f"Embedding API response parsing failed: {ex}")
    
    def get_models(self) -> List[str]:
        """Get list of available models."""
        # Popular HuggingFace models for conversation
        return [
            "microsoft/DialoGPT-large",
            "microsoft/DialoGPT-medium",
            "facebook/blenderbot-400M-distill",
            "facebook/blenderbot-1B-distill",
            "google/flan-t5-base",
            "google/flan-t5-large",
            "Salesforce/codet5-base",
            "Salesforce/codet5-large",
            "EleutherAI/gpt-neo-1.3B",
            "EleutherAI/gpt-neo-2.7B"
        ]
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get provider metadata."""
        return {
            "name": "huggingface",
            "model": self.model,
            "use_local": self.use_local,
            "has_api_token": bool(self.api_token),
            "inference_endpoint": self.inference_endpoint,
            "supports_streaming": False,  # Can be implemented later
            "supports_embeddings": True
        }

    def health_check(self) -> Dict[str, Any]:
        """Perform health check on HuggingFace provider with model availability information."""
        try:
            if self.use_local:
                # Check local model availability
                if self._local_pipeline is None:
                    return {
                        "status": "unhealthy",
                        "error": "Local model not initialized"
                    }
                
                # Test local pipeline
                start_time = time.time()
                try:
                    test_result = self._local_pipeline("Hello", max_length=5)
                    response_time = time.time() - start_time
                    
                    health_result = {
                        "status": "healthy",
                        "response_time": response_time,
                        "model_tested": self.model,
                        "execution_mode": "local"
                    }
                except Exception as e:
                    return {
                        "status": "unhealthy",
                        "error": f"Local model test failed: {str(e)}"
                    }
            else:
                # Check API availability
                if not self.api_token:
                    return {
                        "status": "unhealthy",
                        "error": "No API token provided"
                    }
                
                # Test API call
                start_time = time.time()
                try:
                    test_result = self.generate_text("Hello", max_tokens=1)
                    response_time = time.time() - start_time
                    
                    health_result = {
                        "status": "healthy",
                        "response_time": response_time,
                        "model_tested": self.model,
                        "execution_mode": "api"
                    }
                except Exception as e:
                    return {
                        "status": "unhealthy",
                        "error": f"API test failed: {str(e)}"
                    }

            # Add Model Library compatibility check
            try:
                from ai_karen_engine.core.model_runtime.compatibility.provider_model_compatibility import ProviderModelCompatibilityService
                compatibility_service = ProviderModelCompatibilityService()
                validation = compatibility_service.validate_provider_model_setup("huggingface")
                
                health_result["model_library"] = {
                    "available": True,
                    "compatible_models_count": validation.get("total_compatible", 0),
                    "validation_status": validation.get("status", "unknown")
                }
                
                # Add recommendations if no compatible models
                if validation.get("total_compatible", 0) == 0:
                    health_result["warnings"] = health_result.get("warnings", [])
                    health_result["warnings"].append("No compatible models found in Model Library")
                
            except Exception as e:
                health_result["model_library"] = {
                    "available": False,
                    "error": str(e)
                }
                health_result["warnings"] = health_result.get("warnings", [])
                health_result["warnings"].append(f"Model Library unavailable: {e}")

            return health_result
            
        except Exception as ex:
            return {
                "status": "unhealthy",
                "error": str(ex),
                "model_library": {
                    "available": False,
                    "error": "Provider health check failed"
                }
            }

    # Lightweight status helpers -------------------------------------------------

    def ping(self) -> bool:
        try:
            result = self.health_check()
            return result.get("status") == "healthy"
        except Exception:
            return False

    def available_models(self) -> list[str]:
        if self.use_local:
            return [self.model]
        try:
            return self.get_models()
        except Exception:
            return [self.model]


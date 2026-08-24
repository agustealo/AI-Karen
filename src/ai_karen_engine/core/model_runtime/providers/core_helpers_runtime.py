"""
Core Helpers Runtime Implementation

This module provides the CoreHelpersRuntime class for degraded mode operation
using lightweight models like the default model, DistilBERT, and spaCy for basic functionality.
"""

import logging
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Union

logger = logging.getLogger(__name__)

# Try to import core helper libraries
try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    logger.debug("spacy not available")
    SPACY_AVAILABLE = False
    spacy = None

try:
    from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    logger.debug("transformers not available")
    TRANSFORMERS_AVAILABLE = False
    pipeline = None
    AutoTokenizer = None
    AutoModelForCausalLM = None

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    logger.debug("sentence-transformers not available")
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None


class CoreHelpersRuntime:
    """
    Runtime for degraded mode operation using lightweight core helper models.
    
    This runtime provides basic functionality when primary models are unavailable,
    using a combination of lightweight models for different tasks:
    - Default model for basic text generation
    - DistilBERT for embeddings and classification
    - spaCy for NLP tasks (tokenization, NER, etc.)
    
    Key Features:
    - Minimal resource requirements
    - Fast startup time
    - Basic text generation capabilities
    - NLP processing with spaCy
    - Lightweight embeddings
    - Graceful degradation messaging
    """
    
    def __init__(
        self,
        text_model: str = "default-text-model",  # Fallback; overridden by config
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        spacy_model: str = "en_core_web_sm",
        device: str = "cpu",
        max_memory_mb: int = 2048,
        **kwargs
    ):
        """
        Initialize Core Helpers runtime.
        
        Args:
            text_model: Lightweight text generation model
            embedding_model: Lightweight embedding model
            spacy_model: spaCy model for NLP tasks
            device: Device to use (cpu only for degraded mode)
            max_memory_mb: Maximum memory usage in MB
            **kwargs: Additional parameters
        """
        self.text_model_name = text_model
        self.embedding_model_name = embedding_model
        self.spacy_model_name = spacy_model
        self.device = "cpu"  # Force CPU for degraded mode
        self.max_memory_mb = max_memory_mb
        self.kwargs = kwargs
        
        self._text_pipeline = None
        self._embedding_model = None
        self._spacy_nlp = None
        self._tokenizer = None
        self._lock = threading.RLock()
        self._loaded = False
        self._load_time: Optional[float] = None
        self._memory_usage: Optional[int] = None
        
        # Auto-load core helpers
        self._load_core_helpers()
    
    def _load_core_helpers(self) -> None:
        """Load core helper models."""
        with self._lock:
            try:
                start_time = time.time()
                logger.info("Loading core helper models for degraded mode...")
                
                # Load text generation pipeline
                if TRANSFORMERS_AVAILABLE:
                    try:
                        logger.info(f"Loading text model: {self.text_model_name}")
                        self._text_pipeline = pipeline(
                            "text-generation",
                            model=self.text_model_name,
                            device=-1,  # CPU
                            torch_dtype="float32",
                            model_kwargs={"low_cpu_mem_usage": True}
                        )
                        self._tokenizer = self._text_pipeline.tokenizer
                        logger.info("Text generation model loaded")
                    except Exception as e:
                        logger.warning(f"Failed to load text model: {e}")
                
                # Load embedding model
                if SENTENCE_TRANSFORMERS_AVAILABLE:
                    try:
                        logger.info(f"Loading embedding model: {self.embedding_model_name}")
                        self._embedding_model = SentenceTransformer(
                            self.embedding_model_name,
                            device="cpu"
                        )
                        logger.info("Embedding model loaded")
                    except Exception as e:
                        logger.warning(f"Failed to load embedding model: {e}")
                
                # Load spaCy model
                if SPACY_AVAILABLE:
                    try:
                        logger.info(f"Loading spaCy model: {self.spacy_model_name}")
                        self._spacy_nlp = spacy.load(self.spacy_model_name)
                        logger.info("spaCy model loaded")
                    except Exception as e:
                        logger.warning(f"Failed to load spaCy model: {e}")
                        # Try to download the model
                        try:
                            spacy.cli.download(self.spacy_model_name)
                            self._spacy_nlp = spacy.load(self.spacy_model_name)
                            logger.info("spaCy model downloaded and loaded")
                        except Exception as e2:
                            logger.warning(f"Failed to download spaCy model: {e2}")
                
                self._loaded = True
                self._load_time = time.time() - start_time
                self._memory_usage = self.max_memory_mb * 1024 * 1024  # Rough estimate
                
                logger.info(f"Core helpers loaded in {self._load_time:.2f}s")
                
            except Exception as e:
                logger.error(f"Failed to load core helpers: {e}")
                self._loaded = False
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 128,  # Reduced for degraded mode
        temperature: float = 0.7,
        top_p: float = 0.9,
        stop: Optional[List[str]] = None,
        stream: bool = False,
        **kwargs
    ) -> Union[str, Iterator[str]]:
        """
        Generate text using lightweight model.
        
        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate (limited in degraded mode)
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            stop: Stop sequences
            stream: Whether to stream tokens
            **kwargs: Additional parameters
            
        Returns:
            Generated text or token iterator
        """
        if not self._text_pipeline:
            return self._fallback_response(prompt)
        
        try:
            # Limit max tokens for degraded mode
            max_tokens = min(max_tokens, 128)
            
            generation_params = {
                "max_new_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "do_sample": temperature > 0,
                "return_full_text": False,
                "pad_token_id": self._tokenizer.eos_token_id,
                **kwargs
            }
            
            if stream:
                return self._stream_generate(prompt, **generation_params)
            else:
                return self._complete_generate(prompt, **generation_params)
                
        except Exception as e:
            logger.error(f"Generation failed in degraded mode: {e}")
            return self._fallback_response(prompt)

    def generate_response(self, prompt: str, **kwargs) -> str:
        """Compatibility alias for runtime managers."""
        result = self.generate(prompt, **kwargs)
        if isinstance(result, str):
            return result
        return self._fallback_response(prompt)

    def stream_generate(self, prompt: str, **kwargs) -> Iterator[str]:
        """Compatibility alias for runtime managers."""
        result = self.generate(prompt, stream=True, **kwargs)
        if hasattr(result, "__iter__"):
            yield from result
            return
        yield self._fallback_response(prompt)
    
    def _complete_generate(self, prompt: str, **params) -> str:
        """Generate complete response."""
        try:
            result = self._text_pipeline(prompt, **params)
            
            if isinstance(result, list) and len(result) > 0:
                generated = result[0].get("generated_text", "")
                # Add degraded mode notice
                return f"{generated}\n\n[Generated in degraded mode - limited functionality]"
            else:
                return self._fallback_response(prompt)
        except Exception as e:
            logger.error(f"Text generation failed: {e}")
            return self._fallback_response(prompt)
    
    def _stream_generate(self, prompt: str, **params) -> Iterator[str]:
        """Generate streaming response (simulated)."""
        try:
            # Generate full response first (no true streaming in degraded mode)
            full_response = self._complete_generate(prompt, **params)
            
            # Simulate streaming by yielding words
            words = full_response.split()
            for i, word in enumerate(words):
                if i == 0:
                    yield word
                else:
                    yield " " + word
                time.sleep(0.05)  # Small delay to simulate streaming
                
        except Exception as e:
            logger.error(f"Streaming generation failed: {e}")
            yield self._fallback_response(prompt)
    
    def _fallback_response(self, prompt: str) -> str:
        """Generate a fallback response when models fail."""
        # Simple rule-based responses for common prompts
        prompt_lower = prompt.lower()
        
        if any(word in prompt_lower for word in ["hello", "hi", "hey"]):
            return "Hello! I'm running in degraded mode with limited capabilities. How can I help you?"
        
        elif any(word in prompt_lower for word in ["help", "what", "how"]):
            return "I'm currently running in degraded mode. My capabilities are limited, but I'll try to help with basic tasks."
        
        elif any(word in prompt_lower for word in ["code", "program", "function"]):
            return "I'm in degraded mode and have limited coding assistance. For complex programming tasks, please try again when full models are available."
        
        elif any(word in prompt_lower for word in ["explain", "tell me", "describe"]):
            return "I'm operating in degraded mode with basic functionality. I can provide simple responses but complex explanations may not be available."
        
        else:
            return "I'm currently in degraded mode with limited capabilities. Please try again later when full models are available."
    
    def embed(self, text: str) -> List[float]:
        """
        Generate embeddings using lightweight model.
        
        Args:
            text: Input text
            
        Returns:
            Embedding vector
        """
        if not self._embedding_model:
            # Fallback to simple hash-based embedding
            return self._hash_embedding(text)
        
        try:
            embedding = self._embedding_model.encode(text)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return self._hash_embedding(text)
    
    def _hash_embedding(self, text: str, dim: int = 384) -> List[float]:
        """Generate a simple hash-based embedding as fallback."""
        import hashlib
        import struct
        
        # Create hash of text
        hash_obj = hashlib.md5(text.encode())
        hash_bytes = hash_obj.digest()
        
        # Convert to float vector
        embedding = []
        for i in range(0, len(hash_bytes), 4):
            chunk = hash_bytes[i:i+4]
            if len(chunk) == 4:
                value = struct.unpack('f', chunk)[0]
                embedding.append(value)
        
        # Pad or truncate to desired dimension
        while len(embedding) < dim:
            embedding.extend(embedding[:min(len(embedding), dim - len(embedding))])
        
        return embedding[:dim]
    
    def tokenize(self, text: str) -> List[int]:
        """
        Tokenize text using available tokenizer or spaCy.
        
        Args:
            text: Input text
            
        Returns:
            List of token IDs or word tokens
        """
        if self._tokenizer:
            try:
                return self._tokenizer.encode(text)
            except Exception as e:
                logger.error(f"Tokenization failed: {e}")
        
        # Fallback to spaCy tokenization
        if self._spacy_nlp:
            try:
                doc = self._spacy_nlp(text)
                return [token.text for token in doc]  # Return text tokens instead of IDs
            except Exception as e:
                logger.error(f"spaCy tokenization failed: {e}")
        
        # Ultimate fallback - simple word splitting
        return text.split()
    
    def detokenize(self, tokens: Union[List[int], List[str]]) -> str:
        """
        Detokenize tokens to text.
        
        Args:
            tokens: List of token IDs or text tokens
            
        Returns:
            Decoded text
        """
        if self._tokenizer and all(isinstance(t, int) for t in tokens):
            try:
                return self._tokenizer.decode(tokens, skip_special_tokens=True)
            except Exception as e:
                logger.error(f"Detokenization failed: {e}")
        
        # Fallback - join text tokens
        if all(isinstance(t, str) for t in tokens):
            return " ".join(tokens)
        
        # Convert to strings and join
        return " ".join(str(t) for t in tokens)
    
    def analyze_text(self, text: str) -> Dict[str, Any]:
        """
        Analyze text using spaCy for NLP tasks.
        
        Args:
            text: Input text
            
        Returns:
            Analysis results
        """
        if not self._spacy_nlp:
            return {"error": "spaCy not available"}
        
        try:
            doc = self._spacy_nlp(text)
            
            analysis = {
                "tokens": [{"text": token.text, "pos": token.pos_, "lemma": token.lemma_} for token in doc],
                "entities": [{"text": ent.text, "label": ent.label_, "start": ent.start_char, "end": ent.end_char} for ent in doc.ents],
                "sentences": [sent.text for sent in doc.sents],
                "language": doc.lang_,
            }
            
            return analysis
            
        except Exception as e:
            logger.error(f"Text analysis failed: {e}")
            return {"error": str(e)}
    
    def is_loaded(self) -> bool:
        """Check if core helpers are loaded."""
        return self._loaded
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about loaded models."""
        return {
            "runtime": "core_helpers",
            "loaded": self._loaded,
            "load_time": self._load_time,
            "memory_usage": self._memory_usage,
            "text_model": self.text_model_name,
            "embedding_model": self.embedding_model_name,
            "spacy_model": self.spacy_model_name,
            "device": self.device,
            "degraded_mode": True,
            "components": {
                "text_generation": self._text_pipeline is not None,
                "embeddings": self._embedding_model is not None,
                "nlp_analysis": self._spacy_nlp is not None,
            }
        }
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on core helpers.
        
        Returns:
            Health status information
        """
        try:
            start_time = time.time()
            
            # Check component availability
            components_status = {
                "transformers": TRANSFORMERS_AVAILABLE,
                "sentence_transformers": SENTENCE_TRANSFORMERS_AVAILABLE,
                "spacy": SPACY_AVAILABLE,
            }
            
            # Check loaded models
            models_status = {
                "text_generation": self._text_pipeline is not None,
                "embeddings": self._embedding_model is not None,
                "nlp_analysis": self._spacy_nlp is not None,
            }
            
            # Test basic functionality
            try:
                # Test tokenization
                tokens = self.tokenize("Hello world")
                if not tokens:
                    raise RuntimeError("Tokenization test failed")
                
                # Test text analysis if available
                if self._spacy_nlp:
                    analysis = self.analyze_text("Hello world")
                    if "error" in analysis:
                        raise RuntimeError("Text analysis test failed")
                
                capabilities = {
                    "text_generation": self._text_pipeline is not None,
                    "embeddings": self._embedding_model is not None,
                    "tokenization": True,
                    "text_analysis": self._spacy_nlp is not None,
                    "degraded_mode": True,
                    "streaming": True,  # Simulated streaming
                }
                
                return {
                    "status": "healthy",
                    "message": "Core helpers operational (degraded mode)",
                    "response_time": time.time() - start_time,
                    "components": components_status,
                    "models": models_status,
                    "capabilities": capabilities,
                    "degraded_mode": True
                }
                
            except Exception as e:
                return {
                    "status": "degraded",
                    "error": f"Functionality test failed: {e}",
                    "response_time": time.time() - start_time,
                    "components": components_status,
                    "models": models_status,
                    "degraded_mode": True
                }
                
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "response_time": time.time() - start_time if 'start_time' in locals() else None,
                "degraded_mode": True
            }
    
    def get_resource_usage(self) -> Dict[str, Any]:
        """Get current resource usage statistics."""
        return {
            "memory_usage": self._memory_usage,
            "models_loaded": self.is_loaded(),
            "device": self.device,
            "max_memory_mb": self.max_memory_mb,
            "degraded_mode": True,
        }
    
    def shutdown(self) -> None:
        """Shutdown core helpers and cleanup resources."""
        logger.info("Shutting down core helpers runtime")
        
        with self._lock:
            if self._text_pipeline:
                del self._text_pipeline
                self._text_pipeline = None
            
            if self._embedding_model:
                del self._embedding_model
                self._embedding_model = None
            
            if self._spacy_nlp:
                del self._spacy_nlp
                self._spacy_nlp = None
            
            if self._tokenizer:
                del self._tokenizer
                self._tokenizer = None
            
            self._loaded = False
    
    @staticmethod
    def is_available() -> bool:
        """Check if core helpers runtime is available."""
        # At least one component should be available
        return TRANSFORMERS_AVAILABLE or SENTENCE_TRANSFORMERS_AVAILABLE or SPACY_AVAILABLE
    
    @staticmethod
    def supports_format(format_name: str) -> bool:
        """Check if runtime supports a specific model format."""
        # Core helpers support basic formats
        supported_formats = ["gguf", "safetensors"]
        return format_name.lower() in supported_formats
    
    @staticmethod
    def supports_family(family_name: str) -> bool:
        """Check if runtime supports a specific model family."""
        # Core helpers support lightweight models
        supported_families = ["small_llm", "distilbert", "minilm"]
        return family_name.lower() in supported_families
    
    @staticmethod
    def get_requirements() -> Dict[str, Any]:
        """Get runtime requirements."""
        return {
            "requires_gpu": False,
            "min_memory": "1GB",
            "recommended_memory": "2GB",
            "cpu_only": True,
            "degraded_mode": True
        }


__all__ = ["CoreHelpersRuntime"]

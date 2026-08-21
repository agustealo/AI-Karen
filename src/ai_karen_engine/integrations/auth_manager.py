"""
Authentication and API Key Management System

Handles secure API key validation, rotation, and authentication error recovery.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import hashlib
import json

logger = logging.getLogger("kari.auth_manager")


@dataclass
class ApiKeyInfo:
    """Information about an API key."""
    provider: str
    key_hash: str  # Hashed version for logging
    is_valid: bool
    last_validated: Optional[datetime] = None
    validation_error: Optional[str] = None
    usage_count: int = 0
    rate_limit_remaining: Optional[int] = None
    rate_limit_reset: Optional[datetime] = None


@dataclass
class ValidationResult:
    """Result of API key validation."""
    is_valid: bool
    error_message: Optional[str] = None
    provider_info: Dict[str, Any] = field(default_factory=dict)
    rate_limit_info: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)


class AuthenticationManager:
    """Manages API keys and authentication for LLM providers."""

    def __init__(self):
        """Initialize authentication manager."""
        self.api_keys: Dict[str, ApiKeyInfo] = {}
        self.validation_cache: Dict[str, ValidationResult] = {}
        self.cache_ttl = timedelta(minutes=30)  # Cache validation results for 30 minutes

    def _hash_key(self, api_key: str) -> str:
        """Create a hash of the API key for safe logging."""
        if not api_key:
            return "none"
        # Show first 4 and last 4 characters with hash in between
        if len(api_key) > 8:
            prefix = api_key[:4]
            suffix = api_key[-4:]
            middle_hash = hashlib.md5(api_key[4:-4].encode()).hexdigest()[:8]
            return f"{prefix}...{middle_hash}...{suffix}"
        else:
            return f"key_{hashlib.md5(api_key.encode()).hexdigest()[:8]}"

    def register_api_key(self, provider: str, api_key: Optional[str] = None) -> bool:
        """
        Register an API key for a provider.
        
        Args:
            provider: Provider name (e.g., 'openai', 'anthropic')
            api_key: API key (will try environment variable if None)
            
        Returns:
            True if key was registered successfully
        """
        if not api_key:
            # Try to get from environment
            env_var_name = f"{provider.upper()}_API_KEY"
            api_key = os.getenv(env_var_name)
            
            if not api_key:
                logger.warning(f"No API key found for {provider} (tried {env_var_name})")
                return False

        key_info = ApiKeyInfo(
            provider=provider,
            key_hash=self._hash_key(api_key),
            is_valid=False  # Will be validated separately
        )
        
        self.api_keys[provider] = key_info
        logger.info(f"Registered API key for {provider}: {key_info.key_hash}")
        return True

    def get_api_key(self, provider: str) -> Optional[str]:
        """
        Get the actual API key for a provider.
        
        Args:
            provider: Provider name
            
        Returns:
            API key string or None if not found
        """
        # Always try environment first for security
        env_var_name = f"{provider.upper()}_API_KEY"
        api_key = os.getenv(env_var_name)
        
        if api_key:
            return api_key
            
        logger.warning(f"No API key found for {provider} in environment variable {env_var_name}")
        return None

    def validate_api_key(self, provider: str, force_refresh: bool = False) -> ValidationResult:
        """
        Validate an API key for a provider.
        
        Args:
            provider: Provider name
            force_refresh: Skip cache and force fresh validation
            
        Returns:
            ValidationResult with validation status and details
        """
        # Check cache first (unless force refresh)
        cache_key = f"{provider}_validation"
        if not force_refresh and cache_key in self.validation_cache:
            cached_result = self.validation_cache[cache_key]
            if datetime.now() - cached_result.provider_info.get('validated_at', datetime.min) < self.cache_ttl:
                return cached_result

        api_key = self.get_api_key(provider)
        if not api_key:
            result = ValidationResult(
                is_valid=False,
                error_message=f"No API key found for {provider}"
            )
            self.validation_cache[cache_key] = result
            return result

        # Perform provider-specific validation
        try:
            result = self._validate_provider_key(provider, api_key)
            result.provider_info['validated_at'] = datetime.now()
            
            # Update key info
            if provider in self.api_keys:
                self.api_keys[provider].is_valid = result.is_valid
                self.api_keys[provider].last_validated = datetime.now()
                self.api_keys[provider].validation_error = result.error_message
            
            # Cache result
            self.validation_cache[cache_key] = result
            
            if result.is_valid:
                logger.info(f"API key validation successful for {provider}")
            else:
                logger.warning(f"API key validation failed for {provider}: {result.error_message}")
                
            return result
            
        except Exception as ex:
            error_msg = f"API key validation error for {provider}: {ex}"
            logger.error(error_msg)
            
            result = ValidationResult(
                is_valid=False,
                error_message=error_msg
            )
            self.validation_cache[cache_key] = result
            return result

    def _validate_provider_key(self, provider: str, api_key: str) -> ValidationResult:
        """Validate API key for specific provider."""
        provider_lower = provider.lower()
        
        if provider_lower == "openai":
            return self._validate_openai_key(api_key)
        elif provider_lower == "anthropic":
            return self._validate_anthropic_key(api_key)
        elif provider_lower == "google" or provider_lower == "gemini":
            return self._validate_google_key(api_key)
        elif provider_lower == "deepseek":
            return self._validate_deepseek_key(api_key)
        else:
            return ValidationResult(
                is_valid=False,
                error_message=f"Unknown provider: {provider}"
            )

    def _validate_openai_key(self, api_key: str) -> ValidationResult:
        """Validate OpenAI API key."""
        try:
            import openai
            
            client = openai.OpenAI(api_key=api_key, timeout=10.0)
            
            # Test with minimal request
            models = client.models.list()
            model_list = [model.id for model in models.data if "gpt" in model.id.lower()]
            
            return ValidationResult(
                is_valid=True,
                provider_info={
                    "available_models": len(model_list),
                    "sample_models": model_list[:3]
                },
                capabilities=["text_generation", "embeddings", "function_calling", "streaming"]
            )
            
        except ImportError:
            return ValidationResult(
                is_valid=False,
                error_message="OpenAI package not installed. Run: pip install openai"
            )
        except Exception as ex:
            error_str = str(ex).lower()
            if "api key" in error_str or "unauthorized" in error_str:
                return ValidationResult(
                    is_valid=False,
                    error_message="Invalid OpenAI API key"
                )
            elif "rate limit" in error_str:
                # Rate limit during validation doesn't mean invalid key
                return ValidationResult(
                    is_valid=True,
                    error_message="Rate limited during validation, but key appears valid",
                    capabilities=["text_generation", "embeddings", "function_calling", "streaming"]
                )
            else:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"OpenAI validation failed: {ex}"
                )

    def _validate_anthropic_key(self, api_key: str) -> ValidationResult:
        """Validate Anthropic API key."""
        try:
            import anthropic
            
            client = anthropic.Anthropic(api_key=api_key, timeout=10.0)
            
            # Test with minimal request
            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1,
                messages=[{"role": "user", "content": "Hi"}]
            )
            
            return ValidationResult(
                is_valid=True,
                provider_info={
                    "test_response_id": response.id if hasattr(response, 'id') else None
                },
                capabilities=["text_generation", "function_calling", "streaming"]
            )
            
        except ImportError:
            return ValidationResult(
                is_valid=False,
                error_message="Anthropic package not installed. Run: pip install anthropic"
            )
        except Exception as ex:
            error_str = str(ex).lower()
            if "api key" in error_str or "unauthorized" in error_str:
                return ValidationResult(
                    is_valid=False,
                    error_message="Invalid Anthropic API key"
                )
            else:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Anthropic validation failed: {ex}"
                )

    def _validate_google_key(self, api_key: str) -> ValidationResult:
        """Validate Google/Gemini API key."""
        try:
            import importlib

            genai = importlib.import_module("google.generativeai")
            configure = getattr(genai, "configure", None)
            if configure is None:
                raise AttributeError("google.generativeai.configure is unavailable")

            configure(api_key=api_key)
            
            # Test with model list
            models = list(genai.list_models())
            model_names = [model.name for model in models if "gemini" in model.name.lower()]
            
            return ValidationResult(
                is_valid=True,
                provider_info={
                    "available_models": len(model_names),
                    "sample_models": model_names[:3]
                },
                capabilities=["text_generation", "vision", "streaming"]
            )
            
        except ImportError:
            return ValidationResult(
                is_valid=False,
                error_message="Google AI package not installed. Run: pip install google-generativeai"
            )
        except Exception as ex:
            error_str = str(ex).lower()
            if "api key" in error_str or "invalid" in error_str:
                return ValidationResult(
                    is_valid=False,
                    error_message="Invalid Google AI API key"
                )
            else:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Google AI validation failed: {ex}"
                )

    def _validate_deepseek_key(self, api_key: str) -> ValidationResult:
        """Validate DeepSeek API key."""
        try:
            import requests
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            # Test with models endpoint
            response = requests.get(
                "https://api.deepseek.com/v1/models",
                headers=headers,
                timeout=10.0
            )
            
            if response.status_code == 200:
                models_data = response.json()
                model_list = [model["id"] for model in models_data.get("data", [])]
                
                return ValidationResult(
                    is_valid=True,
                    provider_info={
                        "available_models": len(model_list),
                        "sample_models": model_list[:3]
                    },
                    capabilities=["text_generation", "streaming"]
                )
            elif response.status_code == 401:
                return ValidationResult(
                    is_valid=False,
                    error_message="Invalid DeepSeek API key"
                )
            else:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"DeepSeek validation failed: HTTP {response.status_code}"
                )
                
        except ImportError:
            return ValidationResult(
                is_valid=False,
                error_message="Requests package required for DeepSeek validation"
            )
        except Exception as ex:
            return ValidationResult(
                is_valid=False,
                error_message=f"DeepSeek validation failed: {ex}"
            )

    def get_provider_status(self, provider: str) -> Dict[str, Any]:
        """
        Get comprehensive status for a provider's authentication.
        
        Args:
            provider: Provider name
            
        Returns:
            Dictionary with authentication status information
        """
        api_key = self.get_api_key(provider)
        key_info = self.api_keys.get(provider)
        
        status = {
            "provider": provider,
            "has_api_key": bool(api_key),
            "key_registered": provider in self.api_keys,
            "environment_variable": f"{provider.upper()}_API_KEY"
        }
        
        if key_info:
            status.update({
                "key_hash": key_info.key_hash,
                "is_valid": key_info.is_valid,
                "last_validated": key_info.last_validated.isoformat() if key_info.last_validated else None,
                "validation_error": key_info.validation_error,
                "usage_count": key_info.usage_count
            })
        
        # Check validation cache
        cache_key = f"{provider}_validation"
        if cache_key in self.validation_cache:
            cached_result = self.validation_cache[cache_key]
            status["cached_validation"] = {
                "is_valid": cached_result.is_valid,
                "capabilities": cached_result.capabilities,
                "provider_info": cached_result.provider_info
            }
        
        return status

    def get_all_provider_status(self) -> Dict[str, Dict[str, Any]]:
        """Get authentication status for all known providers."""
        # Common providers to check
        providers = ["openai", "anthropic", "google", "gemini", "deepseek"]
        
        # Add any registered providers
        providers.extend(self.api_keys.keys())
        
        # Remove duplicates
        providers = list(set(providers))
        
        return {provider: self.get_provider_status(provider) for provider in providers}

    def refresh_all_validations(self) -> Dict[str, ValidationResult]:
        """Refresh validation for all registered providers."""
        results = {}
        
        for provider in self.api_keys.keys():
            try:
                result = self.validate_api_key(provider, force_refresh=True)
                results[provider] = result
            except Exception as ex:
                logger.error(f"Failed to refresh validation for {provider}: {ex}")
                results[provider] = ValidationResult(
                    is_valid=False,
                    error_message=f"Validation refresh failed: {ex}"
                )
        
        return results

    def get_setup_instructions(self, provider: str) -> List[str]:
        """
        Get setup instructions for a provider's API key.
        
        Args:
            provider: Provider name
            
        Returns:
            List of setup instruction strings
        """
        provider_lower = provider.lower()
        env_var = f"{provider.upper()}_API_KEY"
        
        base_instructions = [
            f"1. Get an API key from {provider} dashboard",
            f"2. Set environment variable: export {env_var}=your_api_key_here",
            f"3. Restart the application to load the new key",
            f"4. Test the connection in provider settings"
        ]
        
        if provider_lower == "openai":
            return [
                "1. Visit https://platform.openai.com/api-keys",
                "2. Click 'Create new secret key'",
                "3. Copy the generated key",
                f"4. Set environment variable: export {env_var}=sk-your_key_here",
                "5. Restart the application"
            ]
        elif provider_lower == "anthropic":
            return [
                "1. Visit https://console.anthropic.com/",
                "2. Go to API Keys section",
                "3. Create a new API key",
                f"4. Set environment variable: export {env_var}=your_key_here",
                "5. Restart the application"
            ]
        elif provider_lower in ["google", "gemini"]:
            return [
                "1. Visit https://makersuite.google.com/app/apikey",
                "2. Create a new API key",
                "3. Copy the generated key",
                f"4. Set environment variable: export {env_var}=your_key_here",
                "5. Restart the application"
            ]
        elif provider_lower == "deepseek":
            return [
                "1. Visit https://platform.deepseek.com/api_keys",
                "2. Create a new API key",
                "3. Copy the generated key",
                f"4. Set environment variable: export {env_var}=your_key_here",
                "5. Restart the application"
            ]
        else:
            return base_instructions

    def clear_cache(self, provider: Optional[str] = None):
        """
        Clear validation cache.
        
        Args:
            provider: Specific provider to clear (all if None)
        """
        if provider:
            cache_key = f"{provider}_validation"
            if cache_key in self.validation_cache:
                del self.validation_cache[cache_key]
                logger.info(f"Cleared validation cache for {provider}")
        else:
            self.validation_cache.clear()
            logger.info("Cleared all validation cache")

    def record_usage(self, provider: str):
        """Record API key usage for statistics."""
        if provider in self.api_keys:
            self.api_keys[provider].usage_count += 1

    def update_rate_limit_info(self, provider: str, remaining: Optional[int], reset_time: Optional[datetime]):
        """Update rate limit information for a provider."""
        if provider in self.api_keys:
            self.api_keys[provider].rate_limit_remaining = remaining
            self.api_keys[provider].rate_limit_reset = reset_time

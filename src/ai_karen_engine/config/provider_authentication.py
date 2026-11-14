"""
Comprehensive Provider Authentication System

This module provides secure API key management and authentication for LLM providers with:
- Secure API key management for external providers
- Authentication validation on startup
- Provider-specific authentication handling
- Authentication error handling and user feedback
"""

import os
import json
import logging
import asyncio
import hashlib
import base64
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union, Callable
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
import threading

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    keyring = None

try:
    from cryptography.fernet import Fernet
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None

from ai_karen_engine.config.llm_provider_config import (
    get_provider_config_manager,
    ProviderConfig,
    AuthenticationType
)

logger = logging.getLogger(__name__)


class AuthenticationStatus(str, Enum):
    """Authentication status enumeration"""
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    RATE_LIMITED = "rate_limited"
    INSUFFICIENT_PERMISSIONS = "insufficient_permissions"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


class SecureStorageBackend(str, Enum):
    """Secure storage backend options"""
    KEYRING = "keyring"          # System keyring (preferred)
    ENCRYPTED_FILE = "encrypted_file"  # Encrypted file storage
    ENVIRONMENT = "environment"   # Environment variables only
    MEMORY = "memory"            # In-memory only (not persistent)


@dataclass
class AuthenticationResult:
    """Result of authentication validation"""
    provider_name: str
    status: AuthenticationStatus
    message: str
    validated_at: datetime
    expires_at: Optional[datetime] = None
    permissions: Set[str] = field(default_factory=set)
    rate_limit_info: Optional[Dict[str, Any]] = None
    user_info: Optional[Dict[str, Any]] = None
    
    @property
    def is_valid(self) -> bool:
        """Check if authentication is valid"""
        return self.status == AuthenticationStatus.VALID
    
    @property
    def is_expired(self) -> bool:
        """Check if authentication is expired"""
        if self.expires_at:
            return datetime.now() > self.expires_at
        return False


@dataclass
class APIKeyInfo:
    """API key information and metadata"""
    provider_name: str
    key_hash: str  # Hashed version for identification
    created_at: datetime
    last_used: Optional[datetime] = None
    last_validated: Optional[datetime] = None
    validation_result: Optional[AuthenticationResult] = None
    usage_count: int = 0
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProviderAuthenticationManager:
    """
    Comprehensive authentication manager for LLM providers.
    
    Features:
    - Secure API key storage using system keyring or encryption
    - Authentication validation with caching
    - Provider-specific authentication handling
    - Startup validation and health monitoring
    - User feedback for authentication issues
    """
    
    def __init__(
        self,
        storage_backend: Optional[SecureStorageBackend] = None,
        cache_duration: int = 3600,  # 1 hour
        validation_timeout: int = 10
    ):
        self.config_manager = get_provider_config_manager()
        self.cache_duration = cache_duration
        self.validation_timeout = validation_timeout
        
        # Determine storage backend
        self.storage_backend = storage_backend or self._determine_best_storage_backend()
        
        # Initialize storage
        self._init_secure_storage()
        
        # Authentication cache
        self._auth_cache: Dict[str, AuthenticationResult] = {}
        self._api_key_info: Dict[str, APIKeyInfo] = {}
        self._cache_lock = threading.RLock()
        
        # Event handlers
        self._auth_change_handlers: List[Callable[[str, AuthenticationResult], None]] = []
        
        logger.info(f"Initialized provider authentication manager with {self.storage_backend.value} backend")
    
    # ---------- Secure Storage Management ----------
    
    def _determine_best_storage_backend(self) -> SecureStorageBackend:
        """Determine the best available storage backend"""
        if KEYRING_AVAILABLE:
            try:
                # Test keyring functionality
                keyring.get_password("kari-test", "test")
                return SecureStorageBackend.KEYRING
            except Exception:
                logger.warning("Keyring not functional, falling back to encrypted file")
        
        if CRYPTOGRAPHY_AVAILABLE:
            return SecureStorageBackend.ENCRYPTED_FILE
        
        logger.warning("No secure storage available, using environment variables only")
        return SecureStorageBackend.ENVIRONMENT
    
    def _init_secure_storage(self) -> None:
        """Initialize secure storage backend"""
        if self.storage_backend == SecureStorageBackend.ENCRYPTED_FILE:
            self._init_encrypted_file_storage()
        elif self.storage_backend == SecureStorageBackend.MEMORY:
            self._memory_storage: Dict[str, str] = {}
    
    def _init_encrypted_file_storage(self) -> None:
        """Initialize encrypted file storage"""
        if not CRYPTOGRAPHY_AVAILABLE:
            raise RuntimeError("Cryptography library not available for encrypted file storage")
        
        self.storage_dir = Path.home() / ".kari" / "auth"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize or load encryption key
        key_file = self.storage_dir / "storage.key"
        if key_file.exists():
            with open(key_file, 'rb') as f:
                self._encryption_key = f.read()
        else:
            self._encryption_key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(self._encryption_key)
            # Secure the key file
            os.chmod(key_file, 0o600)
        
        self._cipher = Fernet(self._encryption_key)
        self.credentials_file = self.storage_dir / "credentials.enc"
    
    # ---------- API Key Management ----------
    
    def store_api_key(self, provider_name: str, api_key: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Securely store an API key for a provider.
        
        Args:
            provider_name: Name of the provider
            api_key: The API key to store
            metadata: Optional metadata about the key
            
        Returns:
            True if storage was successful
        """
        try:
            # Validate provider exists
            config = self.config_manager.get_provider(provider_name)
            if not config:
                logger.error(f"Provider {provider_name} not found")
                return False
            
            # Store the key using the configured backend
            success = self._store_key_secure(provider_name, api_key)
            
            if success:
                # Create key info record
                key_hash = self._hash_api_key(api_key)
                key_info = APIKeyInfo(
                    provider_name=provider_name,
                    key_hash=key_hash,
                    created_at=datetime.now(),
                    metadata=metadata or {}
                )
                self._api_key_info[provider_name] = key_info
                
                # Clear authentication cache for this provider
                self._clear_auth_cache(provider_name)
                
                logger.info(f"Stored API key for provider: {provider_name}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to store API key for {provider_name}: {e}")
            return False
    
    def get_api_key(self, provider_name: str) -> Optional[str]:
        """
        Retrieve an API key for a provider.
        
        Args:
            provider_name: Name of the provider
            
        Returns:
            The API key or None if not found
        """
        try:
            # Try secure storage first
            api_key = self._retrieve_key_secure(provider_name)
            
            if api_key:
                # Update usage info
                if provider_name in self._api_key_info:
                    self._api_key_info[provider_name].last_used = datetime.now()
                    self._api_key_info[provider_name].usage_count += 1
                
                return api_key
            
            # Fallback to environment variable
            config = self.config_manager.get_provider(provider_name)
            if config and config.authentication.api_key_env_var:
                env_key = os.getenv(config.authentication.api_key_env_var)
                if env_key:
                    logger.debug(f"Using environment variable for {provider_name} API key")
                    return env_key
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to retrieve API key for {provider_name}: {e}")
            return None
    
    def remove_api_key(self, provider_name: str) -> bool:
        """
        Remove an API key for a provider.
        
        Args:
            provider_name: Name of the provider
            
        Returns:
            True if removal was successful
        """
        try:
            success = self._remove_key_secure(provider_name)
            
            if success:
                # Remove key info
                if provider_name in self._api_key_info:
                    del self._api_key_info[provider_name]
                
                # Clear authentication cache
                self._clear_auth_cache(provider_name)
                
                logger.info(f"Removed API key for provider: {provider_name}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove API key for {provider_name}: {e}")
            return False
    
    def list_stored_keys(self) -> List[str]:
        """List providers with stored API keys"""
        return list(self._api_key_info.keys())
    
    def get_key_info(self, provider_name: str) -> Optional[APIKeyInfo]:
        """Get information about a stored API key"""
        return self._api_key_info.get(provider_name)
    
    # ---------- Storage Backend Implementation ----------
    
    def _store_key_secure(self, provider_name: str, api_key: str) -> bool:
        """Store key using the configured secure backend"""
        if self.storage_backend == SecureStorageBackend.KEYRING:
            return self._store_key_keyring(provider_name, api_key)
        elif self.storage_backend == SecureStorageBackend.ENCRYPTED_FILE:
            return self._store_key_encrypted_file(provider_name, api_key)
        elif self.storage_backend == SecureStorageBackend.MEMORY:
            return self._store_key_memory(provider_name, api_key)
        else:
            logger.warning(f"Storage backend {self.storage_backend} does not support key storage")
            return False
    
    def _retrieve_key_secure(self, provider_name: str) -> Optional[str]:
        """Retrieve key using the configured secure backend"""
        if self.storage_backend == SecureStorageBackend.KEYRING:
            return self._retrieve_key_keyring(provider_name)
        elif self.storage_backend == SecureStorageBackend.ENCRYPTED_FILE:
            return self._retrieve_key_encrypted_file(provider_name)
        elif self.storage_backend == SecureStorageBackend.MEMORY:
            return self._retrieve_key_memory(provider_name)
        else:
            return None
    
    def _remove_key_secure(self, provider_name: str) -> bool:
        """Remove key using the configured secure backend"""
        if self.storage_backend == SecureStorageBackend.KEYRING:
            return self._remove_key_keyring(provider_name)
        elif self.storage_backend == SecureStorageBackend.ENCRYPTED_FILE:
            return self._remove_key_encrypted_file(provider_name)
        elif self.storage_backend == SecureStorageBackend.MEMORY:
            return self._remove_key_memory(provider_name)
        else:
            return False
    
    # Keyring backend
    def _store_key_keyring(self, provider_name: str, api_key: str) -> bool:
        """Store key in system keyring"""
        try:
            keyring.set_password("kari-llm-providers", provider_name, api_key)
            return True
        except Exception as e:
            logger.error(f"Failed to store key in keyring: {e}")
            return False
    
    def _retrieve_key_keyring(self, provider_name: str) -> Optional[str]:
        """Retrieve key from system keyring"""
        try:
            return keyring.get_password("kari-llm-providers", provider_name)
        except Exception as e:
            logger.error(f"Failed to retrieve key from keyring: {e}")
            return None
    
    def _remove_key_keyring(self, provider_name: str) -> bool:
        """Remove key from system keyring"""
        try:
            keyring.delete_password("kari-llm-providers", provider_name)
            return True
        except Exception as e:
            logger.error(f"Failed to remove key from keyring: {e}")
            return False
    
    # Encrypted file backend
    def _store_key_encrypted_file(self, provider_name: str, api_key: str) -> bool:
        """Store key in encrypted file"""
        try:
            # Load existing credentials
            credentials = self._load_encrypted_credentials()
            
            # Add/update the key
            credentials[provider_name] = api_key
            
            # Save encrypted credentials
            return self._save_encrypted_credentials(credentials)
        except Exception as e:
            logger.error(f"Failed to store key in encrypted file: {e}")
            return False
    
    def _retrieve_key_encrypted_file(self, provider_name: str) -> Optional[str]:
        """Retrieve key from encrypted file"""
        try:
            credentials = self._load_encrypted_credentials()
            return credentials.get(provider_name)
        except Exception as e:
            logger.error(f"Failed to retrieve key from encrypted file: {e}")
            return None
    
    def _remove_key_encrypted_file(self, provider_name: str) -> bool:
        """Remove key from encrypted file"""
        try:
            credentials = self._load_encrypted_credentials()
            if provider_name in credentials:
                del credentials[provider_name]
                return self._save_encrypted_credentials(credentials)
            return True
        except Exception as e:
            logger.error(f"Failed to remove key from encrypted file: {e}")
            return False
    
    def _load_encrypted_credentials(self) -> Dict[str, str]:
        """Load credentials from encrypted file"""
        if not self.credentials_file.exists():
            return {}
        
        try:
            with open(self.credentials_file, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = self._cipher.decrypt(encrypted_data)
            return json.loads(decrypted_data.decode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to load encrypted credentials: {e}")
            return {}
    
    def _save_encrypted_credentials(self, credentials: Dict[str, str]) -> bool:
        """Save credentials to encrypted file"""
        try:
            data = json.dumps(credentials).encode('utf-8')
            encrypted_data = self._cipher.encrypt(data)
            
            with open(self.credentials_file, 'wb') as f:
                f.write(encrypted_data)
            
            # Secure the file
            os.chmod(self.credentials_file, 0o600)
            return True
        except Exception as e:
            logger.error(f"Failed to save encrypted credentials: {e}")
            return False
    
    # Memory backend
    def _store_key_memory(self, provider_name: str, api_key: str) -> bool:
        """Store key in memory (not persistent)"""
        self._memory_storage[provider_name] = api_key
        return True
    
    def _retrieve_key_memory(self, provider_name: str) -> Optional[str]:
        """Retrieve key from memory"""
        return self._memory_storage.get(provider_name)
    
    def _remove_key_memory(self, provider_name: str) -> bool:
        """Remove key from memory"""
        if provider_name in self._memory_storage:
            del self._memory_storage[provider_name]
        return True
    
    # ---------- Authentication Validation ----------
    
    async def validate_authentication(self, provider_name: str, force_refresh: bool = False) -> AuthenticationResult:
        """
        Validate authentication for a provider.
        
        Args:
            provider_name: Name of the provider
            force_refresh: Force validation even if cached result is available
            
        Returns:
            Authentication result
        """
        # Check cache first
        if not force_refresh:
            cached_result = self._get_cached_auth_result(provider_name)
            if cached_result and not cached_result.is_expired:
                return cached_result
        
        try:
            config = self.config_manager.get_provider(provider_name)
            if not config:
                return AuthenticationResult(
                    provider_name=provider_name,
                    status=AuthenticationStatus.INVALID,
                    message="Provider not found",
                    validated_at=datetime.now()
                )
            
            # Perform provider-specific validation
            result = await self._validate_provider_auth(config)
            
            # Cache the result
            self._cache_auth_result(provider_name, result)
            
            # Update key info
            if provider_name in self._api_key_info:
                self._api_key_info[provider_name].last_validated = datetime.now()
                self._api_key_info[provider_name].validation_result = result
            
            # Notify handlers
            self._notify_auth_change_handlers(provider_name, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Authentication validation failed for {provider_name}: {e}")
            result = AuthenticationResult(
                provider_name=provider_name,
                status=AuthenticationStatus.NETWORK_ERROR,
                message=f"Validation failed: {str(e)}",
                validated_at=datetime.now()
            )
            self._cache_auth_result(provider_name, result)
            return result
    
    async def _validate_provider_auth(self, config: ProviderConfig) -> AuthenticationResult:
        """Validate authentication for a specific provider"""
        
        if config.authentication.type == AuthenticationType.NONE:
            return AuthenticationResult(
                provider_name=config.name,
                status=AuthenticationStatus.VALID,
                message="No authentication required",
                validated_at=datetime.now()
            )
        
        elif config.authentication.type == AuthenticationType.API_KEY:
            return await self._validate_api_key_auth(config)
        
        else:
            return AuthenticationResult(
                provider_name=config.name,
                status=AuthenticationStatus.UNKNOWN,
                message=f"Unsupported authentication type: {config.authentication.type}",
                validated_at=datetime.now()
            )
    
    async def validate_candidate_api_key(
        self, provider_name: str, api_key: str
    ) -> AuthenticationResult:
        """Probe an unsaved key without reading/storing workspace credentials.

        Uses the configured provider endpoint, never a client-supplied URL,
        and deliberately bypasses the provider authentication cache.
        """
        now = datetime.now()
        config = self.config_manager.get_provider(provider_name)
        if not config or not config.enabled:
            return AuthenticationResult(
                provider_name=provider_name,
                status=AuthenticationStatus.INVALID,
                message="Provider is not configured or enabled",
                validated_at=now,
            )
        if (
            not config.authentication
            or config.authentication.type != AuthenticationType.API_KEY
            or not isinstance(api_key, str)
            or not api_key.strip()
        ):
            return AuthenticationResult(
                provider_name=provider_name,
                status=AuthenticationStatus.INVALID,
                message="An API key is required for this provider",
                validated_at=now,
            )

        # Never forward a consumer-supplied credential to plaintext HTTP,
        # embedded URL credentials, or a noncanonical validation endpoint.
        base_url = str(getattr(config.endpoint, "base_url", "") or "")
        endpoint = config.authentication.validation_endpoint or "/models"
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not endpoint.startswith("/")
            or endpoint.startswith("//")
            or "?" in endpoint
            or "#" in endpoint
            or any(segment in {".", ".."} for segment in endpoint.split("/"))
        ):
            return AuthenticationResult(
                provider_name=provider_name,
                status=AuthenticationStatus.UNKNOWN,
                message="Provider has no approved secure validation endpoint",
                validated_at=now,
            )

        return await self._validate_api_key_auth(
            config,
            candidate_api_key=api_key.strip(),
            require_models_evidence=True,
        )

    async def _validate_api_key_auth(
        self,
        config: ProviderConfig,
        *,
        candidate_api_key: Optional[str] = None,
        require_models_evidence: bool = False,
    ) -> AuthenticationResult:
        """Validate API key authentication"""
        
        # Get API key
        api_key = candidate_api_key if candidate_api_key is not None else self.get_api_key(config.name)
        if not api_key:
            return AuthenticationResult(
                provider_name=config.name,
                status=AuthenticationStatus.INVALID,
                message="API key not configured",
                validated_at=datetime.now()
            )
        
        # Perform validation request
        try:
            import aiohttp
            
            # Prepare headers
            headers = {"User-Agent": "Kari-AI/1.0"}
            
            # Add authentication header
            if config.name == "gemini":
                # Candidate probes do not place secrets into URLs or HTTP logs.
                if candidate_api_key is not None:
                    headers["x-goog-api-key"] = api_key
            else:
                headers[config.authentication.api_key_header] = f"{config.authentication.api_key_prefix} {api_key}"
            
            # Build validation URL
            if config.authentication.validation_endpoint:
                url = f"{config.endpoint.base_url}{config.authentication.validation_endpoint}"
            else:
                url = f"{config.endpoint.base_url}/models"  # Default validation endpoint
            
            # Add API key to URL for Gemini
            if config.name == "gemini" and candidate_api_key is None:
                url += f"?key={api_key}"
            
            # Make validation request
            timeout = aiohttp.ClientTimeout(total=self.validation_timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, allow_redirects=False) as response:
                    
                    if response.status == 200:
                        # Parse response for additional info
                        try:
                            data = await response.json()
                            if require_models_evidence and (
                                not isinstance(data, dict)
                                or data.get("error") is not None
                                or not (
                                    isinstance(data.get("data"), list)
                                    or isinstance(data.get("models"), list)
                                )
                            ):
                                return AuthenticationResult(
                                    provider_name=config.name,
                                    status=AuthenticationStatus.UNKNOWN,
                                    message="Provider did not confirm authenticated model access",
                                    validated_at=datetime.now(),
                                )
                            user_info, permissions, rate_limit_info = self._parse_validation_response(config.name, data)
                            
                            return AuthenticationResult(
                                provider_name=config.name,
                                status=AuthenticationStatus.VALID,
                                message="API key is valid",
                                validated_at=datetime.now(),
                                expires_at=datetime.now() + timedelta(hours=24),  # Assume 24h validity
                                permissions=permissions,
                                rate_limit_info=rate_limit_info,
                                user_info=user_info
                            )
                        except Exception:
                            # Candidate keys must never be marked valid on a
                            # non-JSON or malformed successful response.
                            if require_models_evidence:
                                return AuthenticationResult(
                                    provider_name=config.name,
                                    status=AuthenticationStatus.UNKNOWN,
                                    message="Provider validation response was not verifiable",
                                    validated_at=datetime.now(),
                                )
                            return AuthenticationResult(
                                provider_name=config.name,
                                status=AuthenticationStatus.VALID,
                                message="API key is valid",
                                validated_at=datetime.now(),
                                expires_at=datetime.now() + timedelta(hours=24)
                            )
                    
                    elif response.status == 401:
                        return AuthenticationResult(
                            provider_name=config.name,
                            status=AuthenticationStatus.INVALID,
                            message="Invalid API key",
                            validated_at=datetime.now()
                        )
                    
                    elif response.status == 403:
                        return AuthenticationResult(
                            provider_name=config.name,
                            status=AuthenticationStatus.INSUFFICIENT_PERMISSIONS,
                            message="API key lacks required permissions",
                            validated_at=datetime.now()
                        )
                    
                    elif response.status == 429:
                        return AuthenticationResult(
                            provider_name=config.name,
                            status=AuthenticationStatus.RATE_LIMITED,
                            message="Rate limit exceeded",
                            validated_at=datetime.now()
                        )
                    
                    else:
                        return AuthenticationResult(
                            provider_name=config.name,
                            status=AuthenticationStatus.UNKNOWN,
                            message=f"Validation failed with status {response.status}",
                            validated_at=datetime.now()
                        )
        
        except ImportError:
            logger.warning("aiohttp not available for authentication validation")
            return AuthenticationResult(
                provider_name=config.name,
                status=AuthenticationStatus.UNKNOWN,
                message="Cannot validate - aiohttp not available",
                validated_at=datetime.now()
            )
        
        except asyncio.TimeoutError:
            return AuthenticationResult(
                provider_name=config.name,
                status=AuthenticationStatus.NETWORK_ERROR,
                message="Validation request timed out",
                validated_at=datetime.now()
            )
        
        except Exception as e:
            return AuthenticationResult(
                provider_name=config.name,
                status=AuthenticationStatus.NETWORK_ERROR,
                message="Provider validation network error" if candidate_api_key is not None else f"Network error: {str(e)}",
                validated_at=datetime.now()
            )
    
    def _parse_validation_response(self, provider_name: str, data: Dict[str, Any]) -> tuple:
        """Parse validation response for additional information"""
        user_info = {}
        permissions = set()
        rate_limit_info = {}
        
        try:
            if provider_name == "openai":
                # OpenAI /models response
                if "data" in data:
                    permissions.add("models")
                    if any("gpt-4" in model.get("id", "") for model in data["data"]):
                        permissions.add("gpt-4")
            
            elif provider_name == "gemini":
                # Gemini /models response
                if "models" in data:
                    permissions.add("models")
                    for model in data["models"]:
                        if "generateContent" in model.get("supportedGenerationMethods", []):
                            permissions.add("generate_content")
            
            elif provider_name == "huggingface":
                # HuggingFace /whoami response
                if "name" in data:
                    user_info["username"] = data["name"]
                if "type" in data:
                    user_info["account_type"] = data["type"]
                if "plan" in data:
                    user_info["plan"] = data["plan"]
        
        except Exception as e:
            logger.debug(f"Failed to parse validation response for {provider_name}: {e}")
        
        return user_info, permissions, rate_limit_info
    
    # ---------- Startup Validation ----------
    
    async def validate_all_providers(self) -> Dict[str, AuthenticationResult]:
        """Validate authentication for all configured providers"""
        results = {}
        
        providers = self.config_manager.list_providers(enabled_only=True)
        
        # Run validations concurrently
        tasks = [
            self.validate_authentication(provider.name)
            for provider in providers
            if provider.authentication.type != AuthenticationType.NONE
        ]
        
        if tasks:
            validation_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(validation_results):
                if isinstance(result, AuthenticationResult):
                    results[result.provider_name] = result
                else:
                    provider_name = providers[i].name
                    results[provider_name] = AuthenticationResult(
                        provider_name=provider_name,
                        status=AuthenticationStatus.NETWORK_ERROR,
                        message=f"Validation failed: {str(result)}",
                        validated_at=datetime.now()
                    )
        
        return results
    
    def get_authentication_summary(self) -> Dict[str, Any]:
        """Get summary of authentication status for all providers"""
        summary = {
            "total_providers": len(self.config_manager.list_providers()),
            "providers_with_auth": 0,
            "valid_authentications": 0,
            "invalid_authentications": 0,
            "stored_keys": len(self._api_key_info),
            "storage_backend": self.storage_backend.value,
            "providers": {}
        }
        
        for provider in self.config_manager.list_providers():
            auth_required = provider.authentication.type != AuthenticationType.NONE
            if auth_required:
                summary["providers_with_auth"] += 1
            
            cached_result = self._get_cached_auth_result(provider.name)
            auth_status = "unknown"
            if cached_result:
                auth_status = cached_result.status.value
                if cached_result.is_valid:
                    summary["valid_authentications"] += 1
                elif cached_result.status == AuthenticationStatus.INVALID:
                    summary["invalid_authentications"] += 1
            
            summary["providers"][provider.name] = {
                "auth_required": auth_required,
                "auth_type": provider.authentication.type.value,
                "auth_status": auth_status,
                "has_stored_key": provider.name in self._api_key_info,
                "last_validated": cached_result.validated_at.isoformat() if cached_result else None
            }
        
        return summary
    
    # ---------- Cache Management ----------
    
    def _get_cached_auth_result(self, provider_name: str) -> Optional[AuthenticationResult]:
        """Get cached authentication result"""
        with self._cache_lock:
            result = self._auth_cache.get(provider_name)
            if result and datetime.now() - result.validated_at < timedelta(seconds=self.cache_duration):
                return result
            return None
    
    def _cache_auth_result(self, provider_name: str, result: AuthenticationResult) -> None:
        """Cache authentication result"""
        with self._cache_lock:
            self._auth_cache[provider_name] = result
    
    def _clear_auth_cache(self, provider_name: Optional[str] = None) -> None:
        """Clear authentication cache"""
        with self._cache_lock:
            if provider_name:
                self._auth_cache.pop(provider_name, None)
            else:
                self._auth_cache.clear()
    
    # ---------- Event Handlers ----------
    
    def add_auth_change_handler(self, handler: Callable[[str, AuthenticationResult], None]) -> None:
        """Add authentication change event handler"""
        self._auth_change_handlers.append(handler)
    
    def remove_auth_change_handler(self, handler: Callable[[str, AuthenticationResult], None]) -> None:
        """Remove authentication change event handler"""
        if handler in self._auth_change_handlers:
            self._auth_change_handlers.remove(handler)
    
    def _notify_auth_change_handlers(self, provider_name: str, result: AuthenticationResult) -> None:
        """Notify authentication change handlers"""
        for handler in self._auth_change_handlers:
            try:
                handler(provider_name, result)
            except Exception as e:
                logger.warning(f"Authentication change handler failed: {e}")
    
    # ---------- Utility Methods ----------
    
    def _hash_api_key(self, api_key: str) -> str:
        """Create a hash of the API key for identification"""
        return hashlib.sha256(api_key.encode()).hexdigest()[:16]
    
    def get_provider_auth_status(self, provider_name: str) -> str:
        """Get human-readable authentication status for a provider"""
        cached_result = self._get_cached_auth_result(provider_name)
        if not cached_result:
            return "Not validated"
        
        if cached_result.is_expired:
            return "Expired"
        
        status_messages = {
            AuthenticationStatus.VALID: "Valid",
            AuthenticationStatus.INVALID: "Invalid API key",
            AuthenticationStatus.EXPIRED: "Expired",
            AuthenticationStatus.RATE_LIMITED: "Rate limited",
            AuthenticationStatus.INSUFFICIENT_PERMISSIONS: "Insufficient permissions",
            AuthenticationStatus.NETWORK_ERROR: "Network error",
            AuthenticationStatus.UNKNOWN: "Unknown status"
        }
        
        return status_messages.get(cached_result.status, "Unknown")


# Global instance
_provider_auth_manager: Optional[ProviderAuthenticationManager] = None


def get_provider_auth_manager() -> ProviderAuthenticationManager:
    """Get the global provider authentication manager instance"""
    global _provider_auth_manager
    if _provider_auth_manager is None:
        _provider_auth_manager = ProviderAuthenticationManager()
    return _provider_auth_manager


def reset_provider_auth_manager() -> None:
    """Reset the global provider authentication manager (for testing)"""
    global _provider_auth_manager
    _provider_auth_manager = None
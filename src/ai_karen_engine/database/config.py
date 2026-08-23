"""
Database Configuration Validation Module.

This module provides centralized configuration management and validation
for database connections, ensuring proper environment variable handling
and clear error reporting for missing or invalid configurations.

DEPRECATED: Prefer ``ai_karen_engine.config.database.DatabaseSettings``.
This shim remains for backward compatibility during DATA-CONVERGE-2.
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs
import re

from ai_karen_engine.config import Settings

# --- Canonical config re-exports (DATA-CONVERGE-2) ---
from ai_karen_engine.config.database import (  # noqa: F401
    DatabaseSettings,
    SupabaseSettings,
    PostgresSettings,
    PoolSettings,
    get_database_settings,
    refresh_database_settings,
)

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """Database configuration with validation and fallback mechanisms."""
    
    # Core connection parameters
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    database: str = "ai_karen"
    
    # Connection pool configuration
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600
    
    # Optional complete URL override
    url: Optional[str] = None
    
    # SSL configuration
    ssl_mode: str = "prefer"
    ssl_cert: Optional[str] = None
    ssl_key: Optional[str] = None
    ssl_ca: Optional[str] = None
    
    # Debug and logging
    debug_sql: bool = False
    
    # Validation results
    validation_errors: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        self._validate_configuration()
    
    def _validate_configuration(self) -> None:
        """Validate the database configuration."""
        self.validation_errors.clear()
        self.validation_warnings.clear()
        
        # Validate host
        if not self.host or not self.host.strip():
            self.validation_errors.append("Database host cannot be empty")
        
        # Validate port
        if not isinstance(self.port, int) or self.port <= 0 or self.port > 65535:
            self.validation_errors.append(f"Invalid database port: {self.port}. Must be between 1 and 65535")
        
        # Validate user
        if not self.user or not self.user.strip():
            self.validation_errors.append("Database user cannot be empty")
        
        # Validate password
        if not self.password:
            self.validation_warnings.append("Database password is empty - this may cause authentication failures")
        
        # Validate database name
        if not self.database or not self.database.strip():
            self.validation_errors.append("Database name cannot be empty")
        elif not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', self.database):
            self.validation_errors.append(f"Invalid database name: {self.database}. Must start with letter or underscore and contain only alphanumeric characters and underscores")
        
        # Validate pool configuration
        if self.pool_size <= 0:
            self.validation_errors.append(f"Pool size must be positive: {self.pool_size}")
        
        if self.max_overflow < 0:
            self.validation_errors.append(f"Max overflow cannot be negative: {self.max_overflow}")
        
        if self.pool_timeout <= 0:
            self.validation_errors.append(f"Pool timeout must be positive: {self.pool_timeout}")
        
        if self.pool_recycle <= 0:
            self.validation_errors.append(f"Pool recycle time must be positive: {self.pool_recycle}")
        
        # Validate SSL mode
        valid_ssl_modes = ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]
        if self.ssl_mode not in valid_ssl_modes:
            self.validation_errors.append(f"Invalid SSL mode: {self.ssl_mode}. Must be one of: {', '.join(valid_ssl_modes)}")
        
        # Validate URL if provided
        if self.url:
            try:
                parsed = urlparse(self.url)
                if parsed.scheme not in ["postgresql", "postgres"]:
                    self.validation_errors.append(f"Invalid database URL scheme: {parsed.scheme}. Must be 'postgresql' or 'postgres'")
                if not parsed.hostname:
                    self.validation_errors.append("Database URL must contain a hostname")
                if parsed.port and (parsed.port <= 0 or parsed.port > 65535):
                    self.validation_errors.append(f"Invalid port in database URL: {parsed.port}")
            except Exception as e:
                self.validation_errors.append(f"Invalid database URL format: {e}")
    
    def is_valid(self) -> bool:
        """Check if the configuration is valid."""
        return len(self.validation_errors) == 0
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """Get a summary of validation results."""
        return {
            "valid": self.is_valid(),
            "errors": self.validation_errors.copy(),
            "warnings": self.validation_warnings.copy(),
            "error_count": len(self.validation_errors),
            "warning_count": len(self.validation_warnings)
        }
    
    def build_database_url(self) -> str:
        """Build the database URL from configuration parameters."""
        if self.url:
            return self.url
        
        # Handle special characters in password
        password_encoded = self.password.replace("@", "%40").replace(":", "%3A").replace("/", "%2F")
        
        # Build base URL
        url = f"postgresql://{self.user}:{password_encoded}@{self.host}:{self.port}/{self.database}"
        
        # Add SSL parameters if needed
        params = []
        if self.ssl_mode != "prefer":  # prefer is the default
            params.append(f"sslmode={self.ssl_mode}")
        
        if self.ssl_cert:
            params.append(f"sslcert={self.ssl_cert}")
        
        if self.ssl_key:
            params.append(f"sslkey={self.ssl_key}")
        
        if self.ssl_ca:
            params.append(f"sslrootcert={self.ssl_ca}")
        
        if params:
            url += "?" + "&".join(params)
        
        return url
    
    def build_async_database_url(self) -> str:
        """Build the async database URL (asyncpg) from configuration parameters."""
        base_url = self.build_database_url()
        return base_url.replace("postgresql://", "postgresql+asyncpg://")
    
    def get_sanitized_config(self) -> Dict[str, Any]:
        """Get configuration with sensitive data sanitized for logging."""
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": "***" if self.password else "(empty)",
            "database": self.database,
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_timeout": self.pool_timeout,
            "pool_recycle": self.pool_recycle,
            "ssl_mode": self.ssl_mode,
            "debug_sql": self.debug_sql,
            "url_provided": bool(self.url),
            "validation_status": "valid" if self.is_valid() else "invalid"
        }


class DatabaseConfigurationError(Exception):
    """Exception raised for database configuration errors."""
    
    def __init__(self, message: str, errors: List[str] = None, warnings: List[str] = None):
        super().__init__(message)
        self.errors = errors or []
        self.warnings = warnings or []


class DatabaseConfigLoader:
    """Loads and validates database configuration from environment variables."""
    
    # Environment variable mappings
    ENV_MAPPINGS = {
        "host": ["POSTGRES_HOST", "DATABASE_HOST", "DB_HOST"],
        "port": ["POSTGRES_PORT", "DATABASE_PORT", "DB_PORT"],
        "user": ["POSTGRES_USER", "DATABASE_USER", "DB_USER"],
        "password": ["POSTGRES_PASSWORD", "DATABASE_PASSWORD", "DB_PASSWORD"],
        "database": ["POSTGRES_DB", "DATABASE_NAME", "DB_NAME"],
        "url": ["DATABASE_URL", "POSTGRES_URL", "DB_URL"],
        "pool_size": ["DB_POOL_SIZE", "DATABASE_POOL_SIZE"],
        "max_overflow": ["DB_MAX_OVERFLOW", "DATABASE_MAX_OVERFLOW"],
        "pool_timeout": ["DB_POOL_TIMEOUT", "DATABASE_POOL_TIMEOUT"],
        "pool_recycle": ["DB_POOL_RECYCLE", "DATABASE_POOL_RECYCLE"],
        "ssl_mode": ["DB_SSL_MODE", "DATABASE_SSL_MODE", "POSTGRES_SSL_MODE"],
        "ssl_cert": ["DB_SSL_CERT", "DATABASE_SSL_CERT", "POSTGRES_SSL_CERT"],
        "ssl_key": ["DB_SSL_KEY", "DATABASE_SSL_KEY", "POSTGRES_SSL_KEY"],
        "ssl_ca": ["DB_SSL_CA", "DATABASE_SSL_CA", "POSTGRES_SSL_CA"],
        "debug_sql": ["SQL_DEBUG", "DB_DEBUG", "DATABASE_DEBUG"]
    }
    
    @classmethod
    def load_from_environment(cls, env_file_path: Optional[str] = None) -> DatabaseConfig:
        """
        Load database configuration from environment variables.
        
        Args:
            env_file_path: Optional path to .env file to load first
            
        Returns:
            DatabaseConfig instance
            
        Raises:
            DatabaseConfigurationError: If configuration is invalid
        """
        # Load .env file if specified
        if env_file_path and os.path.exists(env_file_path):
            cls._load_env_file(env_file_path)
        
        # Extract configuration values
        config_values = {}
        missing_vars = []
        
        for config_key, env_vars in cls.ENV_MAPPINGS.items():
            value = None
            found_var = None
            
            # Try each environment variable in order of preference
            for env_var in env_vars:
                value = os.getenv(env_var)
                if value is not None:
                    found_var = env_var
                    break
            
            if value is not None:
                # Convert value to appropriate type
                if config_key in ["port", "pool_size", "max_overflow", "pool_timeout", "pool_recycle"]:
                    try:
                        config_values[config_key] = int(value)
                    except ValueError:
                        logger.warning(f"Invalid integer value for {found_var}: {value}")
                        continue
                elif config_key == "debug_sql":
                    config_values[config_key] = value.lower() in ["true", "1", "yes", "on"]
                else:
                    config_values[config_key] = value
                
                logger.debug(f"Loaded {config_key} from {found_var}")
            else:
                # Track missing critical variables
                if config_key in ["host", "user", "password", "database"]:
                    missing_vars.append(f"{config_key} (tried: {', '.join(env_vars)})")
        
        # Create configuration instance
        config = DatabaseConfig(**config_values)
        
        # Add missing variable warnings
        for missing_var in missing_vars:
            config.validation_warnings.append(f"Environment variable not found: {missing_var}")
        
        # Log configuration status
        sanitized = config.get_sanitized_config()
        logger.info(f"Database configuration loaded: {sanitized}")
        
        # Log validation results
        validation = config.get_validation_summary()
        if validation["errors"]:
            logger.error(f"Database configuration errors: {validation['errors']}")
        if validation["warnings"]:
            logger.warning(f"Database configuration warnings: {validation['warnings']}")
        
        # Raise exception if configuration is invalid
        if not config.is_valid():
            raise DatabaseConfigurationError(
                f"Database configuration is invalid: {len(config.validation_errors)} errors found",
                errors=config.validation_errors,
                warnings=config.validation_warnings
            )
        
        return config
    
    @staticmethod
    def _load_env_file(env_file_path: str) -> None:
        """Load environment variables from .env file."""
        try:
            with open(env_file_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse key=value pairs
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # Remove inline comments (everything after # that's not in quotes)
                        if '#' in value and not (value.startswith('"') or value.startswith("'")):
                            value = value.split('#')[0].strip()
                        
                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        
                        # Handle variable substitution (basic ${VAR} support)
                        if '${' in value and '}' in value:
                            import re
                            def replace_var(match):
                                var_name = match.group(1)
                                replacement = os.getenv(var_name, '')
                                # If replacement is empty, skip this variable
                                if not replacement:
                                    return ''
                                return replacement
                            value = re.sub(r'\$\{([^}]+)\}', replace_var, value)
                            
                            # Skip empty values after substitution
                            if not value.strip():
                                continue
                        
                        # Set environment variable if not already set
                        if key not in os.environ:
                            os.environ[key] = value
                            logger.debug(f"Loaded {key} from {env_file_path}")
                    else:
                        logger.warning(f"Invalid line in {env_file_path}:{line_num}: {line}")
        
        except Exception as e:
            logger.error(f"Failed to load environment file {env_file_path}: {e}")
            raise


def load_database_config(env_file_path: Optional[str] = None) -> DatabaseConfig:
    """
    Convenience function to load database configuration.
    
    Args:
        env_file_path: Optional path to .env file (defaults to .env in current directory)
        
    Returns:
        DatabaseConfig instance
        
    Raises:
        DatabaseConfigurationError: If configuration is invalid
    """
    if env_file_path is None:
        env_file_path = ".env"
    
    return DatabaseConfigLoader.load_from_environment(env_file_path)


def validate_database_connection(config: DatabaseConfig) -> Dict[str, Any]:
    """
    Validate database connection using the provided configuration.
    
    Args:
        config: DatabaseConfig instance
        
    Returns:
        Dictionary with connection test results
    """
    result = {
        "success": False,
        "error": None,
        "connection_time": None,
        "server_version": None,
        "database_exists": False
    }
    
    try:
        import time
        from sqlalchemy import create_engine, text
        
        start_time = time.time()
        
        # Create test engine
        engine = create_engine(
            config.build_database_url(),
            pool_size=1,
            max_overflow=0,
            pool_timeout=10
        )
        
        # Test connection
        with engine.connect() as conn:
            # Get server version
            version_result = conn.execute(text("SELECT version()"))
            result["server_version"] = version_result.scalar()
            
            # Check if database exists
            db_result = conn.execute(text("SELECT current_database()"))
            current_db = db_result.scalar()
            result["database_exists"] = current_db == config.database
            
            conn.commit()
        
        result["connection_time"] = time.time() - start_time
        result["success"] = True
        
        engine.dispose()
        
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Database connection validation failed: {e}")
    
    return result

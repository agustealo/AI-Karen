"""
Backward Compatibility Layer for Directory Structure Reorganization

Provides temporary compatibility imports during migration with:
- Detailed usage tracking
- Version-aware deprecation warnings
- Automatic module redirection
- Migration progress monitoring
"""

import warnings
import sys
import importlib
import inspect
import time
from typing import Any, Dict, Optional, Type, Callable, Union, List
from types import ModuleType
from dataclasses import dataclass, field
from datetime import datetime
import functools
import logging

# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# === Configuration ===
@dataclass
class CompatibilityConfig:
    removal_version: str = "0.5.0"
    warn_once_per_module: bool = True
    track_usage: bool = True
    strict_checks: bool = False

class ImportRedirect:
    """Descriptor for attribute access with redirection tracking"""
    def __init__(self, name: str, old_path: str, new_path: str, manager: 'CompatibilityImportManager'):
        self.name = name
        self.old_path = old_path
        self.new_path = new_path
        self.manager = manager
        self._resolved = None

    def __get__(self, obj, objtype=None):
        if self._resolved is None:
            try:
                module = importlib.import_module(self.new_path)
                self._resolved = getattr(module, self.name)
                self.manager.track_successful_redirect(self.old_path)
            except (ImportError, AttributeError) as e:
                self.manager.track_failed_redirect(self.old_path, str(e))
                raise AttributeError(
                    f"Could not redirect '{self.old_path}.{self.name}' to '{self.new_path}.{self.name}': {e}"
                ) from e

        self.manager.track_usage(self.old_path)
        warnings.warn(
            f"Import of '{self.name}' from '{self.old_path}' is deprecated. "
            f"Use '{self.new_path}.{self.name}' instead. "
            f"Will be removed in version {self.manager.config.removal_version}.",
            DeprecationWarning,
            stacklevel=3
        )
        return self._resolved

@dataclass
class MigrationStats:
    total_redirects: int = 0
    successful_redirects: int = 0
    failed_redirects: int = 0
    usage_counts: Dict[str, int] = field(default_factory=dict)
    first_use_timestamps: Dict[str, float] = field(default_factory=dict)
    last_use_timestamps: Dict[str, float] = field(default_factory=dict)
    error_messages: Dict[str, List[str]] = field(default_factory=lambda: {})

class CompatibilityImportManager:
    """Central manager for compatibility imports during migration"""
    
    def __init__(self, config: Optional[CompatibilityConfig] = None):
        self.config = config or CompatibilityConfig()
        self.stats = MigrationStats()
        self._seen_warnings = set()
        self._redirect_cache = {}
        
        # Define all migration paths
        self.import_mappings = {
            # Core system mappings
            "ai_karen_engine.plugin_manager": "ai_karen_engine.extensions.platform.core.manager",
            "ai_karen_engine.plugin_router": "ai_karen_engine.plugins.router",
            
            # Plugin mappings organized by category
            "examples": {
                "ai_karen_engine.plugins.hello_world": "ai_karen_engine.plugins.router",
                "ai_karen_engine.plugins.sandbox_fail": "ai_karen_engine.plugins.router",
            },
            "integrations": {
                "ai_karen_engine.plugins.llm_manager": "ai_karen_engine.core.model_runtime.routing.llm_router_service",
            },
            "ai": {
                "ai_karen_engine.plugins.llm_services": "ai_karen_engine.core.model_runtime.routing.llm_router_service",
            }
        }
    
    def track_usage(self, old_path: str) -> None:
        """Track usage of deprecated import paths"""
        if not self.config.track_usage:
            return
            
        now = time.time()
        self.stats.usage_counts[old_path] = self.stats.usage_counts.get(old_path, 0) + 1
        self.stats.total_redirects += 1
        
        if old_path not in self.stats.first_use_timestamps:
            self.stats.first_use_timestamps[old_path] = now
        self.stats.last_use_timestamps[old_path] = now
    
    def track_successful_redirect(self, old_path: str) -> None:
        """Track successful import redirections"""
        self.stats.successful_redirects += 1
    
    def track_failed_redirect(self, old_path: str, error: str) -> None:
        """Track failed import redirections"""
        self.stats.failed_redirects += 1
        if old_path not in self.stats.error_messages:
            self.stats.error_messages[old_path] = []
        self.stats.error_messages[old_path].append(error)
    
    def get_usage_report(self) -> Dict[str, Any]:
        """Generate comprehensive usage report"""
        return {
            "summary": {
                "total_redirects": self.stats.total_redirects,
                "successful_redirects": self.stats.successful_redirects,
                "failed_redirects": self.stats.failed_redirects,
                "unique_deprecated_paths": len(self.stats.usage_counts),
            },
            "usage_details": {
                "most_used": max(self.stats.usage_counts.items(), key=lambda x: x[1]) if self.stats.usage_counts else None,
                "least_used": min(self.stats.usage_counts.items(), key=lambda x: x[1]) if self.stats.usage_counts else None,
                "unused_paths": [path for path in self.import_mappings if path not in self.stats.usage_counts],
            },
            "timing": {
                "first_use": min(self.stats.first_use_timestamps.values()) if self.stats.first_use_timestamps else None,
                "last_use": max(self.stats.last_use_timestamps.values()) if self.stats.last_use_timestamps else None,
            },
            "errors": self.stats.error_messages,
        }
    
    def deprecated_import(self, old_path: str, new_path: str, removal_version: Optional[str] = None):
        """Decorator factory for deprecated imports"""
        removal = removal_version or self.config.removal_version
        
        def decorator(obj):
            nonlocal old_path, new_path
            
            if inspect.isclass(obj) or inspect.isfunction(obj):
                # For classes and functions
                @functools.wraps(obj)
                def wrapper(*args, **kwargs):
                    self._warn_deprecated(old_path, new_path, removal)
                    return obj(*args, **kwargs)
                
                return wrapper
            else:
                # For modules
                class DeprecatedModule(ModuleType):
                    def __getattr__(self, name):
                        self._warn_deprecated(old_path, new_path, removal)
                        try:
                            new_module = importlib.import_module(new_path)
                            return getattr(new_module, name)
                        except (ImportError, AttributeError) as e:
                            raise AttributeError(
                                f"Could not redirect '{old_path}.{name}' to '{new_path}.{name}': {e}"
                            ) from e
                
                return DeprecatedModule(old_path)
        
        return decorator
    
    def _warn_deprecated(self, old_path: str, new_path: str, removal_version: str):
        """Issue deprecation warning with tracking"""
        if self.config.warn_once_per_module:
            key = f"{old_path}->{new_path}"
            if key in self._seen_warnings:
                return
            self._seen_warnings.add(key)
        
        self.track_usage(old_path)
        warnings.warn(
            f"Import from '{old_path}' is deprecated. "
            f"Use '{new_path}' instead. "
            f"Will be removed in version {removal_version}.",
            DeprecationWarning,
            stacklevel=3
        )
    
    def create_compatibility_module(self, old_path: str, new_path: str) -> None:
        """Create a module that redirects imports to new location"""
        if old_path in sys.modules:
            return
            
        try:
            new_module = importlib.import_module(new_path)
            
            class CompatibilityModule(ModuleType):
                def __getattr__(self, name):
                    self.track_usage(old_path)
                    try:
                        return getattr(new_module, name)
                    except AttributeError as e:
                        raise AttributeError(
                            f"'{name}' not found in '{new_path}' (compatibility redirect from '{old_path}')"
                        ) from e
            
            sys.modules[old_path] = CompatibilityModule(old_path)
            self.track_successful_redirect(old_path)
            logger.info(f"Created compatibility redirect: {old_path} -> {new_path}")
        
        except ImportError as e:
            self.track_failed_redirect(old_path, str(e))
            if self.config.strict_checks:
                logger.warning(f"Failed to create compatibility redirect: {old_path} -> {new_path}: {e}")
    
    def setup_compatibility_imports(self) -> None:
        """Initialize all compatibility imports"""
        # Process core mappings
        for old_path, new_path in self.import_mappings.items():
            if isinstance(new_path, dict):
                # Skip category containers
                continue
            self.create_compatibility_module(old_path, new_path)
        
        # Process plugin mappings by category
        for category, mappings in self.import_mappings.items():
            if isinstance(mappings, dict):
                for old_path, new_path in mappings.items():
                    self.create_compatibility_module(old_path, new_path)

# Global manager instance
_compat_manager = CompatibilityImportManager()

# === Public API ===
def deprecated_import(old_path: str, new_path: str, removal_version: Optional[str] = None):
    """Public decorator for deprecated imports"""
    return _compat_manager.deprecated_import(old_path, new_path, removal_version)

def check_deprecated_imports() -> Dict[str, Any]:
    """Check usage of deprecated imports"""
    return _compat_manager.get_usage_report()

def warn_about_deprecated_import(old_path: str, new_path: str) -> None:
    """Warn about specific deprecated import"""
    _compat_manager._warn_deprecated(old_path, new_path, _compat_manager.config.removal_version)

def is_migration_complete() -> bool:
    """Check if migration to new structure is complete"""
    try:
        importlib.import_module("ai_karen_engine.plugins.manager")
        importlib.import_module("ai_karen_engine.plugins.router")
        
        # Check some representative plugins
        importlib.import_module("plugins_hub.ai.llm_manager")
        
        return True
    except ImportError:
        return False

def get_migration_progress() -> Dict[str, Any]:
    """Get detailed migration progress report"""
    report = _compat_manager.get_usage_report()
    report["migration_complete"] = is_migration_complete()
    report["pending_migrations"] = [
        path for path in _compat_manager.import_mappings
        if path not in report["usage_details"]["unused_paths"]
    ]
    return report

# Initialize compatibility imports when module loads
_compat_manager.setup_compatibility_imports()

# === Compatibility Exports ===
__all__ = [
    "deprecated_import",
    "check_deprecated_imports",
    "warn_about_deprecated_import",
    "is_migration_complete",
    "get_migration_progress",
]


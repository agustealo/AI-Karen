"""
Settings Manager

This module manages application settings including feature flags,
copilot configuration, and validation of cloud feature requirements.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from ai_karen_engine.core.security.secrets.secrets import get_secret_manager

logger = logging.getLogger(__name__)


class SettingsManager:
    """
    Manages application settings with feature flag support and validation.
    """
    
    def __init__(self, settings_path: Optional[Path] = None):
        """
        Initialize settings manager.
        
        Args:
            settings_path: Path to settings.json file
        """
        self.settings_path = settings_path or Path("src/ai_karen_engine/config/settings.json")
        self.secret_manager = get_secret_manager()
        self.settings: Dict[str, Any] = {}
        self._load_settings()
    
    def _load_settings(self) -> None:
        """Load settings from JSON file."""
        try:
            if self.settings_path.exists():
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    self.settings = json.load(f)
                self._normalize_settings()
                logger.info(f"Loaded settings from {self.settings_path}")
            else:
                logger.warning(f"Settings file not found: {self.settings_path}")
                self.settings = self._get_default_settings()
                self._save_settings()
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            self.settings = self._get_default_settings()
    
    def _save_settings(self) -> None:
        """Save settings to JSON file."""
        try:
            self._normalize_settings()
            # Ensure directory exists
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
            
            logger.info(f"Settings saved to {self.settings_path}")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """Get default settings configuration."""
        return {
            "provider": "local_gguf",
            "model": "Phi-3-mini-4k-instruct-q4.gguf",
            "use_memory": True,
            "context_length": 512,
            "decay": 0.1,
            "features": {
                "copilot_cloud_enabled": False,
                "copilot_advanced_ui": True,
                "copilot_batch_operations": True
            },
            "copilot": {
                "default_profile": "local_default",
                "max_concurrent_operations": 3,
                "timeout_seconds": 30,
                "enable_audit_logging": True
            }
        }

    def _normalize_settings(self) -> None:
        """Remove legacy fields that no longer belong in mutable app settings."""
        # Provider secrets are stored in SecretManager, not in settings.json.
        self.settings.pop("api_key", None)
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value using dot notation.
        
        Args:
            key: Setting key (supports dot notation like 'features.copilot_cloud_enabled')
            default: Default value if key not found
            
        Returns:
            Setting value or default
        """
        keys = key.split('.')
        value = self.settings
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set_setting(self, key: str, value: Any, save: bool = True) -> None:
        """
        Set a setting value using dot notation.
        
        Args:
            key: Setting key (supports dot notation)
            value: Value to set
            save: Whether to save settings to file immediately
        """
        keys = key.split('.')
        current = self.settings
        
        # Navigate to the parent of the target key
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        
        # Set the value
        current[keys[-1]] = value
        
        if save:
            self._save_settings()
    
    def get_feature_flag(self, flag_name: str) -> bool:
        """
        Get feature flag value.
        
        Args:
            flag_name: Name of the feature flag
            
        Returns:
            True if feature is enabled, False otherwise
        """
        return self.get_setting(f"features.{flag_name}", False)
    
    def set_feature_flag(self, flag_name: str, enabled: bool, save: bool = True) -> None:
        """
        Set feature flag value.
        
        Args:
            flag_name: Name of the feature flag
            enabled: Whether to enable the feature
            save: Whether to save settings immediately
        """
        self.set_setting(f"features.{flag_name}", enabled, save)
        logger.info(f"Feature flag '{flag_name}' set to {enabled}")
    
    def get_copilot_setting(self, setting_name: str, default: Any = None) -> Any:
        """
        Get copilot-specific setting.
        
        Args:
            setting_name: Name of the copilot setting
            default: Default value if not found
            
        Returns:
            Setting value or default
        """
        return self.get_setting(f"copilot.{setting_name}", default)
    
    def set_copilot_setting(self, setting_name: str, value: Any, save: bool = True) -> None:
        """
        Set copilot-specific setting.
        
        Args:
            setting_name: Name of the copilot setting
            value: Value to set
            save: Whether to save settings immediately
        """
        self.set_setting(f"copilot.{setting_name}", value, save)
    
    def has_secret(self, secret_name: str) -> bool:
        """
        Check if a secret exists.
        
        Args:
            secret_name: Name of the secret
            
        Returns:
            True if secret exists, False otherwise
        """
        return self.secret_manager.has_secret(secret_name)
    
    def validate_cloud_features(self) -> Dict[str, Any]:
        """
        Validate cloud feature requirements.
        
        Returns:
            Dictionary with validation results
        """
        validation_result = {
            "can_use_cloud": False,
            "errors": [],
            "warnings": [],
            "requirements_met": {
                "feature_flag": False,
                "api_key": False
            }
        }
        
        # Check feature flag
        cloud_enabled = self.get_feature_flag("copilot_cloud_enabled")
        validation_result["requirements_met"]["feature_flag"] = cloud_enabled
        
        if not cloud_enabled:
            validation_result["errors"].append("Cloud features are disabled (feature flag: copilot_cloud_enabled)")
        
        # Check API key
        has_api_key = self.has_secret("COPILOT_API_KEY")
        validation_result["requirements_met"]["api_key"] = has_api_key
        
        if not has_api_key:
            validation_result["errors"].append("No COPILOT_API_KEY configured")
        
        # Overall validation
        validation_result["can_use_cloud"] = cloud_enabled and has_api_key
        
        if validation_result["can_use_cloud"]:
            validation_result["warnings"].append("Cloud features are enabled - ensure API key is valid")
        
        return validation_result
    
    def validate_profile_requirements(self, profile_config: Dict[str, Any]) -> List[str]:
        """
        Validate requirements for a specific profile configuration.
        
        Args:
            profile_config: Profile configuration to validate
            
        Returns:
            List of validation error messages
        """
        errors = []
        
        # Check cloud gating requirements
        routing = profile_config.get("routing", {})
        cloud_gating = routing.get("cloud_gating", {})
        
        if cloud_gating:
            # Check required feature flag
            required_flag = cloud_gating.get("requires_feature_flag")
            if required_flag:
                flag_value = self.get_feature_flag(required_flag.replace("features.", ""))
                if not flag_value:
                    errors.append(f"Required feature flag '{required_flag}' is not enabled")
            
            # Check required API key
            required_key = cloud_gating.get("requires_api_key")
            if required_key:
                if not self.has_secret(required_key):
                    errors.append(f"Required API key '{required_key}' is not configured")
        
        # Check model-specific requirements
        models = profile_config.get("models", [])
        for i, model in enumerate(models):
            # Check feature flag requirements
            when_flag = model.get("when_flag")
            if when_flag:
                flag_value = self.get_feature_flag(when_flag.replace("features.", ""))
                if not flag_value:
                    errors.append(f"Model {i}: Required feature flag '{when_flag}' is not enabled")
            
            # Check API key requirements
            api_key_ref = model.get("require_api_key_ref")
            if api_key_ref:
                if not self.has_secret(api_key_ref):
                    errors.append(f"Model {i}: Required API key '{api_key_ref}' is not configured")
        
        return errors
    
    def get_settings_status(self) -> Dict[str, Any]:
        """
        Get comprehensive settings status.
        
        Returns:
            Dictionary with settings status information
        """
        cloud_validation = self.validate_cloud_features()
        
        # Get feature flags status
        features = self.get_setting("features", {})
        feature_status = {}
        for flag_name, enabled in features.items():
            feature_status[flag_name] = {
                "enabled": enabled,
                "description": self._get_feature_description(flag_name)
            }
        
        # Get copilot settings
        copilot_settings = self.get_setting("copilot", {})
        
        # Get secrets status
        secrets_status = {}
        for secret_name in ["COPILOT_API_KEY"]:
            secrets_status[secret_name] = self.secret_manager.get_secret_status(secret_name)
        
        return {
            "settings_file": str(self.settings_path),
            "cloud_validation": cloud_validation,
            "feature_flags": feature_status,
            "copilot_settings": copilot_settings,
            "secrets": secrets_status,
            "last_loaded": datetime.utcnow().isoformat()
        }
    
    def _get_feature_description(self, flag_name: str) -> str:
        """Get description for a feature flag."""
        descriptions = {
            "copilot_cloud_enabled": "Enable cloud LLM providers for copilot operations",
            "copilot_advanced_ui": "Enable advanced copilot UI features",
            "copilot_batch_operations": "Enable batch operations in copilot"
        }
        return descriptions.get(flag_name, "No description available")
    
    def reload_settings(self) -> None:
        """Reload settings from file."""
        logger.info("Reloading settings configuration")
        self._load_settings()
    
    def export_settings(self, include_secrets: bool = False) -> Dict[str, Any]:
        """
        Export settings for backup or migration.
        
        Args:
            include_secrets: Whether to include secret names (not values)
            
        Returns:
            Dictionary with exportable settings
        """
        export_data = {
            "settings": self.settings.copy(),
            "exported_at": datetime.utcnow().isoformat()
        }
        
        if include_secrets:
            export_data["secrets"] = list(self.secret_manager.list_secrets().keys())
        
        return export_data
    
    def import_settings(self, settings_data: Dict[str, Any], merge: bool = True) -> bool:
        """
        Import settings from backup or migration.
        
        Args:
            settings_data: Settings data to import
            merge: Whether to merge with existing settings or replace
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if merge:
                # Merge with existing settings
                self._deep_merge(self.settings, settings_data.get("settings", {}))
            else:
                # Replace settings
                self.settings = settings_data.get("settings", {})
            
            self._save_settings()
            logger.info("Settings imported successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to import settings: {e}")
            return False
    
    def _deep_merge(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """Deep merge source dictionary into target dictionary."""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value


# Global settings manager instance
_settings_manager_instance: Optional[SettingsManager] = None


def get_settings_manager() -> SettingsManager:
    """Get global settings manager instance."""
    global _settings_manager_instance
    if _settings_manager_instance is None:
        _settings_manager_instance = SettingsManager()
    return _settings_manager_instance


def reload_settings_manager() -> SettingsManager:
    """Reload the global settings manager instance."""
    global _settings_manager_instance
    _settings_manager_instance = SettingsManager()
    return _settings_manager_instance

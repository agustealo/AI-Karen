"""Centralized loaders for configuration assets."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
import logging

logger = logging.getLogger(__name__)


def load_optimization_config() -> Dict[str, Any]:
    """Load optimization configuration from config_assets/optimization_config.json."""
    config_path = Path("config_assets/optimization_config.json")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(
                f"Failed to load optimization config from {config_path}: {e}"
            )
    return {}


def load_permissions_config() -> Dict[str, Any]:
    """Load permissions configuration from config_assets/permissions.json."""
    config_path = Path("config_assets/permissions.json")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load permissions config from {config_path}: {e}")
    return {}


def load_model_runtime_discovery_config() -> Dict[str, Any]:
    """Load model runtime discovery configuration."""
    config_path = Path("config_assets/model_runtime_discovery.json")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(
                f"Failed to load model runtime discovery config from {config_path}: {e}"
            )
    return {}


def load_local_model_runtime_config() -> Dict[str, Any]:
    """Backward-compatible alias for the discovery config loader."""
    return load_model_runtime_discovery_config()


def load_extension_configs() -> List[Dict[str, Any]]:
    """Load extension configurations from config_assets/extensions/ directory."""
    configs = []
    config_dir = Path("config_assets/extensions")
    if config_dir.exists():
        for filename in os.listdir(config_dir):
            if filename.endswith(".yaml") or filename.endswith(".yml"):
                filepath = config_dir / filename
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        config = yaml.safe_load(f)
                        if config:
                            configs.append(config)
                except Exception as e:
                    logger.warning(
                        f"Failed to load extension config from {filepath}: {e}"
                    )
    return configs


def load_memory_policy_config() -> Dict[str, Any]:
    """Load memory policy configuration from config_assets/memory.yml."""
    config_path = Path("config_assets/memory.yml")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(
                f"Failed to load memory policy config from {config_path}: {e}"
            )
    return {}


def load_llm_profiles_config() -> Dict[str, Any]:
    """Load LLM profiles configuration from config_assets/llm_profiles.yml."""
    config_path = Path("config_assets/llm_profiles.yml")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(
                f"Failed to load LLM profiles config from {config_path}: {e}"
            )
    return {}


def load_performance_config() -> Dict[str, Any]:
    """Load performance configuration from config_assets/performance.yml."""
    config_path = Path("config_assets/performance.yml")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load performance config from {config_path}: {e}")
    return {}


def load_deployment_config() -> Dict[str, Any]:
    """Load deployment configuration from config_assets/services.yml."""
    config_path = Path("config_assets/services.yml")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load deployment config from {config_path}: {e}")
    return {}


def load_model_download_recommendations() -> Dict[str, Any]:
    """Load canonical consumer model download recommendations."""
    config_path = Path("config_assets/model_download_recommendations.json")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
                return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            logger.warning(
                "Failed to load model download recommendations from %s: %s",
                config_path,
                exc,
            )
    return {}

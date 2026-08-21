"""
System initialization module for AI Karen Engine.
Ensures all necessary files, folders, models, and dependencies are properly set up on first run.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable
import json
import urllib.request
import urllib.error

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)


class SystemInitializer:
    """
    Handles system initialization and setup on first run.
    Ensures all necessary components are available and properly configured.
    """

    def __init__(self):
        self.logger = logger
        self.base_dir = Path.cwd()
        # Use local models directory instead of /models to avoid permission issues
        self.models_dir = Path(os.getenv("KARI_MODEL_DIR", "models"))
        self.data_dir = Path("data")
        self.config_dir = Path("config")

        self.default_models = {
            "transformers": [
                "models/transformers/Qwen--Qwen3.5-0.8B",
                "models/transformers/deepseek-ai--DeepSeek-R1-Distill-Qwen-1.5B",
            ],
        }

        # Required directories
        self.required_dirs = [
            self.models_dir,
            self.models_dir / "transformers",
            self.models_dir / "groq",
            self.data_dir,
            self.data_dir / "attachments",
            self.data_dir / "bootstrap",
            self.data_dir / "migrations",
            self.config_dir,
            Path("logs"),
            Path("extensions"),
            Path("plugins"),
        ]

        # Required config files
        self.required_configs: Dict[str, Callable[[], Any]] = {
            "config_assets/config.json": self._get_default_config,
            "model_registry.json": self._get_default_model_registry,
            "config_assets/llm_profiles.yml": self._get_default_llm_profiles,
            "config_assets/memory.yml": self._get_default_memory_config,
            "config_assets/security_config.yml": self._get_default_security_config,
        }

    async def initialize_system(self, force_reinstall: bool = False) -> Dict[str, bool]:
        """
        Initialize the entire system on first run.

        Args:
            force_reinstall: Force reinstallation of all components

        Returns:
            Dict with initialization results for each component
        """
        results = {}

        self.logger.info("Starting system initialization...")

        # 1. Create required directories
        results["directories"] = await self._setup_directories()

        # 2. Setup configuration files
        results["configs"] = await self._setup_config_files(force_reinstall)

        # 3. Install required Python packages
        results["packages"] = await self._install_required_packages()

        # 4. Download and setup models
        self.logger.info("Stage 4: Setting up models...")
        results["models"] = await self._setup_models(force_reinstall)

        # 5. Initialize databases
        self.logger.info("Stage 5: Initializing databases...")
        results["database"] = await self._initialize_databases()

        # 6. Setup CopilotKit if configured
        self.logger.info("Stage 6: Checking CopilotKit...")
        results["copilotkit"] = await self._setup_copilotkit()

        # 7. Discover and register plugins/extensions
        self.logger.info("Stage 7: Discovering plugins...")
        results["plugins"] = await self._discover_plugins()

        # 8. Validate system health
        results["validation"] = await self._validate_system_health()

        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)

        if success_count == total_count:
            self.logger.info("✅ System initialization completed successfully!")
        else:
            self.logger.warning(
                f"⚠️ System initialization completed with issues: {success_count}/{total_count} components successful"
            )

        return results

    async def _setup_directories(self) -> bool:
        """Create all required directories."""
        try:
            for directory in self.required_dirs:
                directory.mkdir(parents=True, exist_ok=True)
                self.logger.info(f"✅ Created directory: {directory}")

            # Set proper permissions for models directory
            if self.models_dir.exists():
                os.chmod(self.models_dir, 0o755)

            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to create directories: {e}")
            return False

    async def _setup_config_files(self, force_reinstall: bool = False) -> bool:
        """Setup all required configuration files."""
        try:
            for config_path, config_generator in self.required_configs.items():
                file_path = Path(config_path)

                if file_path.exists() and not force_reinstall:
                    self.logger.info(f"✅ Config file already exists: {config_path}")
                    continue

                # Create parent directories if needed
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # Generate and write config
                config_content = config_generator()

                if config_path.endswith(".json"):
                    with open(file_path, "w") as f:
                        json.dump(config_content, f, indent=2)
                else:
                    with open(file_path, "w") as f:
                        f.write(config_content)

                self.logger.info(f"✅ Created config file: {config_path}")

            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to setup config files: {e}")
            return False

    async def _install_required_packages(self) -> bool:
        """Install required Python packages."""
        required_packages = [
            "transformers>=4.21.0",
            "torch>=1.12.0",
            "sentence-transformers>=2.2.0",
            "spacy>=3.4.0",
            "huggingface-hub>=0.10.0",
        ]

        optional_packages = [
            "copilotkit",  # Optional CopilotKit integration
        ]

        try:
            # Install required packages
            for package in required_packages:
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", package],
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )

                    if result.returncode == 0:
                        self.logger.info(f"✅ Installed package: {package}")
                    else:
                        self.logger.warning(
                            f"⚠️ Failed to install {package}: {result.stderr}"
                        )
                except subprocess.TimeoutExpired:
                    self.logger.warning(f"⚠️ Timeout installing {package}")

            # Install optional packages (don't fail if they can't be installed)
            for package in optional_packages:
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", package],
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )

                    if result.returncode == 0:
                        self.logger.info(f"✅ Installed optional package: {package}")
                    else:
                        self.logger.info(
                            f"ℹ️ Optional package {package} not installed (this is OK)"
                        )
                except subprocess.TimeoutExpired:
                    self.logger.info(
                        f"ℹ️ Timeout installing optional package {package} (this is OK)"
                    )

            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to install packages: {e}")
            return False

    async def _setup_models(self, force_reinstall: bool = False) -> bool:
        """Download and setup required models asynchronously."""
        try:
            loop = asyncio.get_running_loop()
            
            # Setup transformers models in executor (using sync helper)
            await loop.run_in_executor(None, self._setup_transformers_models_sync, force_reinstall)

            # Download spaCy model in executor (using sync helper)
            await loop.run_in_executor(None, self._setup_spacy_models_sync)

            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to setup models: {e}")
            return False

    def _setup_transformers_models_sync(self, force_reinstall: bool = False) -> None:
        """Synchronous helper for Transformers setup."""
        try:
            from transformers import AutoTokenizer, AutoModel

            # Check if distilbert-base-uncased already exists
            existing_distilbert = self.models_dir / "distilbert-base-uncased"
            if existing_distilbert.exists():
                self.logger.info(
                    "✅ distilbert-base-uncased already available in models directory"
                )

            for model_name in self.default_models["transformers"]:
                # Check if model already exists locally
                cache_dir = self.models_dir / "transformers" / model_name
                if cache_dir.exists() and not force_reinstall:
                    self.logger.info(
                        f"✅ Transformers model already exists: {model_name}"
                    )
                    continue

                try:
                    self.logger.info(f"📥 Downloading transformers model: {model_name}")

                    # Download tokenizer and model
                    tokenizer = AutoTokenizer.from_pretrained(model_name)
                    model = AutoModel.from_pretrained(model_name)

                    # Save to local cache
                    cache_dir.mkdir(parents=True, exist_ok=True)

                    tokenizer.save_pretrained(cache_dir)
                    model.save_pretrained(cache_dir)

                    self.logger.info(f"✅ Setup transformers model: {model_name}")

                except Exception as e:
                    self.logger.warning(
                        f"⚠️ Failed to setup transformers model {model_name}: {e}"
                    )

        except ImportError:
            self.logger.warning(
                "⚠️ Transformers library not available - skipping transformers models"
            )

    def _setup_spacy_models_sync(self) -> None:
        """Synchronous helper for spaCy download."""
        try:
            import subprocess
            import sys
            # Download English model
            result = subprocess.run(
                [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode == 0:
                self.logger.info("✅ Downloaded spaCy English model")
            else:
                self.logger.warning(
                    f"⚠️ Failed to download spaCy model: {result.stderr}"
                )

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to setup spaCy models: {e}")

    async def _setup_transformers_models(self, force_reinstall: bool = False) -> None:
        # Compatibility shim
        self._setup_transformers_models_sync(force_reinstall)

    async def _setup_spacy_models(self) -> None:
        # Compatibility shim
        self._setup_spacy_models_sync()

    async def _download_file_with_progress(self, url: str, destination: Path) -> None:
        """Download a file with progress logging."""
        destination.parent.mkdir(parents=True, exist_ok=True)

        def progress_hook(block_num, block_size, total_size):
            if total_size > 0:
                percent = min(100, (block_num * block_size * 100) // total_size)
                if block_num % 100 == 0:  # Log every 100 blocks to avoid spam
                    self.logger.info(f"📥 Download progress: {percent}%")

        try:
            urllib.request.urlretrieve(url, destination, reporthook=progress_hook)
        except urllib.error.URLError as e:
            raise Exception(f"Failed to download from {url}: {e}")

    async def _initialize_databases(self) -> bool:
        """Initialize required databases."""
        try:
            # 1. Create SQLite database files if they don't exist
            db_files = ["auth.db", "auth_sessions.db", "data/kari_automation.db"]

            for db_file in db_files:
                db_path = Path(db_file)
                if not db_path.exists():
                    db_path.parent.mkdir(parents=True, exist_ok=True)
                    db_path.touch()
                    self.logger.info(f"✅ Created SQLite database: {db_file}")

            # 2. Initialize PostgreSQL Tables
            try:
                from ai_karen_engine.database.client import MultiTenantPostgresClient

                db_client = MultiTenantPostgresClient()
                self.logger.info("🛠️ Initializing PostgreSQL tables...")
                await db_client.create_tables_async()
                self.logger.info("✅ PostgreSQL tables initialized successfully")
            except Exception as e:
                self.logger.warning(
                    f"⚠️ Non-critical failure initializing PostgreSQL: {e}"
                )

            return True
        except Exception as e:
            self.logger.exception(f"❌ Failed to initialize databases: {e}")
            return False

    async def _setup_copilotkit(self) -> bool:
        """Setup CopilotKit if available and configured."""
        try:
            # Check if CopilotKit is available
            try:
                import copilotkit

                self.logger.info("✅ CopilotKit library is available")

                # Check for API key configuration
                api_key = os.getenv("COPILOTKIT_API_KEY")
                if api_key:
                    self.logger.info("✅ CopilotKit API key is configured")
                else:
                    self.logger.info(
                        "ℹ️ CopilotKit API key not configured - using fallback mode"
                    )

                return True

            except ImportError:
                self.logger.info(
                    "ℹ️ CopilotKit library not installed - using fallback mode"
                )
                return True  # This is OK - fallback mode works

        except Exception as e:
            self.logger.warning(f"⚠️ CopilotKit setup issue: {e}")
            return True  # Don't fail initialization for optional component

    async def _discover_plugins(self) -> bool:
        """Discover and load plugin manifests into the registry."""
        try:
            from ai_karen_engine.extensions.platform.core.manager import (
                get_plugin_manager,
            )

            manager = get_plugin_manager()
            await manager.discover_extensions()
            plugins = manager.registry.list_plugins()
            self.logger.info(f"✅ Discovered and registered {len(plugins)} plugins")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to discover plugins: {e}")
            return False

    async def _validate_system_health(self) -> bool:
        """Validate that the system is properly initialized."""
        try:
            health_checks = []

            # Check directories exist
            for directory in self.required_dirs:
                health_checks.append(directory.exists())

            # Check models directory has content or is properly set up
            models_exist = (
                len(list(self.models_dir.glob("**/*.gguf"))) > 0
                or len(list(self.models_dir.glob("**/*.bin"))) > 0
                or (self.models_dir / "transformers").exists()
            )
            health_checks.append(models_exist)

            # Check config files exist
            for config_path in self.required_configs.keys():
                health_checks.append(Path(config_path).exists())

            success_rate = sum(health_checks) / len(health_checks)

            if success_rate >= 0.8:  # 80% success rate
                self.logger.info(
                    f"✅ System health validation passed ({success_rate:.1%})"
                )
                return True
            else:
                self.logger.warning(
                    f"⚠️ System health validation concerns ({success_rate:.1%})"
                )
                return False

        except Exception as e:
            self.logger.error(f"❌ System health validation failed: {e}")
            return False

    # Configuration generators
    def _get_default_config(self) -> Dict[str, Any]:
        """Generate default config.json."""
        return {
            "app_name": "AI Karen Engine",
            "version": "0.4.0",
            "environment": "development",
            "logging": {
                "level": "INFO",
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
            "models": {
                "default_provider": "builtin_vllm",
                "model_dir": str(self.models_dir),
                "cache_enabled": True,
            },
            "expression": {
                "active_engine": "builtin",
                "enabled_engines": ["builtin", "openai_compatible_local"],
                "fallback_order": ["builtin", "openai_compatible_local", "llama_cpp_server", "glm"],
                "policies": {
                    "allow_third_party": True,
                    "allow_external": False
                }
            },
            "features": {
                "extensions_enabled": True,
                "plugins_enabled": True,
                "memory_system_enabled": True,
                "copilotkit_enabled": False,
            },
        }

    def _get_default_model_registry(self) -> Dict:
        """Generate default model registry."""
        return {
            "providers": {
                "builtin_vllm": {
                    "enabled": True,
                    "models_dir": str(self.models_dir / "vllm"),
                    "supported_formats": [".gguf", ".bin"],
                },
                "transformers": {
                    "enabled": True,
                    "models_dir": str(self.models_dir / "transformers"),
                    "cache_dir": str(self.models_dir / "transformers"),
                },
                "copilotkit": {
                    "enabled": False,
                    "api_key": None,
                    "base_url": "https://api.copilotkit.ai",
                },
            },
            "default_models": {
                "chat": "auto",
                "completion": "auto",
                "embedding": "distilbert-base-uncased",
            },
        }

    def _get_default_llm_profiles(self) -> str:
        """Generate default LLM profiles YAML."""
        return """
profiles:
  default:
    provider: builtin_transformers
    model: auto
    temperature: 0.7
    max_tokens: 150
    
  creative:
    provider: builtin_transformers
    model: auto
    temperature: 0.9
    max_tokens: 200
    
  precise:
    provider: builtin_transformers
    model: auto
    temperature: 0.3
    max_tokens: 100
"""

    def _get_default_memory_config(self) -> str:
        """Generate default memory configuration YAML."""
        return """
memory:
  enabled: true
  provider: local
  
  storage:
    type: sqlite
    path: data/memory.db
    
  embedding:
    provider: transformers
    model: distilbert-base-uncased
    dimension: 768
    
  retrieval:
    top_k: 10
    similarity_threshold: 0.7
"""

    def _get_default_security_config(self) -> str:
        """Generate default security configuration YAML."""
        return """
security:
  authentication:
    enabled: true
    session_timeout: 3600
    
  authorization:
    rbac_enabled: true
    default_role: user
    
  encryption:
    algorithm: AES-256-GCM
    key_rotation_days: 90
    
  audit:
    enabled: true
    log_level: INFO
"""


# Convenience function for easy initialization
async def initialize_system(force_reinstall: bool = False) -> Dict[str, bool]:
    """
    Initialize the AI Karen Engine system.

    Args:
        force_reinstall: Force reinstallation of all components

    Returns:
        Dict with initialization results
    """
    initializer = SystemInitializer()
    return await initializer.initialize_system(force_reinstall)


# NOTE: Auto-initialization at import time was removed due to race conditions.
# Applications should explicitly call initialize_system() during their startup sequence.
# Example:
#
#   @app.on_event("startup")
#   async def startup():
#       from ai_karen_engine.core.runtime.initialization import initialize_system
#       results = await initialize_system()
#       logger.info(f"System initialization complete: {results}")
#
# For migration from auto-init, set KARI_SKIP_AUTO_INIT=true in your environment.

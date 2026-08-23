"""
Secret Manager

This module provides encrypted storage for sensitive data like API keys
with presence-only API responses for security.
"""

import base64
import json
import logging
import os
import shutil
import tempfile
from cryptography.fernet import Fernet
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class SecretManager:
    """
    Manages encrypted storage of secrets with presence-only API responses.
    """

    def __init__(self, secrets_dir: Optional[Path] = None):
        self.legacy_secrets_dir = Path("config_assets/secrets")
        self.secrets_dir = self._resolve_secrets_dir(secrets_dir)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_directory_permissions(self.secrets_dir)
        self._migrate_legacy_secrets_if_needed()

        self.key_file = self.secrets_dir / ".key"
        self.cipher = self._get_or_create_cipher()

        self.metadata_file = self.secrets_dir / "metadata.json"
        self.metadata = self._load_metadata()

    def _resolve_secrets_dir(self, secrets_dir: Optional[Path]) -> Path:
        if secrets_dir is not None:
            return secrets_dir

        env_dir = os.getenv("KARI_SECRETS_DIR")
        if env_dir:
            return Path(os.path.expanduser(env_dir))

        container_secure = Path("/secure/secrets")
        if self._is_directory_writable(container_secure.parent):
            return container_secure

        user_secure = Path.home() / ".kari" / "secure" / "secrets"
        if self._is_directory_writable(user_secure.parent):
            return user_secure

        return Path(tempfile.gettempdir()) / "kari" / "secrets"

    def _is_directory_writable(self, path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".write_test"
            with open(test_file, "w", encoding="utf-8") as handle:
                handle.write("ok")
            test_file.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def _ensure_directory_permissions(self, path: Path) -> None:
        try:
            os.chmod(path, 0o700)
        except Exception:
            logger.debug(
                "Unable to apply secure permissions to %s", path, exc_info=True
            )

    def _migrate_legacy_secrets_if_needed(self) -> None:
        if self.secrets_dir == self.legacy_secrets_dir:
            return
        if not self.legacy_secrets_dir.exists():
            return

        for candidate in [
            ".key",
            "metadata.json",
            *[p.name for p in self.legacy_secrets_dir.glob("*.enc")],
        ]:
            source = self.legacy_secrets_dir / candidate
            target = self.secrets_dir / candidate
            if not source.exists() or target.exists():
                continue
            try:
                shutil.copy2(source, target)
            except Exception as exc:
                logger.warning(
                    "Failed to migrate legacy secret artifact %s: %s", source, exc
                )

    def _get_or_create_cipher(self) -> Fernet:
        if self.key_file.exists():
            with open(self.key_file, "rb") as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            with open(self.key_file, "wb") as f:
                f.write(key)
            os.chmod(self.key_file, 0o600)

        return Fernet(key)

    def _load_metadata(self) -> Dict[str, Any]:
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load secrets metadata: {e}")

        return {}

    def _save_metadata(self) -> None:
        try:
            self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, indent=2)
            os.chmod(self.metadata_file, 0o600)
        except Exception as e:
            logger.error(f"Failed to save secrets metadata: {e}")
            raise

    def _refresh_metadata(self) -> None:
        self.metadata = self._load_metadata()

    def set_secret(self, name: str, value: str, description: str = "") -> bool:
        try:
            encrypted_value = self.cipher.encrypt(value.encode("utf-8"))

            secret_file = self.secrets_dir / f"{name}.enc"
            with open(secret_file, "wb") as f:
                f.write(encrypted_value)
            os.chmod(secret_file, 0o600)

            self.metadata[name] = {
                "description": description,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "file": str(secret_file.name),
            }
            self._save_metadata()

            logger.info(f"Secret '{name}' stored successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to store secret '{name}': {e}")
            return False

    def get_secret(self, name: str) -> Optional[str]:
        try:
            secret_file = self.secrets_dir / f"{name}.enc"
            if not secret_file.exists():
                return None

            with open(secret_file, "rb") as f:
                encrypted_value = f.read()

            decrypted_value = self.cipher.decrypt(encrypted_value)
            return decrypted_value.decode("utf-8")

        except Exception as e:
            logger.error(f"Failed to retrieve secret '{name}': {e}")
            return None

    def has_secret(self, name: str) -> bool:
        secret_file = self.secrets_dir / f"{name}.enc"
        if not secret_file.exists():
            return False
        if name in self.metadata:
            return True
        self._refresh_metadata()
        if name in self.metadata:
            return True
        logger.warning(
            "Secret file exists for '%s' but metadata is missing; treating file presence as configured.",
            name,
        )
        return True

    def delete_secret(self, name: str) -> bool:
        try:
            secret_file = self.secrets_dir / f"{name}.enc"

            if secret_file.exists():
                secret_file.unlink()

            if name in self.metadata:
                del self.metadata[name]
                self._save_metadata()

            logger.info(f"Secret '{name}' deleted successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to delete secret '{name}': {e}")
            return False

    def list_secrets(self) -> Dict[str, Dict[str, Any]]:
        result = {}

        for name, metadata in self.metadata.items():
            result[name] = {
                "description": metadata.get("description", ""),
                "created_at": metadata.get("created_at"),
                "updated_at": metadata.get("updated_at"),
                "exists": self.has_secret(name),
            }

        return result

    def get_secret_status(self, name: str) -> Dict[str, Any]:
        exists = self.has_secret(name)
        metadata = self.metadata.get(name, {})

        return {
            "name": name,
            "exists": exists,
            "description": metadata.get("description", ""),
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
        }

    def validate_secret_format(self, name: str, value: str) -> Dict[str, Any]:
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "provider_compatible": [],
            "security_score": 100,
            "recommendations": [],
        }

        if len(value) < 8:
            validation_result["valid"] = False
            validation_result["errors"].append(
                "Secret appears too short (minimum 8 characters)"
            )
            validation_result["security_score"] -= 50

        if value.lower() in ["password", "secret", "key", "token"]:
            validation_result["valid"] = False
            validation_result["errors"].append(
                "Secret appears to be a placeholder value"
            )
            validation_result["security_score"] = 0

        if "API_KEY" in name.upper():
            if len(value) < 10:
                validation_result["valid"] = False
                validation_result["errors"].append("API key appears too short")
                validation_result["security_score"] -= 30

            if value.count("0") > len(value) * 0.5:
                validation_result["warnings"].append(
                    "API key contains many zeros - verify it's correct"
                )
                validation_result["security_score"] -= 10

            if "OPENAI" in name.upper():
                if not value.startswith("sk-"):
                    validation_result["warnings"].append(
                        "OpenAI API keys typically start with 'sk-'"
                    )
                    validation_result["security_score"] -= 5
                if len(value) < 40:
                    validation_result["warnings"].append(
                        "OpenAI API keys are typically longer"
                    )
                    validation_result["security_score"] -= 10
                validation_result["provider_compatible"].append("openai")

            elif "ANTHROPIC" in name.upper():
                if not value.startswith("sk-ant-"):
                    validation_result["warnings"].append(
                        "Anthropic API keys typically start with 'sk-ant-'"
                    )
                    validation_result["security_score"] -= 5
                validation_result["provider_compatible"].append("anthropic")

            elif "GEMINI" in name.upper() or "GOOGLE" in name.upper():
                if len(value) < 30:
                    validation_result["warnings"].append(
                        "Google API keys are typically longer"
                    )
                    validation_result["security_score"] -= 10
                validation_result["provider_compatible"].append("gemini")

            elif "DEEPSEEK" in name.upper():
                if not value.startswith("sk-"):
                    validation_result["warnings"].append(
                        "DeepSeek API keys typically start with 'sk-'"
                    )
                    validation_result["security_score"] -= 5
                validation_result["provider_compatible"].append("deepseek")

            elif "COPILOT" in name.upper():
                if value.startswith("sk-"):
                    if value.startswith("sk-ant-"):
                        validation_result["provider_compatible"].append("anthropic")
                    else:
                        validation_result["provider_compatible"].extend(
                            ["openai", "deepseek"]
                        )
                else:
                    validation_result["provider_compatible"].append("gemini")

                if not validation_result["provider_compatible"]:
                    validation_result["provider_compatible"].extend(
                        ["openai", "anthropic", "deepseek", "gemini"]
                    )

        if validation_result["security_score"] < 80:
            validation_result["recommendations"].append(
                "Consider regenerating the API key from the provider"
            )

        if (
            len(validation_result["provider_compatible"]) == 0
            and "API_KEY" in name.upper()
        ):
            validation_result["recommendations"].append(
                "Verify the API key format matches your intended provider"
            )

        return validation_result

    def validate_secret_security(self, name: str, value: str) -> Dict[str, Any]:
        security_result = {
            "secure": True,
            "risk_level": "low",
            "issues": [],
            "recommendations": [],
            "entropy_score": 0.0,
        }

        if value:
            import math
            from collections import Counter

            counter = Counter(value)
            length = len(value)
            entropy = -sum(
                (count / length) * math.log2(count / length)
                for count in counter.values()
            )
            security_result["entropy_score"] = entropy

            if entropy < 3.0:
                security_result["secure"] = False
                security_result["risk_level"] = "high"
                security_result["issues"].append(
                    "Low entropy - secret may be predictable"
                )
                security_result["recommendations"].append(
                    "Use a cryptographically secure random generator"
                )
            elif entropy < 4.0:
                security_result["risk_level"] = "medium"
                security_result["issues"].append(
                    "Moderate entropy - consider using more random characters"
                )

        patterns = [
            ("123", "Contains sequential numbers"),
            ("abc", "Contains sequential letters"),
            ("000", "Contains repeated characters"),
            ("password", "Contains common words"),
            ("test", "Appears to be a test value"),
        ]

        value_lower = value.lower()
        for pattern, message in patterns:
            if pattern in value_lower:
                security_result["secure"] = False
                security_result["risk_level"] = "high"
                security_result["issues"].append(message)

        if len(value) < 16:
            security_result["issues"].append(
                "Secret is shorter than recommended minimum (16 characters)"
            )
            if security_result["risk_level"] == "low":
                security_result["risk_level"] = "medium"

        return security_result

    def rotate_encryption_key(self) -> bool:
        try:
            logger.info("Starting encryption key rotation")

            current_secrets = {}
            for name in self.metadata.keys():
                secret_value = self.get_secret(name)
                if secret_value:
                    current_secrets[name] = secret_value

            new_key = Fernet.generate_key()
            new_cipher = Fernet(new_key)

            for name, value in current_secrets.items():
                encrypted_value = new_cipher.encrypt(value.encode("utf-8"))
                secret_file = self.secrets_dir / f"{name}.enc"
                with open(secret_file, "wb") as f:
                    f.write(encrypted_value)
                os.chmod(secret_file, 0o600)

            with open(self.key_file, "wb") as f:
                f.write(new_key)
            os.chmod(self.key_file, 0o600)

            self.cipher = new_cipher

            logger.info("Encryption key rotation completed successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to rotate encryption key: {e}")
            return False


_secret_manager_instance: Optional[SecretManager] = None


def get_secret_manager() -> SecretManager:
    """Get global secret manager instance."""
    global _secret_manager_instance
    if _secret_manager_instance is None:
        _secret_manager_instance = SecretManager()
    return _secret_manager_instance

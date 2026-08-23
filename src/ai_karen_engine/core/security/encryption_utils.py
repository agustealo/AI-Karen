from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet


log = logging.getLogger(__name__)


def _is_production_env() -> bool:
    env = os.getenv("ENVIRONMENT") or os.getenv("KARI_ENV") or "development"
    return env.lower() in ("production", "prod")


ENCRYPTION_KEY = os.getenv("KARI_JOB_ENC_KEY")
if not ENCRYPTION_KEY:
    if _is_production_env():
        raise RuntimeError("KARI_JOB_ENC_KEY must be set in production")
    ENCRYPTION_KEY = Fernet.generate_key()
    log.warning(
        "KARI_JOB_ENC_KEY not set; generated ephemeral key for development." \
        " Provide a persistent key in production.",
    )

_fernet = Fernet(
    ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY
)


def set_encryption_key(key: bytes | str) -> None:
    """Inject a persistent Fernet key.

    This allows production deployments to supply a stable key from a
    dedicated secrets manager. The provided ``key`` must be a valid
    URL-safe base64 encoded 32-byte key as required by :class:`Fernet`.

    Args:
        key: The key to use for encryption/decryption.

    Raises:
        ValueError: If ``key`` is missing or invalid.
    """

    global _fernet, ENCRYPTION_KEY
    if not key:
        raise ValueError("Encryption key must be provided")
    key_bytes = key.encode() if isinstance(key, str) else key
    try:
        _fernet = Fernet(key_bytes)
    except Exception as exc:  # pragma: no cover - cryptography defines the exception
        raise ValueError("Invalid Fernet key") from exc
    ENCRYPTION_KEY = key_bytes


def encrypt_data(data: bytes | str) -> bytes:
    if isinstance(data, str):
        data = data.encode()
    return _fernet.encrypt(data)


def decrypt_data(token: bytes | memoryview | None) -> str | None:
    if token is None:
        return None
    if isinstance(token, memoryview):
        token = token.tobytes()
    return _fernet.decrypt(token).decode()

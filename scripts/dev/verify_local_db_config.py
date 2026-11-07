"""Fail-closed validation of the effective local Compose PostgreSQL identity.

Reads the rendered Compose JSON only from stdin. No credentials, URLs, Compose
payloads or database error bodies are ever printed. Does not connect to a DB,
run migrations, create identities, or install a second configuration owner.
"""
from __future__ import annotations

import json
import sys
from urllib.parse import unquote, urlsplit

URL_KEYS = ("DATABASE_URL", "POSTGRES_URL", "AUTH_DATABASE_URL")
DETAIL_KEYS = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")


class ConfigError(ValueError):
    """Safe error message without caller-provided values."""


def _identity(value: object, key: str) -> tuple[str, int, str, str, str]:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"Missing canonical {key}")
    try:
        parts = urlsplit(value)
        expected = "postgresql" if key == "DATABASE_URL" else "postgresql+asyncpg"
        if (
            parts.scheme != expected
            or not parts.hostname
            or parts.username is None
            or parts.password is None
            or not parts.path.startswith("/")
            or parts.path == "/"
            or parts.fragment
            or not (1 <= (parts.port or 5432) <= 65535)
        ):
            raise ConfigError(f"Invalid canonical {key} connection")
        host = parts.hostname.lower()
        if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0", "api", "postgres"}:
            raise ConfigError(f"Local-only {key} host is unreachable from the canonical API container")
        user = unquote(parts.username)
        password = unquote(parts.password)
        name = unquote(parts.path[1:])
        if not user or not password or not name or "/" in name:
            raise ConfigError(f"Incomplete canonical {key} connection")
        return (host, parts.port or 5432, user, password, name)
    except (ValueError, TypeError):
        raise ConfigError(f"Invalid canonical {key} connection") from None


def verify(config: object) -> None:
    if not isinstance(config, dict):
        raise ConfigError("Rendered Compose configuration must be an object")
    services = config.get("services")
    if not isinstance(services, dict):
        raise ConfigError("Rendered Compose services are missing")
    if set(("redis", "api", "web")) - services.keys():
        raise ConfigError("Canonical local Compose services are missing")
    if "postgres" in services or "postgres-copilot" in services:
        raise ConfigError("Local API Compose must not create a second database authority")
    api = services.get("api")
    if not isinstance(api, dict) or not isinstance(api.get("environment"), dict):
        raise ConfigError("Canonical API environment is missing")
    env = api["environment"]
    for key in DETAIL_KEYS:
        if not isinstance(env.get(key), str) or not env[key]:
            raise ConfigError(f"Missing canonical {key}")
    expected = _identity(env.get("DATABASE_URL"), "DATABASE_URL")
    if any(_identity(env.get(key), key) != expected for key in URL_KEYS[1:]):
        raise ConfigError("Canonical PostgreSQL connection identities differ")
    try:
        port = int(env["DB_PORT"])
    except ValueError:
        raise ConfigError("Invalid canonical DB_PORT") from None
    details = (
        env["DB_HOST"].lower(),
        port,
        env["DB_USER"],
        env["DB_PASSWORD"],
        env["DB_NAME"],
    )
    if details != expected:
        raise ConfigError("Canonical DB_* settings do not match database URLs")


def main() -> int:
    try:
        config = json.load(sys.stdin)
        verify(config)
    except (ConfigError, json.JSONDecodeError, UnicodeError, OSError):
        print("ERROR: Local Compose database identity is missing, inconsistent, or unsafe.", file=sys.stderr)
        return 1
    print("Canonical local Supabase PostgreSQL identity verified (connection not tested).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


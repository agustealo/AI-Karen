"""Canonical tenant-scoped persistence for nonsecret plugin configuration.

The manifest is authoritative for accepted keys. Sensitive fields require
Identity Vault integration and cannot enter this JSONB store or its audit.
No filesystem, in-memory fallback, background write, or auto-created schema.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator
from sqlalchemy import text

from ai_karen_engine.database.client import MultiTenantPostgresClient

_PLUGIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SECRET_TOKENS = (
    "password", "secret", "token", "credential", "apikey",
    "privatekey", "accesskey", "authkey", "bearer",
)
_SUPPORTED_TYPES = frozenset({"string", "integer", "number", "boolean"})
_MAX_SERIALIZED_SETTINGS = 16 * 1024


class PluginSettingsNotConfigured(ValueError):
    """No writable, manifest-declared settings contract exists."""


class PluginSettingsValidationError(ValueError):
    """A request violates the nonsecret manifest contract."""


class PluginSettingsRevisionConflict(RuntimeError):
    """Another persisted mutation changed the settings revision."""


@dataclass(frozen=True)
class PluginSettingsContract:
    """Validated manifest projection, without secret values or defaults."""

    fields: tuple[dict[str, Any], ...]
    rules: dict[str, dict[str, Any]]
    defaults: dict[str, Any]
    required: tuple[str, ...]

    def present(self, stored: Mapping[str, Any]) -> dict[str, Any]:
        """Never expose undeclared, sensitive, or read-only DB content."""
        return {
            **self.defaults,
            **{key: value for key, value in stored.items() if key in self.rules},
        }

    def validate(
        self, incoming: Mapping[str, Any], *, require_configured: bool = True
    ) -> dict[str, Any]:
        if not isinstance(incoming, dict):
            raise PluginSettingsValidationError("Plugin settings must be a JSON object")
        unknown = set(incoming) - set(self.rules)
        if unknown:
            raise PluginSettingsValidationError(
                "Undeclared, secret, or read-only plugin setting keys are forbidden"
            )
        candidate = {**self.defaults, **incoming}
        schema = {
            "type": "object",
            "properties": self.rules,
            "required": list(self.required) if require_configured else [],
            "additionalProperties": False,
        }
        try:
            Draft202012Validator.check_schema(schema)
            failure = next(iter(Draft202012Validator(schema).iter_errors(candidate)), None)
        except Exception as exc:
            raise PluginSettingsValidationError("Invalid plugin settings schema") from exc
        if failure is not None:
            # Never echo submitted values, especially from a forged sensitive key.
            raise PluginSettingsValidationError("Plugin settings failed manifest validation")
        try:
            serialized = json.dumps(incoming, allow_nan=False, separators=(",", ":"))
        except (ValueError, TypeError) as exc:
            raise PluginSettingsValidationError("Plugin settings must be finite JSON") from exc
        if len(serialized.encode("utf-8")) > _MAX_SERIALIZED_SETTINGS:
            raise PluginSettingsValidationError("Plugin settings exceed the 16 KiB limit")
        return dict(incoming)


class PluginSettingsRepository:
    """One transaction path for tenant-specific settings and value-free audit."""

    def __init__(
        self,
        client_factory: Callable[[], MultiTenantPostgresClient] = MultiTenantPostgresClient,
    ) -> None:
        self._client_factory = client_factory

    @staticmethod
    def _is_secret(key: str, definition: Mapping[str, Any]) -> bool:
        normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
        return (
            any(fragment in normalized for fragment in _SECRET_TOKENS)
            or bool(definition.get("writeOnly"))
            or bool(definition.get("x-secret"))
            or str(definition.get("format", "")).lower() in {"password", "secret", "token"}
        )

    @classmethod
    def contract(cls, manifest: Any) -> PluginSettingsContract:
        schema = getattr(manifest, "config_schema", None)
        if schema is None:
            raise PluginSettingsNotConfigured("Plugin has no declared settings schema")
        properties = getattr(schema, "properties", None)
        required = getattr(schema, "required", ()) or ()
        if not isinstance(properties, dict) or not properties:
            raise PluginSettingsNotConfigured("Plugin has no configurable settings")
        if len(properties) > 64:
            raise PluginSettingsNotConfigured("Plugin settings schema exceeds field limit")

        result: list[dict[str, Any]] = []
        rules: dict[str, dict[str, Any]] = {}
        defaults: dict[str, Any] = {}
        for key, raw_definition in properties.items():
            if not isinstance(key, str) or not _PLUGIN_ID.fullmatch(key):
                raise PluginSettingsNotConfigured("Invalid plugin settings field name")
            if not isinstance(raw_definition, dict):
                raise PluginSettingsNotConfigured("Invalid plugin settings field schema")
            definition = dict(raw_definition)
            secret = cls._is_secret(key, definition)
            dtype = definition.get("type")
            unsupported = dtype not in _SUPPORTED_TYPES
            read_only = bool(definition.get("readOnly")) or secret or unsupported
            field_type = (
                "password" if secret
                else "select" if isinstance(definition.get("enum"), list) and not unsupported
                else "number" if dtype in ("integer", "number")
                else dtype if dtype in ("boolean", "string")
                else "json"
            )
            field: dict[str, Any] = {
                "key": key,
                "label": str(definition.get("title") or key.replace("_", " ").replace("-", " ").title()),
                "type": field_type,
                "readOnly": read_only,
            }
            if definition.get("description"):
                field["description"] = str(definition["description"])
            if read_only:
                field["description"] = (
                    "Requires governed credential storage in Identity Vault"
                    if secret else "This setting is not writable through Plugin Settings"
                )
            else:
                normalized_rules = {
                    allowed: definition[allowed]
                    for allowed in (
                        "type", "enum", "minimum", "maximum", "minLength",
                        "maxLength", "pattern", "multipleOf",
                    )
                    if allowed in definition
                }
                rules[key] = normalized_rules
                if "default" in definition:
                    defaults[key] = definition["default"]
                    field["defaultValue"] = definition["default"]
                validation: dict[str, Any] = {}
                for standard, ui in (
                    ("minimum", "min"), ("maximum", "max"),
                    ("minLength", "minLength"), ("maxLength", "maxLength"),
                    ("pattern", "pattern"),
                ):
                    if standard in definition:
                        validation[ui] = definition[standard]
                if validation:
                    field["validation"] = validation
                if field_type == "select":
                    field["options"] = [
                        {"value": str(value), "label": str(value)}
                        for value in definition["enum"]
                    ]
            result.append(field)
        return PluginSettingsContract(
            fields=tuple(result),
            rules=rules,
            defaults=defaults,
            required=tuple(str(key) for key in required if key in rules),
        )

    @staticmethod
    def _tenant(tenant_id: str) -> str:
        try:
            return str(uuid.UUID(str(tenant_id)))
        except (ValueError, AttributeError, TypeError) as exc:
            raise PluginSettingsValidationError("Valid tenant scope is required") from exc

    @staticmethod
    async def _scope(session: Any, tenant_id: str) -> None:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )

    async def get(self, tenant_id: str, plugin_id: str) -> dict[str, Any]:
        tenant = self._tenant(tenant_id)
        async with self._client_factory().get_async_session() as session:
            await self._scope(session, tenant)
            result = await session.execute(
                text(
                    "SELECT settings, revision FROM public.extension_plugin_settings "
                    "WHERE tenant_id = CAST(:tenant_id AS uuid) AND plugin_id = :plugin_id"
                ),
                {"tenant_id": tenant, "plugin_id": plugin_id},
            )
            row = result.mappings().one_or_none()
            return (
                {"settings": dict(row["settings"]), "revision": int(row["revision"])}
                if row else {"settings": {}, "revision": 0}
            )

    async def list_tenant(self, tenant_id: str) -> dict[str, dict[str, Any]]:
        tenant = self._tenant(tenant_id)
        async with self._client_factory().get_async_session() as session:
            await self._scope(session, tenant)
            rows = await session.execute(
                text(
                    "SELECT plugin_id, settings, revision FROM public.extension_plugin_settings "
                    "WHERE tenant_id = CAST(:tenant_id AS uuid)"
                ),
                {"tenant_id": tenant},
            )
            return {
                str(row["plugin_id"]): {
                    "settings": dict(row["settings"]),
                    "revision": int(row["revision"]),
                }
                for row in rows.mappings().all()
            }

    async def write(
        self,
        *,
        tenant_id: str,
        plugin_id: str,
        actor_user_id: str,
        operation: str,
        settings: dict[str, Any],
        expected_revision: int,
        request_id: str,
        correlation_id: str,
    ) -> int:
        tenant = self._tenant(tenant_id)
        if not _PLUGIN_ID.fullmatch(plugin_id):
            raise PluginSettingsValidationError("Invalid plugin identifier")
        if operation not in ("save", "reset") or expected_revision < 0:
            raise PluginSettingsValidationError("Invalid settings mutation")
        if not actor_user_id or len(str(actor_user_id)) > 255:
            raise PluginSettingsValidationError("Authenticated actor is required")
        if not request_id or not correlation_id or len(request_id) > 128 or len(correlation_id) > 128:
            raise PluginSettingsValidationError("Valid request correlation is required")
        encoded = json.dumps(settings, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _MAX_SERIALIZED_SETTINGS:
            raise PluginSettingsValidationError("Plugin settings exceed the 16 KiB limit")

        parameters = {
            "tenant_id": tenant,
            "plugin_id": plugin_id,
            "actor": str(actor_user_id),
            "settings": encoded,
            "revision": expected_revision,
        }
        async with self._client_factory().get_async_session() as session:
            await self._scope(session, tenant)
            if expected_revision == 0:
                change = await session.execute(
                    text(
                        "INSERT INTO public.extension_plugin_settings "
                        "(tenant_id, plugin_id, settings, revision, updated_by) "
                        "VALUES (CAST(:tenant_id AS uuid), :plugin_id, "
                        "CAST(:settings AS jsonb), 1, :actor) "
                        "ON CONFLICT (tenant_id, plugin_id) DO NOTHING "
                        "RETURNING revision"
                    ),
                    parameters,
                )
            else:
                change = await session.execute(
                    text(
                        "UPDATE public.extension_plugin_settings "
                        "SET settings = CAST(:settings AS jsonb), "
                        "revision = revision + 1, updated_by = :actor, "
                        "updated_at = clock_timestamp() "
                        "WHERE tenant_id = CAST(:tenant_id AS uuid) "
                        "AND plugin_id = :plugin_id AND revision = :revision "
                        "RETURNING revision"
                    ),
                    parameters,
                )
            updated = change.scalar_one_or_none()
            if updated is None:
                raise PluginSettingsRevisionConflict(
                    "Plugin settings changed; refresh before saving"
                )
            await session.execute(
                text(
                    "INSERT INTO public.extension_plugin_settings_audit "
                    "(tenant_id, plugin_id, actor_user_id, operation, revision, "
                    "request_id, correlation_id) "
                    "VALUES (CAST(:tenant_id AS uuid), :plugin_id, :actor, "
                    ":operation, :new_revision, :request_id, :correlation_id)"
                ),
                {
                    "tenant_id": tenant,
                    "plugin_id": plugin_id,
                    "actor": str(actor_user_id),
                    "operation": operation,
                    "new_revision": int(updated),
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                },
            )
            # The canonical context manager commits. Any audit failure rolls
            # back the setting mutation in the same database transaction.
            return int(updated)


__all__ = [
    "PluginSettingsContract",
    "PluginSettingsNotConfigured",
    "PluginSettingsRepository",
    "PluginSettingsRevisionConflict",
    "PluginSettingsValidationError",
]

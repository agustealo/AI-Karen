from __future__ import annotations

import uuid
from pathlib import Path

from ai_karen_engine.database.identity_vault_schema import (
    AccountSession,
    AuthGrant,
    Credential,
    CredentialAuditEvent,
    CredentialBinding,
    CredentialSecret,
    ExternalAccount,
    LoginAttempt,
    ProviderDefinition,
    TokenLease,
)
from ai_karen_engine.database.models.identity_vault import (
    AccountSessionCreate,
    CredentialAuditEventCreate,
    CredentialCreate,
    CredentialSecretCreate,
)
from ai_karen_engine.services.identity_vault.credential_vault_service import CredentialVaultService


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src/ai_karen_engine/services/identity_vault/credential_vault_service.py"
SCHEMA = ROOT / "src/ai_karen_engine/database/identity_vault_schema.py"
DTO = ROOT / "src/ai_karen_engine/database/models/identity_vault.py"
MIGRATION = ROOT / "supabase/migrations/20260827080000_08_identity_vault_tenant_scope.sql"

TENANT_MODELS = (
    ProviderDefinition,
    CredentialSecret,
    Credential,
    ExternalAccount,
    CredentialBinding,
    AccountSession,
    AuthGrant,
    TokenLease,
    LoginAttempt,
    CredentialAuditEvent,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _class_block(text: str, class_name: str) -> str:
    marker = f"class {class_name}(Base):"
    start = text.index(marker)
    end = text.find("\nclass ", start + len(marker))
    return text[start:] if end == -1 else text[start:end]


def test_identity_vault_dto_authority_is_importable_and_persistence_free() -> None:
    text = _read(DTO)
    assert "Base.metadata" not in text
    credential = CredentialCreate(
        name="local",
        provider_id=uuid.uuid4(),
        credential_type="api_key",
        metadata={"purpose": "test"},
    )
    secret = CredentialSecretCreate(secret_type="api_key", encrypted_value="secret", metadata={"k": "v"})
    session = AccountSessionCreate(
        credential_id=uuid.uuid4(),
        external_account_id=uuid.uuid4(),
        session_token="session-token",
        token_type="session",
        metadata={"device": "test"},
    )
    event = CredentialAuditEventCreate(
        event_type="created",
        action="provider_creation",
        resource_type="provider",
        metadata={"source": "test"},
    )
    assert credential.credential_metadata == {"purpose": "test"}
    assert secret.secret_metadata == {"k": "v"}
    assert session.session_metadata == {"device": "test"}
    assert event.credential_id is None


def test_every_identity_vault_aggregate_has_tenant_ownership() -> None:
    schema = _read(SCHEMA)
    for model in TENANT_MODELS:
        block = _class_block(schema, model.__name__)
        assert "tenant_id = Column(" in block, model.__name__


def test_canonical_tenant_query_adds_tenant_predicate_for_every_aggregate() -> None:
    tenant_id = uuid.uuid4()
    for model in TENANT_MODELS:
        statement = CredentialVaultService._tenant_query(model, tenant_id)
        sql = str(statement)
        assert f"{model.__tablename__}.tenant_id" in sql, model.__name__
        assert tenant_id in statement.compile().params.values(), model.__name__


def test_runtime_requires_tenant_and_validates_related_ownership() -> None:
    text = _read(SERVICE)
    assert "tenant_id: Optional[uuid.UUID] = None" not in text
    assert "model.tenant_id == tenant_id" in text
    assert "Credential and account must belong to the tenant" in text
    assert "Credential and provider must belong to the tenant" in text
    assert "Provider not found in tenant" in text
    assert "tenant_id=tenant_id" in text


def test_runtime_uses_canonical_encryption_and_same_session_audit() -> None:
    text = _read(SERVICE)
    assert "from ai_karen_engine.core.security.encryption_utils import decrypt_data, encrypt_data" in text
    assert "hmac.new" not in text
    assert "_audit(\n        self,\n        session: AsyncSession" in text
    assert "audit_metadata=safe_metadata" in text


def test_forward_migration_quarantines_unowned_rows() -> None:
    text = _read(MIGRATION)
    for table in (
        "identity_providers",
        "credentials",
        "credential_secrets",
        "external_accounts",
        "credential_bindings",
        "account_sessions",
        "auth_grants",
        "token_leases",
        "login_attempts",
    ):
        assert f"'{table}'" in text
    assert "ADD COLUMN IF NOT EXISTS tenant_id UUID" in text
    assert "WHERE tenant_id IS NULL" in text
    assert "ALTER COLUMN tenant_id SET NOT NULL" in text
    assert "UPDATE" not in text.upper()


def test_provider_account_and_primary_binding_uniqueness_are_tenant_local() -> None:
    migration = _read(MIGRATION)
    schema = _read(SCHEMA)
    assert "uq_identity_providers_tenant_provider" in migration
    assert "uq_external_accounts_tenant_provider_identifier" in migration
    assert "uq_credential_bindings_primary_per_account" in migration
    assert "WHERE is_primary IS TRUE AND is_active IS TRUE" in migration
    provider_line = _class_block(schema, "ProviderDefinition").split("provider_id", 1)[1].split("\n", 1)[0]
    assert "unique=True" not in provider_line
    assert 'UniqueConstraint("tenant_id", "provider_id", "account_identifier"' in _class_block(
        schema, "ExternalAccount"
    )
    assert "uq_external_account_primary" not in _class_block(schema, "CredentialBinding")


def test_audit_events_do_not_require_unrelated_credential() -> None:
    migration = _read(MIGRATION)
    schema = _class_block(_read(SCHEMA), "CredentialAuditEvent")
    assert "ALTER TABLE credential_audit_events ALTER COLUMN credential_id DROP NOT NULL" in migration
    assert "credential_id = Column(" in schema
    credential_line = schema.split("credential_id = Column(", 1)[1].split("\n", 1)[0]
    assert "nullable=True" in credential_line

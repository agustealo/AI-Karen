from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src/ai_karen_engine/services/identity_vault/credential_vault_service.py"
SCHEMA = ROOT / "src/ai_karen_engine/database/identity_vault_schema.py"
DTO = ROOT / "src/ai_karen_engine/database/models/identity_vault.py"
MIGRATION = ROOT / "supabase/migrations/20260827080000_08_identity_vault_tenant_scope.sql"

TENANT_MODELS = (
    "ProviderDefinition",
    "CredentialSecret",
    "Credential",
    "ExternalAccount",
    "CredentialBinding",
    "AccountSession",
    "AuthGrant",
    "TokenLease",
    "LoginAttempt",
    "CredentialAuditEvent",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _class_block(text: str, class_name: str) -> str:
    marker = f"class {class_name}(Base):"
    start = text.index(marker)
    end = text.find("\nclass ", start + len(marker))
    return text[start:] if end == -1 else text[start:end]


def test_identity_vault_dto_authority_is_persistence_free_and_complete() -> None:
    text = _read(DTO)
    assert "Base.metadata" not in text
    assert "sqlalchemy" not in text.lower()
    for name in (
        "ProviderDefinitionCreate",
        "CredentialCreate",
        "CredentialSecretCreate",
        "ExternalAccountCreate",
        "CredentialBindingCreate",
        "AccountSessionCreate",
        "AuthGrantCreate",
        "TokenLeaseCreate",
        "LoginAttemptCreate",
        "CredentialAuditEventCreate",
        "CredentialHealthStatus",
        "TokenRotationResult",
    ):
        assert f"class {name}" in text, name
    assert 'alias="metadata"' in text
    assert "credential_id: Optional[uuid.UUID] = None" in text


def test_every_identity_vault_aggregate_has_tenant_ownership() -> None:
    schema = _read(SCHEMA)
    for model in TENANT_MODELS:
        block = _class_block(schema, model)
        assert "tenant_id = Column(" in block, model


def test_canonical_runtime_has_one_query_constructor_and_it_is_tenant_scoped() -> None:
    text = _read(SERVICE)
    assert text.count("select(") == 1
    assert "return select(model).where(model.tenant_id == tenant_id)" in text
    assert "tenant_id: Optional[uuid.UUID] = None" not in text
    assert "if tenant_id is None:" in text
    assert "raise ValueError(\"tenant_id is required\")" in text


def test_relationship_writes_validate_tenant_ownership() -> None:
    text = _read(SERVICE)
    assert "Credential and account must belong to the tenant" in text
    assert "Credential and provider must belong to the tenant" in text
    assert "Provider not found in tenant" in text
    assert "Account not found in tenant" in text
    assert "Credential not found in tenant" in text
    assert "tenant_id=tenant_id" in text


def test_runtime_encrypts_secrets_hashes_bearer_tokens_and_uses_same_session_audit() -> None:
    text = _read(SERVICE)
    assert "from ai_karen_engine.core.security.encryption_utils import encrypt_data" in text
    assert "hmac.new" not in text
    assert "def _token_digest" in text
    assert "hashlib.sha256(value.encode" in text
    assert "session_token=self._token_digest(session_data.session_token)" in text
    assert "lease_token=self._token_digest(lease_data.lease_token)" in text
    assert "_audit(\n        self,\n        session: AsyncSession" in text
    assert "audit_metadata=safe_metadata" in text
    assert "***REDACTED***" in text


def test_provider_token_refresh_is_never_synthesized() -> None:
    text = _read(SERVICE)
    assert "token_urlsafe" not in text
    assert "Identity Vault will not synthesize provider tokens" in text
    assert "OAuth token refresh requires a governed provider adapter" in text


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


def test_database_enforces_tenant_consistent_relationships() -> None:
    text = _read(MIGRATION)
    for constraint in (
        "fk_credentials_tenant_provider",
        "fk_credential_secrets_tenant_credential",
        "fk_external_accounts_tenant_provider",
        "fk_credential_bindings_tenant_credential",
        "fk_credential_bindings_tenant_account",
        "fk_account_sessions_tenant_credential",
        "fk_account_sessions_tenant_account",
        "fk_auth_grants_tenant_credential",
        "fk_auth_grants_tenant_provider",
        "fk_token_leases_tenant_credential",
        "fk_login_attempts_tenant_credential",
        "fk_login_attempts_tenant_account",
        "fk_credential_audit_tenant_credential",
        "fk_credential_audit_tenant_account",
        "fk_credential_audit_tenant_provider",
    ):
        assert constraint in text, constraint
    assert "FOREIGN KEY (tenant_id, credential_id)" in text
    assert "FOREIGN KEY (tenant_id, provider_id)" in text
    assert "FOREIGN KEY (tenant_id, external_account_id)" in text


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
    credential_line = schema.split("credential_id = Column(", 1)[1].split("\n", 1)[0]
    assert "nullable=True" in credential_line

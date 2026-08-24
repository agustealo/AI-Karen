"""
Identity Vault API Routes.

This module provides FastAPI routes for the identity vault system including
credential management, OAuth flows, account binding, and audit logging.
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Security
from fastapi.responses import JSONResponse
from sqlalchemy import select

from ai_karen_engine.core.security import get_current_user, get_tenant_id
from ai_karen_engine.services.identity_vault.credential_vault_service import CredentialVaultService
from ai_karen_engine.database.models.identity_vault import (
    ProviderDefinitionCreate,
    ProviderDefinitionUpdate,
    CredentialCreate,
    CredentialUpdate,
    ExternalAccountCreate,
    ExternalAccountUpdate,
    CredentialBindingCreate,
    AccountSessionCreate,
    AuthGrantCreate,
    TokenLeaseCreate,
    LoginAttemptCreate,
    CredentialAuditEventCreate,
    ProviderDefinition,
    Credential,
    ExternalAccount,
    CredentialBinding,
    AccountSession,
    AuthGrant,
    TokenLease,
    LoginAttempt,
    CredentialAuditEvent,
    CredentialResponse,
    ExternalAccountResponse,
    AccountCapabilityDiscovery,
    TokenRotationResult,
    CredentialHealthStatus,
)
from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/identity-vault", tags=["identity-vault"])


# Dependency to get the credential vault service
def get_credential_vault_service() -> CredentialVaultService:
    """Get the credential vault service instance."""
    # In a real implementation, this would be injected via dependency injection
    # For now, we'll create a new instance
    return CredentialVaultService()


# Provider Management Routes
@router.post("/providers", response_model=ProviderDefinition)
async def create_provider(
    provider_data: ProviderDefinitionCreate,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Create a new provider definition."""
    try:
        await service.initialize()
        provider = await service.create_provider(
            provider_data=provider_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return provider
    except Exception as e:
        logger.error(f"Failed to create provider: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/providers/{provider_id}", response_model=ProviderDefinition)
async def get_provider(
    provider_id: str,
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get a provider definition by ID."""
    try:
        await service.initialize()
        provider = await service.get_provider(provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        return provider
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get provider: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/providers", response_model=List[ProviderDefinition])
async def list_providers(
    enabled_only: bool = Query(False, description="Only return enabled providers"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of providers to return"),
    offset: int = Query(0, ge=0, description="Number of providers to skip"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """List provider definitions."""
    try:
        await service.initialize()
        providers = await service.list_providers(
            tenant_id=tenant_id,
            enabled_only=enabled_only,
            limit=limit,
            offset=offset,
        )
        return providers
    except Exception as e:
        logger.error(f"Failed to list providers: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/providers/{provider_id}", response_model=ProviderDefinition)
async def update_provider(
    provider_id: str,
    update_data: ProviderDefinitionUpdate,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Update a provider definition."""
    try:
        await service.initialize()
        provider = await service.update_provider(
            provider_id=provider_id,
            update_data=update_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        return provider
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update provider: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: str,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Delete a provider definition."""
    try:
        await service.initialize()
        success = await service.delete_provider(
            provider_id=provider_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Provider not found or cannot be deleted")
        return {"message": "Provider deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete provider: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Credential Management Routes
@router.post("/credentials", response_model=Credential)
async def create_credential(
    credential_data: CredentialCreate,
    secrets: List[CredentialSecretCreate],
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Create a new credential with encrypted secrets."""
    try:
        await service.initialize()
        credential = await service.create_credential(
            credential_data=credential_data,
            secrets=secrets,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return credential
    except Exception as e:
        logger.error(f"Failed to create credential: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/credentials/{credential_id}", response_model=Credential)
async def get_credential(
    credential_id: uuid.UUID,
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get a credential by ID."""
    try:
        await service.initialize()
        credential = await service.get_credential(credential_id)
        if not credential:
            raise HTTPException(status_code=404, detail="Credential not found")
        return credential
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get credential: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/credentials", response_model=List[Credential])
async def list_credentials(
    provider_id: Optional[str] = Query(None, description="Filter by provider ID"),
    status: Optional[CredentialStatus] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of credentials to return"),
    offset: int = Query(0, ge=0, description="Number of credentials to skip"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """List credentials."""
    try:
        await service.initialize()
        credentials = await service.list_credentials(
            tenant_id=tenant_id,
            provider_id=provider_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return credentials
    except Exception as e:
        logger.error(f"Failed to list credentials: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/credentials/{credential_id}", response_model=Credential)
async def update_credential(
    credential_id: uuid.UUID,
    update_data: CredentialUpdate,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Update a credential."""
    try:
        await service.initialize()
        credential = await service.update_credential(
            credential_id=credential_id,
            update_data=update_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not credential:
            raise HTTPException(status_code=404, detail="Credential not found")
        return credential
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update credential: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/credentials/{credential_id}")
async def delete_credential(
    credential_id: uuid.UUID,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Delete a credential."""
    try:
        await service.initialize()
        success = await service.delete_credential(
            credential_id=credential_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Credential not found or has active bindings")
        return {"message": "Credential deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete credential: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/credentials/{credential_id}/rotate", response_model=TokenRotationResult)
async def rotate_credential(
    credential_id: uuid.UUID,
    new_secrets: List[CredentialSecretCreate],
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Rotate credential secrets."""
    try:
        await service.initialize()
        result = await service.rotate_credential(
            credential_id=credential_id,
            new_secrets=new_secrets,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Credential not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rotate credential: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/credentials/{credential_id}/revoke")
async def revoke_credential(
    credential_id: uuid.UUID,
    reason: Optional[str] = Query(None, description="Reason for revocation"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Revoke a credential."""
    try:
        await service.initialize()
        success = await service.revoke_credential(
            credential_id=credential_id,
            tenant_id=tenant_id,
            user_id=user_id,
            reason=reason,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Credential not found")
        return {"message": "Credential revoked successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke credential: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Account Management Routes
@router.post("/accounts", response_model=ExternalAccount)
async def create_external_account(
    account_data: ExternalAccountCreate,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Create an external account."""
    try:
        await service.initialize()
        account = await service.create_external_account(
            account_data=account_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return account
    except Exception as e:
        logger.error(f"Failed to create external account: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/accounts/{account_id}", response_model=ExternalAccount)
async def get_external_account(
    account_id: uuid.UUID,
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get an external account by ID."""
    try:
        await service.initialize()
        account = await service.get_external_account(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return account
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get external account: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/accounts", response_model=List[ExternalAccount])
async def list_external_accounts(
    provider_id: Optional[str] = Query(None, description="Filter by provider ID"),
    account_identifier: Optional[str] = Query(None, description="Filter by account identifier"),
    active_only: bool = Query(False, description="Only return active accounts"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of accounts to return"),
    offset: int = Query(0, ge=0, description="Number of accounts to skip"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """List external accounts."""
    try:
        await service.initialize()
        accounts = await service.list_external_accounts(
            tenant_id=tenant_id,
            provider_id=provider_id,
            account_identifier=account_identifier,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )
        return accounts
    except Exception as e:
        logger.error(f"Failed to list external accounts: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/accounts/{account_id}", response_model=ExternalAccount)
async def update_external_account(
    account_id: uuid.UUID,
    update_data: ExternalAccountUpdate,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Update an external account."""
    try:
        await service.initialize()
        account = await service.update_external_account(
            account_id=account_id,
            update_data=update_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return account
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update external account: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/accounts/{account_id}")
async def delete_external_account(
    account_id: uuid.UUID,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Delete an external account."""
    try:
        await service.initialize()
        success = await service.delete_external_account(
            account_id=account_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Account not found or has active bindings")
        return {"message": "Account deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete external account: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Binding Management Routes
@router.post("/bindings", response_model=CredentialBinding)
async def create_binding(
    binding_data: CredentialBindingCreate,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Create a credential binding."""
    try:
        await service.initialize()
        binding = await service.create_binding(
            binding_data=binding_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return binding
    except Exception as e:
        logger.error(f"Failed to create binding: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/bindings/{binding_id}", response_model=CredentialBinding)
async def get_binding(
    binding_id: uuid.UUID,
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get a credential binding by ID."""
    try:
        await service.initialize()
        binding = await service.get_binding(binding_id)
        if not binding:
            raise HTTPException(status_code=404, detail="Binding not found")
        return binding
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get binding: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/bindings", response_model=List[CredentialBinding])
async def list_bindings(
    credential_id: Optional[uuid.UUID] = Query(None, description="Filter by credential ID"),
    external_account_id: Optional[uuid.UUID] = Query(None, description="Filter by external account ID"),
    active_only: bool = Query(False, description="Only return active bindings"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of bindings to return"),
    offset: int = Query(0, ge=0, description="Number of bindings to skip"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """List credential bindings."""
    try:
        await service.initialize()
        bindings = await service.list_bindings(
            tenant_id=tenant_id,
            credential_id=credential_id,
            external_account_id=external_account_id,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )
        return bindings
    except Exception as e:
        logger.error(f"Failed to list bindings: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/bindings/{binding_id}", response_model=CredentialBinding)
async def update_binding(
    binding_id: uuid.UUID,
    is_primary: Optional[bool] = Query(None, description="Whether this is the primary binding"),
    binding_metadata: Optional[dict] = Query(None, description="Additional binding metadata"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Update a credential binding."""
    try:
        await service.initialize()
        binding = await service.update_binding(
            binding_id=binding_id,
            is_primary=is_primary,
            binding_metadata=binding_metadata,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not binding:
            raise HTTPException(status_code=404, detail="Binding not found")
        return binding
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update binding: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/bindings/{binding_id}")
async def delete_binding(
    binding_id: uuid.UUID,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Delete a credential binding."""
    try:
        await service.initialize()
        success = await service.delete_binding(
            binding_id=binding_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Binding not found")
        return {"message": "Binding deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete binding: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# OAuth Management Routes
@router.post("/oauth/grants", response_model=AuthGrant)
async def create_oauth_grant(
    grant_data: AuthGrantCreate,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Create an OAuth authorization grant."""
    try:
        await service.initialize()
        grant = await service.create_oauth_grant(
            grant_data=grant_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return grant
    except Exception as e:
        logger.error(f"Failed to create OAuth grant: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/oauth/grants/{grant_id}/complete")
async def complete_oauth_grant(
    grant_id: uuid.UUID,
    access_token: str,
    refresh_token: Optional[str] = None,
    scopes: Optional[List[str]] = None,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Complete an OAuth authorization grant."""
    try:
        await service.initialize()
        grant = await service.complete_oauth_grant(
            grant_id=grant_id,
            access_token=access_token,
            refresh_token=refresh_token,
            scopes=scopes,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not grant:
            raise HTTPException(status_code=404, detail="Grant not found")
        return grant
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to complete OAuth grant: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/oauth/refresh")
async def refresh_oauth_token(
    credential_id: uuid.UUID,
    refresh_token: str,
    new_scopes: Optional[List[str]] = None,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Refresh an OAuth token."""
    try:
        await service.initialize()
        result = await service.refresh_oauth_token(
            credential_id=credential_id,
            refresh_token=refresh_token,
            new_scopes=new_scopes,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not result:
            raise HTTPException(status_code=400, detail="Token refresh failed")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to refresh OAuth token: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Session Management Routes
@router.post("/sessions", response_model=AccountSession)
async def create_account_session(
    session_data: AccountSessionCreate,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Create an account session."""
    try:
        await service.initialize()
        session = await service.create_account_session(
            session_data=session_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return session
    except Exception as e:
        logger.error(f"Failed to create account session: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/{session_id}", response_model=AccountSession)
async def get_account_session(
    session_id: uuid.UUID,
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get an account session by ID."""
    try:
        await service.initialize()
        session = await service.get_account_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get account session: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions", response_model=List[AccountSession])
async def list_account_sessions(
    credential_id: Optional[uuid.UUID] = Query(None, description="Filter by credential ID"),
    external_account_id: Optional[uuid.UUID] = Query(None, description="Filter by external account ID"),
    active_only: bool = Query(False, description="Only return active sessions"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of sessions to return"),
    offset: int = Query(0, ge=0, description="Number of sessions to skip"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """List account sessions."""
    try:
        await service.initialize()
        sessions = await service.list_account_sessions(
            tenant_id=tenant_id,
            credential_id=credential_id,
            external_account_id=external_account_id,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )
        return sessions
    except Exception as e:
        logger.error(f"Failed to list account sessions: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/invalidate")
async def invalidate_account_session(
    session_id: uuid.UUID,
    reason: Optional[str] = Query(None, description="Reason for invalidation"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Invalidate an account session."""
    try:
        await service.initialize()
        success = await service.invalidate_account_session(
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            reason=reason,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"message": "Session invalidated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to invalidate account session: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Login Management Routes
@router.post("/login-attempts", response_model=LoginAttempt)
async def record_login_attempt(
    attempt_data: LoginAttemptCreate,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Record a login attempt."""
    try:
        await service.initialize()
        attempt = await service.record_login_attempt(
            attempt_data=attempt_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return attempt
    except Exception as e:
        logger.error(f"Failed to record login attempt: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Token Lease Management Routes
@router.post("/leases", response_model=TokenLease)
async def create_token_lease(
    lease_data: TokenLeaseCreate,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Create a token lease."""
    try:
        await service.initialize()
        lease = await service.create_token_lease(
            lease_data=lease_data,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return lease
    except Exception as e:
        logger.error(f"Failed to create token lease: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/leases/{lease_token}", response_model=TokenLease)
async def get_token_lease(
    lease_token: str,
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get a token lease by lease token."""
    try:
        await service.initialize()
        lease = await service.get_token_lease(lease_token)
        if not lease:
            raise HTTPException(status_code=404, detail="Lease not found")
        return lease
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get token lease: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/leases/{lease_token}/invalidate")
async def invalidate_token_lease(
    lease_token: str,
    reason: Optional[str] = Query(None, description="Reason for invalidation"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Invalidate a token lease."""
    try:
        await service.initialize()
        success = await service.invalidate_token_lease(
            lease_token=lease_token,
            tenant_id=tenant_id,
            user_id=user_id,
            reason=reason,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Lease not found")
        return {"message": "Lease invalidated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to invalidate token lease: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Capability Discovery Routes
@router.post("/accounts/{account_id}/discover-capabilities", response_model=AccountCapabilityDiscovery)
async def discover_account_capabilities(
    account_id: uuid.UUID,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    user_id: str = Security(get_current_user),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Discover capabilities for an external account."""
    try:
        await service.initialize()
        discovery = await service.discover_account_capabilities(
            account_id=account_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not discovery:
            raise HTTPException(status_code=404, detail="Account not found")
        return discovery
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to discover account capabilities: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Health Monitoring Routes
@router.get("/credentials/{credential_id}/health", response_model=CredentialHealthStatus)
async def get_credential_health(
    credential_id: uuid.UUID,
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get health status for a credential."""
    try:
        await service.initialize()
        health = await service.get_credential_health(credential_id)
        if not health:
            raise HTTPException(status_code=404, detail="Credential not found")
        return health
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get credential health: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/credentials/attention-needed", response_model=List[CredentialHealthStatus])
async def get_credentials_needing_attention(
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of credentials to return"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """List credentials that need attention."""
    try:
        await service.initialize()
        health_statuses = await service.list_credentials_needing_attention(
            tenant_id=tenant_id,
            limit=limit,
        )
        return health_statuses
    except Exception as e:
        logger.error(f"Failed to get credentials needing attention: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Audit Routes
@router.get("/audit/events", response_model=List[CredentialAuditEvent])
async def get_audit_events(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    credential_id: Optional[uuid.UUID] = Query(None, description="Filter by credential ID"),
    account_id: Optional[uuid.UUID] = Query(None, description="Filter by account ID"),
    event_type: Optional[AuditEventType] = Query(None, description="Filter by event type"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of events to return"),
    offset: int = Query(0, ge=0, description="Number of events to skip"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get audit events."""
    try:
        await service.initialize()
        events = await service.get_audit_events(
            tenant_id=tenant_id,
            user_id=user_id,
            credential_id=credential_id,
            account_id=account_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
        return events
    except Exception as e:
        logger.error(f"Failed to get audit events: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/audit/correlation/{correlation_id}", response_model=List[CredentialAuditEvent])
async def get_audit_events_by_correlation(
    correlation_id: str,
    tenant_id: uuid.UUID = Security(get_tenant_id),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get audit events by correlation ID."""
    try:
        await service.initialize()
        events = await service.get_audit_events_by_correlation_id(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
        )
        return events
    except Exception as e:
        logger.error(f"Failed to get audit events by correlation ID: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Utility Routes
@router.get("/credentials/{credential_id}/bindings", response_model=List[CredentialBinding])
async def get_credential_bindings(
    credential_id: uuid.UUID,
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get all bindings for a credential."""
    try:
        await service.initialize()
        bindings = await service.get_credential_bindings(credential_id)
        return bindings
    except Exception as e:
        logger.error(f"Failed to get credential bindings: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/accounts/{account_id}/bindings", response_model=List[CredentialBinding])
async def get_external_account_bindings(
    account_id: uuid.UUID,
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get all bindings for an external account."""
    try:
        await service.initialize()
        bindings = await service.get_external_account_bindings(account_id)
        return bindings
    except Exception as e:
        logger.error(f"Failed to get external account bindings: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Legacy Routes for Compatibility
@router.get("/providers/{provider_id}/credentials", response_model=List[Credential])
async def get_provider_credentials(
    provider_id: str,
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of credentials to return"),
    offset: int = Query(0, ge=0, description="Number of credentials to skip"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get all credentials for a provider (legacy route)."""
    try:
        await service.initialize()
        credentials = await service.list_credentials(
            tenant_id=tenant_id,
            provider_id=provider_id,
            limit=limit,
            offset=offset,
        )
        return credentials
    except Exception as e:
        logger.error(f"Failed to get provider credentials: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/accounts/{account_id}/sessions", response_model=List[AccountSession])
async def get_account_sessions(
    account_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of sessions to return"),
    offset: int = Query(0, ge=0, description="Number of sessions to skip"),
    tenant_id: uuid.UUID = Security(get_tenant_id),
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Get all sessions for an account (legacy route)."""
    try:
        await service.initialize()
        sessions = await service.list_account_sessions(
            tenant_id=tenant_id,
            external_account_id=account_id,
            limit=limit,
            offset=offset,
        )
        return sessions
    except Exception as e:
        logger.error(f"Failed to get account sessions: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# Health Check Route
@router.get("/health")
async def health_check(
    service: CredentialVaultService = Depends(get_credential_vault_service),
):
    """Health check endpoint."""
    try:
        await service.initialize()
        return {"status": "healthy", "service": "identity_vault"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )
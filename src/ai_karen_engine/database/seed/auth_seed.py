"""Seed data for authentication tables."""

# mypy: ignore-errors

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from ai_karen_engine.database.models import AuthProvider, AuthUser, Tenant

DEFAULT_ADMIN_PASSWORD_HASH = (
    "$2b$12$1BVzKwS0wvU6FzcjiiVNhO2On8T1hLz1o4FLXnn78M6MDDJNZ99DS"
)

DEFAULT_ADMINS = [
    ("admin@kari.ai", "Admin User", "default"),
    ("admin@karen.ai", "Zeus Eternal", "ee6b1597-0504-4b06-847a-f84283d76182"),
]


def _resolve_tenant_id(session: Session, tenant_identifier: str) -> uuid.UUID:
    """Resolve a tenant identifier to a real UUID, creating the default tenant if needed."""
    try:
        return uuid.UUID(str(tenant_identifier))
    except (TypeError, ValueError):
        if tenant_identifier != "default":
            default_tenant = session.query(Tenant).filter_by(slug="default").first()
            if default_tenant:
                return default_tenant.id
            raise

    default_tenant = session.query(Tenant).filter_by(slug="default").first()
    if default_tenant:
        return default_tenant.id

    default_tenant = Tenant(
        name="Default Tenant",
        slug="default",
        subscription_tier="basic",
    )
    session.add(default_tenant)
    session.flush()
    return default_tenant.id


def seed_default_auth(session: Session) -> None:
    """Insert default auth provider and admin users if missing."""
    if not session.query(AuthProvider).filter_by(provider_id="local").first():
        provider = AuthProvider(
            provider_id="local",
            type="local",
            config={},
            metadata={},
        )
        session.add(provider)

    for email, full_name, tenant_id in DEFAULT_ADMINS:
        admin = session.query(AuthUser).filter_by(email=email).first()

        if not admin:
            admin = AuthUser(
                user_id=str(uuid.uuid4()),
                email=email,
                created_at=datetime.utcnow(),
            )
            session.add(admin)

        resolved_tenant_id = _resolve_tenant_id(session, tenant_id)
        admin.full_name = admin.full_name or full_name
        admin.password_hash = DEFAULT_ADMIN_PASSWORD_HASH
        admin.is_active = True
        admin.is_verified = True
        admin.roles = ["admin", "user"]
        admin.tenant_id = admin.tenant_id or resolved_tenant_id
        admin.updated_at = datetime.utcnow()

    session.commit()


# Backward-compatible alias used by older bootstrap code.
seed_auth_data = seed_default_auth

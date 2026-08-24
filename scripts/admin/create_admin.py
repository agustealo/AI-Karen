import asyncio
import sys
import os
from passlib.context import CryptContext

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.curdir))

# Mock settings or import them
from ai_karen_engine.database.integration_manager import get_database_manager
from ai_karen_engine.server.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def create_admin():
    db_manager = await get_database_manager()

    email = "admin@kari.ai"
    password = "Admin@123!"
    full_name = "Admin User"

    # Hardcoded hash for Admin@123! to bypass passlib/bcrypt issues on Python 3.13
    hashed_password = "$2b$12$1BVzKwS0wvU6FzcjiiVNhO2On8T1hLz1o4FLXnn78M6MDDJNZ99DS"

    print(f"Creating user {email}...")

    query_tenant = """
    INSERT INTO tenants (id, name, slug, subscription_tier, is_active, created_at, updated_at)
    VALUES ('00000000-0000-0000-0000-000000000000', 'Default Tenant', 'default', 'enterprise', true, now(), now())
    ON CONFLICT (slug) DO NOTHING;
    """

    query_user = """
    INSERT INTO auth_users (user_id, email, username, full_name, password_hash, tenant_id, roles, preferences, is_active, is_verified, two_factor_enabled, failed_login_attempts, created_at, updated_at)
    VALUES (:user_id, :email, :username, :full_name, :password_hash, '00000000-0000-0000-0000-000000000000', '["admin", "user"]', '{}', true, true, false, 0, now(), now())
    ON CONFLICT (email) DO UPDATE 
    SET password_hash = EXCLUDED.password_hash,
        full_name = EXCLUDED.full_name,
        is_active = true,
        updated_at = now();
    """

    try:
        from sqlalchemy import text
        import uuid

        async with db_manager.get_session() as session:
            # Create default tenant first
            await session.execute(text(query_tenant))

            # Create admin user
            await session.execute(
                text(query_user),
                {
                    "user_id": str(uuid.uuid4()),
                    "email": email,
                    "username": "admin",
                    "full_name": full_name,
                    "password_hash": hashed_password,
                },
            )
            await session.commit()
            print(f"Successfully created/updated admin user: {email}")

    except Exception as e:
        print(f"Error creating user: {e}")


if __name__ == "__main__":
    asyncio.run(create_admin())

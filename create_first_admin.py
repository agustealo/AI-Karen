#!/usr/bin/env python3
"""Script to create the first admin user for AI Karen."""

import asyncio
import os
import sys

# Add the src directory to the path
sys.path.insert(0, "/mnt/Development/GitHub/AI-Karen/src")

# Set required environment variables
os.environ.setdefault("KARI_FIRST_RUN_TENANT_SLUG", "installation")
os.environ.setdefault("KARI_FIRST_RUN_TENANT_NAME", "AI KAREN")
os.environ.setdefault("AUTH_JWT_SECRET_KEY", "change-me-in-production-secure-key")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:54322/postgres")
os.environ.setdefault("AUTH_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:54322/postgres")

# Configure auth settings
os.environ.setdefault("AUTH_PASSWORD_MIN_LENGTH", "8")
os.environ.setdefault("AUTH_PASSWORD_REQUIRE_COMPLEXITY", "true")
os.environ.setdefault("AUTH_BCRYPT_ROUNDS", "12")
os.environ.setdefault("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("AUTH_REFRESH_TOKEN_EXPIRE_DAYS", "7")
os.environ.setdefault("AUTH_MAX_FAILED_LOGIN_ATTEMPTS", "5")
os.environ.setdefault("AUTH_ACCOUNT_LOCKOUT_MINUTES", "15")
os.environ.setdefault("AUTH_JWT_ALGORITHM", "HS256")


async def main():
    from ai_karen_engine.services.auth.auth_service import AuthService, UserRole
    
    print("Creating first admin user...")
    
    # Create auth service
    auth_service = AuthService()
    
    try:
        # Initialize the service
        await auth_service.initialize()
        print("Auth service initialized")
        
        # Check if this is first run
        is_first = await auth_service.is_first_run()
        print(f"Is first run: {is_first}")
        
        email = os.getenv("ADMIN_EMAIL", "admin@karen.ai")
        password = os.getenv("ADMIN_PASSWORD", "!Password123")
        full_name = os.getenv("ADMIN_FULL_NAME", "Admin User")

        if not is_first:
            print("First run setup flag returned False (users exist).")
            # Check if requested admin user exists
            user = await auth_service.get_user(email)
            if user:
                print(f"Admin user already exists: {user.email}")
                return
            else:
                print(f"User {email} not found. Attempting user creation...")
                user, error = await auth_service.create_user(
                    email=email,
                    password=password,
                    full_name=full_name,
                    roles=[UserRole.ADMIN, UserRole.USER],
                    is_verified=True,
                )
                if user:
                    print(f"Admin user created successfully: {user.email}")
                    return
                else:
                    print(f"Error creating user {email}: {error}")
                    return
        
        user = await auth_service.create_first_admin(
            email=email,
            password=password,
            full_name=full_name
        )
        
        print(f"First admin user created successfully!")
        print(f"  Email: {user.email}")
        print(f"  User ID: {user.id}")
        print(f"  Roles: {user.roles}")
        print(f"  Tenant ID: {user.tenant_id}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await auth_service.stop()


if __name__ == "__main__":
    asyncio.run(main())
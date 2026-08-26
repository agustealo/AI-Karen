from __future__ import annotations

from pathlib import Path

PATH = Path("src/ai_karen_engine/api_routes/auth/auth.py")


def replace_once(source: str, old: str, new: str) -> str:
    if old not in source:
        raise RuntimeError(f"marker not found:\n{old}")
    return source.replace(old, new, 1)


def main() -> None:
    source = PATH.read_text(encoding="utf-8")

    source = replace_once(
        source,
        '''async def auth_status() -> Dict[str, Any]:\n    """Get authentication service status."""\n    auth_service_instance = await get_auth_service()\n    stats = await auth_service_instance.get_auth_stats()\n''',
        '''async def auth_status(\n    auth_svc: CoreAuthService = Depends(get_auth_service),\n) -> Dict[str, Any]:\n    """Get authentication service status."""\n    stats = await auth_svc.get_auth_stats()\n''',
    )
    source = source.replace("auth_service_instance.config", "auth_svc.config")

    source = replace_once(
        source,
        '''async def auth_health() -> Dict[str, Any]:\n    """Authentication service health check."""\n    auth_service_instance = await get_auth_service()\n    is_healthy = await auth_service_instance.health_check()\n''',
        '''async def auth_health(\n    auth_svc: CoreAuthService = Depends(get_auth_service),\n) -> Dict[str, Any]:\n    """Authentication service health check."""\n    is_healthy = await auth_svc.health_check()\n''',
    )

    source = replace_once(
        source,
        '''async def check_first_run() -> Dict[str, Any]:\n    """Check if first-run setup is required."""\n    try:\n        auth_service_instance = await get_auth_service()\n        is_first_run = await auth_service_instance.is_first_run()\n''',
        '''async def check_first_run(\n    auth_svc: CoreAuthService = Depends(get_auth_service),\n) -> Dict[str, Any]:\n    """Check if first-run setup is required."""\n    try:\n        is_first_run = await auth_svc.is_first_run()\n''',
    )

    source = replace_once(
        source,
        '''async def first_run_setup(\n    request: FirstRunSetupRequest, http_request: Request\n) -> JSONResponse:\n    """Set up the first admin user through the canonical auth authority."""\n    try:\n        auth_svc = await get_auth_service()\n    except Exception:\n        # If auth service fails to initialize, return error\n        raise HTTPException(\n            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,\n            detail="Auth service unavailable for first-run setup",\n        )\n\n''',
        '''async def first_run_setup(\n    request: FirstRunSetupRequest,\n    http_request: Request,\n    auth_svc: CoreAuthService = Depends(get_auth_service),\n) -> JSONResponse:\n    """Set up the first admin user through the canonical auth authority."""\n\n''',
    )

    source = replace_once(
        source,
        '''async def refresh_token(\n    request: RefreshTokenRequest, http_request: Request\n) -> JSONResponse:\n    """Rotate the refresh token and return a fresh token pair."""\n    auth_svc = await get_auth_service()\n''',
        '''async def refresh_token(\n    request: RefreshTokenRequest,\n    http_request: Request,\n    auth_svc: CoreAuthService = Depends(get_auth_service),\n) -> JSONResponse:\n    """Rotate the refresh token and return a fresh token pair."""\n''',
    )

    source = replace_once(
        source,
        '''async def logout(\n    request: RefreshTokenRequest,\n    current_user=Depends(get_authenticated_user),\n) -> JSONResponse:\n    auth_svc = await get_auth_service()\n''',
        '''async def logout(\n    request: RefreshTokenRequest,\n    current_user=Depends(get_authenticated_user),\n    auth_svc: CoreAuthService = Depends(get_auth_service),\n) -> JSONResponse:\n''',
    )

    source = replace_once(
        source,
        '''async def change_password(\n    request: ChangePasswordRequest,\n    current_user=Depends(get_authenticated_user),\n) -> Dict[str, str]:\n''',
        '''async def change_password(\n    request: ChangePasswordRequest,\n    current_user=Depends(get_authenticated_user),\n    auth_svc: CoreAuthService = Depends(get_auth_service),\n) -> Dict[str, str]:\n''',
    )
    source = replace_once(source, "\n    auth_svc = await get_auth_service()\n    error = await auth_svc.change_user_password(\n", "\n    error = await auth_svc.change_user_password(\n")

    source = replace_once(
        source,
        '''async def create_user(\n    request: CreateUserRequest, current_user=Depends(get_authenticated_user)\n) -> JSONResponse:\n''',
        '''async def create_user(\n    request: CreateUserRequest,\n    current_user=Depends(get_authenticated_user),\n    auth_svc: CoreAuthService = Depends(get_auth_service),\n) -> JSONResponse:\n''',
    )
    source = replace_once(source, "\n    auth_svc = await get_auth_service()\n    user, error = await auth_svc.create_user(\n", "\n    user, error = await auth_svc.create_user(\n")

    source = replace_once(
        source,
        '''async def get_auth_stats(\n    current_user=Depends(get_authenticated_user),\n) -> Dict[str, Any]:\n''',
        '''async def get_auth_stats(\n    current_user=Depends(get_authenticated_user),\n    auth_svc: CoreAuthService = Depends(get_auth_service),\n) -> Dict[str, Any]:\n''',
    )
    source = replace_once(source, "\n    auth_svc = await get_auth_service()\n    stats = await auth_svc.get_auth_stats()\n", "\n    stats = await auth_svc.get_auth_stats()\n")

    if "await get_auth_service()" in source:
        raise RuntimeError("direct get_auth_service call remains in auth routes")

    PATH.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise AssertionError(f"required first-run contract file missing: {relative}")
    return path.read_text(encoding="utf-8")


def _require(text: str, *needles: str, source: str) -> None:
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise AssertionError(f"{source} missing first-run contract markers: {missing}")


def main() -> None:
    auth_route = _read("src/ai_karen_engine/api_routes/auth/auth.py")
    smoke = _read("scripts/ci/production-first-boot-smoke.sh")
    workflow = _read(".github/workflows/production-first-boot-smoke.yml")
    architecture = _read("docs/architecture/FIRST_RUN_SYSTEM.md")

    _require(
        auth_route,
        '@router.get("/first-run")',
        '@router.post("/first-run/setup")',
        "await auth_service_instance.is_first_run()",
        "await auth_svc.create_first_admin(",
        "await auth_svc.authenticate_user(",
        "_serialize_permissions(user_data)",
        'key="kari_session"',
        'httponly=True',
        source="auth route",
    )

    forbidden_route_authority = (
        "select_provider(",
        "execute_plugin(",
        "execute_tool(",
        "docker ",
        "subprocess.",
        "CREATE TABLE",
    )
    leaked = [marker for marker in forbidden_route_authority if marker in auth_route]
    if leaked:
        raise AssertionError(
            f"first-run auth ingress gained forbidden orchestration authority: {leaked}"
        )

    _require(
        smoke,
        "ENVIRONMENT=production",
        "DEBUG=false",
        "AUTH_DEV_MODE=false",
        "AUTH_ALLOW_DEV_LOGIN=false",
        "KARI_AUTH_BYPASS=false",
        "AUTH_ENABLE_SESSION_VALIDATION=true",
        "AUTH_AUTO_CREATE_TABLES=false",
        "find supabase/migrations",
        '"${BASE_URL}/health/live"',
        '"${BASE_URL}/api/auth/health"',
        '"${BASE_URL}/api/auth/first-run"',
        '"${BASE_URL}/api/auth/first-run/setup"',
        '"${BASE_URL}/api/auth/me"',
        '"${BASE_URL}/api/auth/login"',
        "restart",
        "PRODUCTION FIRST-BOOT SMOKE PASSED",
        source="production first-boot smoke",
    )

    _require(
        workflow,
        "Attest exact worker SHA",
        "Validate smoke harness",
        "Build production API image",
        "Execute real production first boot",
        source="production first-boot workflow",
    )

    _require(
        architecture,
        "Auth owns initial durable identity",
        "BOOTSTRAP_BLOCKED",
        "OWNER_REQUIRED",
        "OWNER_CREATED",
        "OPERATIONAL",
        "RuntimePolicy",
        "restart",
        source="first-run architecture document",
    )

    print("FIRST-RUN ARCHITECTURE CONTRACT PASSED")


if __name__ == "__main__":
    main()

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = REPO_ROOT / "deploy" / "compose" / "docker-compose.prod.yml"
PROD_ENV_EXAMPLE = REPO_ROOT / ".env.production.example"
WEB_PROD_DOCKERFILE = (
    REPO_ROOT / "src" / "ui_launchers" / "Karen-AI-Theme" / "Dockerfile.production"
)


def _service_block(text: str, service: str) -> str:
    service_marker = f"  {service}:"
    start = text.index(service_marker)
    next_service = text.find("\n  ", start + len(service_marker))
    return text[start:] if next_service == -1 else text[start:next_service]


def test_canonical_production_compose_overlay_exists() -> None:
    assert PROD_COMPOSE.is_file(), (
        "Production deployment must have one canonical compose overlay at "
        "deploy/compose/docker-compose.prod.yml"
    )


def test_production_overlay_fails_closed_on_required_secrets() -> None:
    text = PROD_COMPOSE.read_text(encoding="utf-8")

    required_fail_closed_vars = {
        "AUTH_JWT_SECRET_KEY",
        "REDIS_PASSWORD",
        "DATABASE_URL",
        "POSTGRES_URL",
        "AUTH_DATABASE_URL",
        "DATABASE_PASSWORD",
        "DB_HOST",
        "DB_USER",
        "DB_NAME",
    }

    for variable in required_fail_closed_vars:
        assert f"${{{variable}:?" in text, (
            f"{variable} must use Compose required-variable syntax in production"
        )


def test_production_overlay_disables_development_auth_paths() -> None:
    text = PROD_COMPOSE.read_text(encoding="utf-8")

    required_false_settings = {
        "DEBUG",
        "AUTH_DEV_MODE",
        "AUTH_ALLOW_DEV_LOGIN",
        "KARI_AUTH_BYPASS",
        "KARI_FAST_STARTUP",
        "KARI_SKIP_STARTUP_CHECK",
        "KARI_SKIP_AUTO_INIT",
        "ALLOW_PUBLIC_COPILOT",
    }

    for setting in required_false_settings:
        assert f'{setting}: "false"' in text, (
            f"Production overlay must explicitly force {setting}=false"
        )


def test_production_overlay_does_not_publish_internal_control_plane_ports() -> None:
    text = PROD_COMPOSE.read_text(encoding="utf-8")

    for service in ("redis", "prometheus", "grafana"):
        block = _service_block(text, service)
        assert "ports: !reset []" in block, (
            f"{service} must not publish a host port in the production overlay"
        )


def test_production_overlay_does_not_inherit_development_env_files() -> None:
    text = PROD_COMPOSE.read_text(encoding="utf-8")

    for service in ("redis", "api", "web"):
        block = _service_block(text, service)
        assert "env_file: !reset []" in block, (
            f"{service} must not inherit the base .env file in production"
        )


def test_production_web_uses_immutable_production_runtime() -> None:
    text = PROD_COMPOSE.read_text(encoding="utf-8")
    web_block = _service_block(text, "web")

    assert "dockerfile: Dockerfile.production" in web_block
    assert "NODE_ENV: production" in web_block
    assert "volumes: !reset []" in web_block
    assert "command: !reset null" in web_block
    assert "npm run dev" not in web_block

    assert WEB_PROD_DOCKERFILE.is_file()
    dockerfile = WEB_PROD_DOCKERFILE.read_text(encoding="utf-8")
    assert "RUN npm ci --no-audit --no-fund" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert 'USER nextjs' in dockerfile
    assert 'CMD ["npm", "run", "start"' in dockerfile


def test_production_environment_template_contains_no_real_credentials() -> None:
    text = PROD_ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "Admin@123!" not in text
    assert "postgres:postgres@" not in text
    assert "CHANGE_ME" in text
    assert "KARI_AUTH_BYPASS=false" in text
    assert "AUTH_DEV_MODE=false" in text

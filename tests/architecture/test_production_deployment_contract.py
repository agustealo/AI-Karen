from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = REPO_ROOT / "deploy" / "compose" / "docker-compose.prod.yml"
PROD_ENV_EXAMPLE = REPO_ROOT / ".env.production.example"
WEB_PROD_ROOT = REPO_ROOT / "src" / "ui_launchers" / "Karen-AI-Theme"
WEB_PROD_DOCKERFILE = WEB_PROD_ROOT / "Dockerfile.production"
WEB_PROD_INGRESS = WEB_PROD_ROOT / "server.mjs"


def _service_block(text: str, service: str) -> str:
    """Return one Compose service block using YAML indentation boundaries."""
    lines = text.splitlines()
    service_marker = f"  {service}:"

    try:
        start = next(index for index, line in enumerate(lines) if line == service_marker)
    except StopIteration as exc:
        raise AssertionError(f"Compose service {service!r} is missing") from exc

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indentation = len(line) - len(line.lstrip(" "))
        if indentation <= 2:
            end = index
            break

    return "\n".join(lines[start:end])


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

    for service in ("redis", "api", "prometheus", "grafana"):
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


def test_production_api_does_not_mask_attested_source_or_config() -> None:
    text = PROD_COMPOSE.read_text(encoding="utf-8")
    api_block = _service_block(text, "api")

    assert "volumes: !override" in api_block
    assert "./:/app" not in api_block
    assert "./config:/app/config" not in api_block
    assert "KAREN_BUILTIN_VLLM_ENABLED: \"false\"" in api_block
    assert "AUTH_ENABLE_SESSION_VALIDATION: \"true\"" in api_block
    assert 'HTTP_TRUSTED_PROXY_HOSTS: "web"' in api_block
    assert "RATE_LIMIT_TRUSTED_PROXY_HOSTS" not in api_block


def test_production_web_uses_immutable_production_runtime() -> None:
    text = PROD_COMPOSE.read_text(encoding="utf-8")
    web_block = _service_block(text, "web")

    assert "dockerfile: Dockerfile.production" in web_block
    assert "NODE_ENV: production" in web_block
    assert (
        "WEB_PUBLIC_SCHEME: ${WEB_PUBLIC_SCHEME:?WEB_PUBLIC_SCHEME must be http or https in production}"
        in web_block
    )
    assert "volumes: !reset []" in web_block
    assert "command: !reset null" in web_block
    assert "npm run dev" not in web_block

    assert WEB_PROD_DOCKERFILE.is_file()
    dockerfile = WEB_PROD_DOCKERFILE.read_text(encoding="utf-8")
    assert "RUN npm ci --no-audit --no-fund" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert "USER nextjs" in dockerfile
    assert 'CMD ["node", "server.mjs"]' in dockerfile

    assert WEB_PROD_INGRESS.is_file()
    ingress = WEB_PROD_INGRESS.read_text(encoding="utf-8")
    assert "req.socket.remoteAddress" in ingress
    assert "req.headers['x-forwarded-for'] = clientIp" in ingress
    assert "process.env.WEB_PUBLIC_SCHEME" in ingress
    assert "req.headers['x-forwarded-proto'] = publicScheme" in ingress


def test_production_environment_template_contains_no_real_credentials() -> None:
    text = PROD_ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "Admin@123!" not in text
    assert "postgres:postgres@" not in text
    assert "CHANGE_ME" in text
    assert "KARI_AUTH_BYPASS=false" in text
    assert "AUTH_DEV_MODE=false" in text
    assert "WEB_PUBLIC_SCHEME=CHANGE_ME_HTTP_OR_HTTPS" in text


def test_training_worker_is_opt_in_and_uses_api_model_registry_mount() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    worker = _service_block(compose, "training-worker")
    api = _service_block(compose, "api")

    assert "profiles:" in worker
    assert "      - training-worker" in worker
    assert 'KAREN_TRAINING_WORKER_TENANT: "${KAREN_TRAINING_WORKER_TENANT:-}"' in worker
    assert "./models:/app/models:rw" in worker
    assert "./models:/app/models:rw" in api
    assert "ai_karen_engine.core.intelligence.ml.training.worker_service" in worker
    assert "depends_on:" not in worker



def test_production_images_carry_explicit_release_revision() -> None:
    """Both production services must receive the same reviewed build identity."""
    overlay = PROD_COMPOSE.read_text(encoding="utf-8")
    required = "KAREN_DEPLOYED_COMMIT_SHA: " + chr(36) + "{KAREN_DEPLOYED_COMMIT_SHA:?"
    for service, image in (("web", "ai-karen-web:"), ("api", "ai-karen-api:")):
        block = _service_block(overlay, service)
        assert block.count(required) == 2
        assert "image: " + image + chr(36) + "{KAREN_DEPLOYED_COMMIT_SHA:?" in block
        assert "build:" in block and "args:" in block
        assert "environment:" in block

    web_dockerfile = WEB_PROD_DOCKERFILE.read_text(encoding="utf-8")
    assert "ARG KAREN_DEPLOYED_COMMIT_SHA" in web_dockerfile
    assert "grep -Eq '^[a-f0-9]{40}$'" in web_dockerfile
    assert 'LABEL org.opencontainers.image.revision="' + chr(36) + '{KAREN_DEPLOYED_COMMIT_SHA}"' in web_dockerfile
    assert 'ENV KAREN_DEPLOYED_COMMIT_SHA="' + chr(36) + '{KAREN_DEPLOYED_COMMIT_SHA}"' in web_dockerfile

    api_dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'LABEL org.opencontainers.image.revision="' + chr(36) + '{KAREN_DEPLOYED_COMMIT_SHA}"' in api_dockerfile
    web_revision = (
        WEB_PROD_ROOT / "src/app/api/deployment-revision/route.ts"
    ).read_text(encoding="utf-8")
    assert "process.env.KAREN_DEPLOYED_COMMIT_SHA" in web_revision


def test_production_template_requires_explicit_revision() -> None:
    env_text = PROD_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "KAREN_DEPLOYED_COMMIT_SHA=CHANGE_ME_40_CHARACTER_LOWERCASE_GIT_SHA" in env_text



def test_ci_production_image_builds_bind_checked_out_commit() -> None:
    """Every CI build of the production Dockerfiles must stamp source identity.

    Pull requests may test a synthetic merge commit; its checked-out SHA is
    valid for the CI image, not an attestation for a production promotion.
    """
    workflows = (
        ".github/workflows/production-first-boot-smoke.yml",
        ".github/workflows/beta-release-gate.yml",
        ".github/workflows/beta-live-model-smoke.yml",
        ".github/workflows/ollama-settings-live-e2e.yml",
        ".github/workflows/presentation-capture.yml",
    )
    for workflow in workflows:
        source = (REPO_ROOT / workflow).read_text(encoding="utf-8")
        assert "git rev-parse HEAD" in source
        blocks = source.split("\n      - name: ")
        builds = [block for block in blocks if "docker build" in block]
        assert builds, f"No production image build found in {workflow}"
        for block in builds:
            assert "--build-arg KAREN_DEPLOYED_COMMIT_SHA" in block, (
                f"Production Docker build omitted reviewed source SHA: {workflow}"
            )



def test_trusted_presentation_capture_stamps_target_not_workflow_sha() -> None:
    """Candidate and orchestrator have distinct identities in presentation proof."""
    source = (
        REPO_ROOT / ".github/workflows/presentation-capture.yml"
    ).read_text(encoding="utf-8")
    assert "Attest exact trusted checkout and target ancestry" in source
    assert "Attest exact candidate checkout" in source
    for name in ("Build exact candidate production API image", "Build exact candidate production web image"):
        build = source.split("      - name: " + name, 1)[1].split("\n      - name:", 1)[0]
        assert "working-directory: .presentation-target" in build
        assert "KAREN_SHOWCASE_TARGET_REVISION: " + chr(36) + "{{ needs.prepare.outputs.target_revision }}" in build
        assert 'test "$(git rev-parse HEAD)" = "$KAREN_SHOWCASE_TARGET_REVISION"' in build
        assert '--build-arg KAREN_DEPLOYED_COMMIT_SHA="$KAREN_SHOWCASE_TARGET_REVISION"' in build
        assert '--build-arg KAREN_DEPLOYED_COMMIT_SHA="$GITHUB_SHA"' not in build


def test_render_beta_blueprint_references_existing_data_without_provisioning() -> None:
    """The beta Blueprint cannot create duplicate managed data services."""
    blueprint = REPO_ROOT / "deploy" / "render" / "render.yaml"
    text = blueprint.read_text(encoding="utf-8")
    assert "name: ai-karen-beta-api" in text
    assert "name: ai-karen-beta-postgres" in text
    assert "name: ai-karen-beta-redis" in text
    assert "fromDatabase:" in text
    assert "fromService:" in text
    assert "\ndatabases:" not in text
    assert "\n  - type: keyvalue" not in text


def test_render_beta_blueprint_never_invents_production_credentials() -> None:
    """Secrets and driver-specific connection URLs stay externally governed."""
    blueprint = REPO_ROOT / "deploy" / "render" / "render.yaml"
    text = blueprint.read_text(encoding="utf-8")
    for key in (
        "POSTGRES_URL",
        "AUTH_DATABASE_URL",
        "KARI_JOB_ENC_KEY",
        "KARI_CORS_ORIGINS",
    ):
        assert f"      - key: {key}\n        sync: false" in text
    for key in (
        "SECRET_KEY",
        "AUTH_SECRET_KEY",
        "AUTH_JWT_SECRET_KEY",
        "EXTENSION_SECRET_KEY",
        "EXTENSION_API_KEY",
        "KARI_JOB_SIGNING_KEY",
        "KARI_MODEL_SIGNING_KEY",
    ):
        assert f"      - key: {key}\n        generateValue: true" in text
    assert "autoDeployTrigger: off" in text
    assert 'value: "true"\n      - key: KARI_AUTH_BYPASS' not in text

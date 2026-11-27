from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ENTRYPOINT = REPO_ROOT / "src" / "ai_karen_engine" / "app.py"
LEGACY_SERVER_APP = REPO_ROOT / "server" / "app.py"
CLI_ENTRYPOINT = REPO_ROOT / "src" / "ai_karen_engine" / "cli.py"
DOCKERFILE = REPO_ROOT / "Dockerfile"


def test_canonical_application_entrypoint_constructs_fastapi_directly() -> None:
    source = APP_ENTRYPOINT.read_text(encoding="utf-8")

    assert "def create_app()" in source
    assert "app = FastAPI(" in source
    assert "create_application_lifespan(settings)" in source
    assert "wire_routers(app, settings)" in source
    assert "from server import app as legacy_app" not in source
    assert "legacy_app.app" not in source
    assert "sys.path" not in source


def test_legacy_server_app_is_compatibility_only() -> None:
    source = LEGACY_SERVER_APP.read_text(encoding="utf-8")

    assert "from ai_karen_engine.app import create_app" in source
    assert "app = create_app()" in source
    assert "FastAPI(" not in source
    assert "wire_routers(" not in source
    assert "create_application_lifespan" not in source
    assert "@app.on_event" not in source


def test_operator_cli_targets_canonical_application() -> None:
    source = CLI_ENTRYPOINT.read_text(encoding="utf-8")

    assert 'APP_TARGET = "ai_karen_engine.app:create_app"' in source
    assert '"--factory"' in source
    assert "server.app" not in source
    assert "server.run" not in source
    assert "sys.path.insert" not in source


def test_docker_runs_canonical_asgi_entrypoint_directly() -> None:
    source = DOCKERFILE.read_text(encoding="utf-8")

    assert '"ai_karen_engine.app:create_app"' in source
    assert '"--factory"' in source
    assert 'CMD ["python", "start.py"]' not in source
    assert "EXPOSE 8000 9090" not in source


def test_retired_startup_layers_do_not_reappear() -> None:
    assert not (REPO_ROOT / "start.py").exists()
    assert not (REPO_ROOT / "server" / "run.py").exists()


def test_docker_does_not_install_unused_poetry_launcher_dependency() -> None:
    source = DOCKERFILE.read_text(encoding="utf-8")

    assert "pip install --no-cache-dir poetry" not in source
    assert "setuptools wheel poetry" not in source


def test_retired_execution_adapters_never_simulate_or_execute():
    import asyncio

    from ai_karen_engine.services.tooling.code_execution_service import (
        CodeExecutionRequest,
        CodeExecutionService,
        CodeLanguage,
        SecurityLevel,
        ToolExecutionContext,
        ToolIntegrationService,
    )

    async def exercise():
        code_service = CodeExecutionService()
        request = CodeExecutionRequest(
            code="print('private source')",
            language=CodeLanguage.PYTHON,
            security_level=SecurityLevel.STRICT,
        )
        result = await code_service.execute_code(request)
        assert result.status == "unavailable"
        assert not result.execution_id
        assert not result.output
        assert result.metadata["execution_performed"] is False
        assert "private source" not in repr(result)
        validation = await code_service.validate_code(request.code, request.language)
        assert validation["valid"] is False
        assert validation["status"] == "unavailable"
        assert await code_service.get_supported_languages() == []
        tools = ToolIntegrationService()
        for name in ("weather", "calculator", "search", "unknown"):
            received = await tools.execute_tool(ToolExecutionContext(
                tool_name=name, parameters={"expression": "1 + 1"}, user_id="owner",
            ))
            assert received.success is False
            assert received.output is None
            assert received.metadata["execution_performed"] is False
        assert await tools.list_tools() == []

    asyncio.run(exercise())


def test_retired_execution_service_contains_no_dynamic_execution_or_fake_success():
    import ast

    service = REPO_ROOT / "src/ai_karen_engine/services/tooling/code_execution_service.py"
    route = REPO_ROOT / "src/ai_karen_engine/api_routes/tools/code_execution.py"
    for path in (service, route):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"eval", "exec", "compile"}
            for node in ast.walk(tree)
        )
        assert "Code executed successfully (simulated)" not in source
    source = route.read_text(encoding="utf-8")
    assert "dependencies=[Depends(get_current_user)]" in source
    assert "get_current_user = get_user_context" in source
    assert "status_code=503" in source

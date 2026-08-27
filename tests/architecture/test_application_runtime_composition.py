from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPLICATION_RUNTIME = (
    ROOT / "src/ai_karen_engine/server/application_runtime.py"
)
LEGACY_SERVER_APP = ROOT / "server/app.py"


def test_application_lifespan_owns_runtime_attachment_and_shutdown() -> None:
    source = APPLICATION_RUNTIME.read_text(encoding="utf-8")

    assert "await on_startup(settings, app)" in source
    assert "await initialize_application_runtime(app)" in source
    assert "await shutdown_application_runtime(app)" in source
    assert "await on_shutdown(app)" in source


def test_application_runtime_attaches_canonical_services_to_app_state() -> None:
    source = APPLICATION_RUNTIME.read_text(encoding="utf-8")

    assert "app.state.runtime_composition = composition" in source
    assert "app.state.chat_runtime = chat_runtime" in source
    assert "app.state.chat_runtime_control_plane = control_plane" in source
    assert "get_runtime_composition()" in source
    assert "get_chat_runtime()" in source
    assert "get_chat_runtime_control_plane()" in source


def test_application_runtime_owns_control_plane_background_shutdown() -> None:
    source = APPLICATION_RUNTIME.read_text(encoding="utf-8")

    assert "await control_plane.shutdown()" in source
    assert '_RUNTIME_SHUTDOWN_STATE_KEY' in source


def test_application_runtime_is_restart_safe_after_control_plane_shutdown() -> None:
    source = APPLICATION_RUNTIME.read_text(encoding="utf-8")

    assert 'if not getattr(control_plane, "_initialized", False):' in source
    assert "await control_plane.initialize()" in source
    assert "and not getattr(" in source
    assert "_RUNTIME_SHUTDOWN_STATE_KEY" in source


def test_transitional_server_app_uses_canonical_application_lifespan() -> None:
    source = LEGACY_SERVER_APP.read_text(encoding="utf-8")

    assert "ai_karen_engine.server.application_runtime import create_application_lifespan" in source
    assert "lifespan = create_application_lifespan(settings)" in source
    assert "from ai_karen_engine.server.startup import create_lifespan" not in source

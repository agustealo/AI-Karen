"""Prevent reintroduction of unapproved plugin lifecycle writes at ingress.

The canonical PluginService + RuntimePolicy/ApprovalService + SQL ledger owns
governed execution. This source-level guard applies to the mounted legacy HTTP
routes and extension-platform compatibility facade. It is not a substitute
for a repository-wide physical mutation reference audit.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_HTTP = ROOT / "src/ai_karen_engine/api_routes/plugins/plugins.py"
STORE_HTTP = ROOT / "src/ai_karen_engine/api_routes/plugins/store.py"
EXTENSION_HTTP = ROOT / "src/ai_karen_engine/api_routes/extensions/extensions.py"
PLATFORM_FACADE = ROOT / "src/ai_karen_engine/extensions/platform/core/manager.py"
CANONICAL_SERVICE = ROOT / "src/ai_karen_engine/services/plugin_service.py"


def _method(path: Path, method: str) -> ast.AsyncFunctionDef:
    source = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node for node in ast.walk(source)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == method
    ]
    assert len(matches) == 1, f"Expected exactly one {method} in {path}"
    return matches[0]


def _calls(method: ast.AsyncFunctionDef) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_legacy_http_entrypoints_never_invoke_direct_plugin_enable_disable() -> None:
    for path, name in (
        (PLUGIN_HTTP, "_set_enabled"),
        (PLUGIN_HTTP, "reload_plugins"),
        (STORE_HTTP, "install_plugin_endpoint"),
        (EXTENSION_HTTP, "load_extension"),
        (EXTENSION_HTTP, "unload_extension"),
    ):
        calls = _calls(_method(path, name))
        assert not calls.intersection({
            "enable_plugin", "disable_plugin", "refresh_plugins",
            "enable", "disable", "load_extension", "unload_extension",
            "refresh_registry", "reload_runtime",
        }), f"Legacy {path}:{name} bypassed the approved lifecycle authority"


def test_platform_facade_delegates_exact_action_to_canonical_service() -> None:
    for name in ("load_extension", "unload_extension"):
        calls = _calls(_method(PLATFORM_FACADE, name))
        assert "execute_approved_lifecycle" in calls
        assert not calls.intersection({
            "enable_plugin", "disable_plugin", "enable", "disable",
        })
    for name in ("reload_extension", "refresh_registry", "reload_runtime"):
        calls = _calls(_method(PLATFORM_FACADE, name))
        assert not calls.intersection({
            "enable_plugin", "disable_plugin", "refresh_plugins",
            "enable", "disable", "load_extension", "unload_extension",
        })


def test_extension_catalog_reads_do_not_refresh_plugin_runtime() -> None:
    calls = _calls(_method(PLATFORM_FACADE, "refresh_extensions"))
    assert "list_plugins" in calls
    assert not calls.intersection({
        "refresh_plugins", "enable_plugin", "disable_plugin",
        "enable", "disable",
    })


def test_canonical_governed_executor_is_preserved_and_unmounted() -> None:
    service = _method(CANONICAL_SERVICE, "execute_approved_lifecycle")
    calls = _calls(service)
    for owner in (
        "reserve_approved", "hold_prepared_execution",
        "transition_prepared_lifecycle", "complete_verified",
        "authorize_approved_plugin_lifecycle", "authorize",
    ):
        assert owner in calls
    assert "enable_plugin" not in calls
    assert "disable_plugin" not in calls
    # The old HTTP handlers cannot infer their own approval or session, and
    # must not direct-call the newly introduced host-only executor either.
    for path, name in (
        (PLUGIN_HTTP, "_set_enabled"),
        (STORE_HTTP, "install_plugin_endpoint"),
        (EXTENSION_HTTP, "load_extension"),
        (EXTENSION_HTTP, "unload_extension"),
    ):
        assert "execute_approved_lifecycle" not in _calls(_method(path, name))



def test_new_admin_routes_delegate_only_to_governed_lifecycle_methods() -> None:
    prepare = _calls(_method(PLUGIN_HTTP, "request_plugin_lifecycle_approval"))
    execute = _calls(_method(PLUGIN_HTTP, "execute_plugin_lifecycle_approval"))
    assert "prepare_lifecycle_approval" in prepare
    assert "resume_lifecycle_approval" in execute
    for calls in (prepare, execute):
        assert not calls.intersection({
            "enable_plugin", "disable_plugin", "refresh_plugins",
            "enable", "disable", "transition_prepared_lifecycle",
            "reserve_approved", "complete_verified",
        })
    for name in ("enable_plugin", "disable_plugin", "_set_enabled"):
        assert "resume_lifecycle_approval" not in _calls(_method(PLUGIN_HTTP, name))
        assert "prepare_lifecycle_approval" not in _calls(_method(PLUGIN_HTTP, name))


def test_verified_bearer_identity_resolver_is_required_for_admin_lifecycle() -> None:
    auth_source = (ROOT / "src/ai_karen_engine/auth/session.py").read_text(
        encoding="utf-8"
    )
    resolver = auth_source.split(
        "async def get_plugin_lifecycle_context", 1
    )[1].split("__all__", 1)[0]
    assert "should_bypass_auth()" in resolver
    assert 'startswith("Bearer ")' in resolver
    assert "validate_token(token)" in resolver
    assert 'payload.get("token_id")' in resolver
    assert "ChatExecutionContext(" in resolver
    assert 'request.headers.get("X-Session-Id")' not in resolver
    assert "get_dev_user_context" not in resolver

    # Both HTTP surfaces must depend on the verified bearer resolver and
    # must never reconstruct a session or lifecycle scope in the route.
    route_source = PLUGIN_HTTP.read_text(encoding="utf-8")
    for name, tail in (
        ("request_plugin_lifecycle_approval", "execute_plugin_lifecycle_approval"),
        ("execute_plugin_lifecycle_approval", "enable_plugin"),
    ):
        entry = route_source.split(f"async def {name}(", 1)[1].split(
            f"async def {tail}(", 1
        )[0]
        assert "Depends(get_plugin_lifecycle_context)" in entry
        assert "PluginLifecycleApprovalScope(" not in entry
        assert "ChatExecutionContext(" not in entry

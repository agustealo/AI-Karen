"""Migration guard regression tests: filesystem fixtures, no network or SDK needed."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts/architecture/audit_copilotkit_wiring.py"
)
SPEC = importlib.util.spec_from_file_location("audit_copilotkit_wiring", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


def fixture(root: Path, *, copilot: bool = False) -> None:
    for path in AUDITOR.OWNERS.values():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("canonical owner\n", encoding="utf-8")

    config = root / AUDITOR.OWNERS["runtime_config"]
    config.write_text("enable_ag_ui_bridge: bool = False\n", encoding="utf-8")
    ingress = root / AUDITOR.OWNERS["ag_ui_ingress"]
    ingress.write_text(
        '@router.post("/chat/ag-ui")\n'
        "get_runtime_settings().features.enable_ag_ui_bridge\n"
        "if request.tools or request.state or request.context:\n"
        "get_chat_runtime()\n",
        encoding="utf-8",
    )

    web = root / AUDITOR.WEB
    manifest = web / "package.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    dependencies = (
        {"@copilotkit/react-core": "1.70.2"}
        if copilot
        else {"@assistant-ui/react": "0.15.29"}
    )
    manifest.write_text(
        json.dumps({"dependencies": dependencies, "devDependencies": {}}),
        encoding="utf-8",
    )
    (web / "package-lock.json").write_text(
        json.dumps({"packages": {"node_modules/@ag-ui/client": {
            "version": "1.0.2" if copilot else "0.0.59",
        }}}),
        encoding="utf-8",
    )
    dashboard = web / "src/app/dashboard/page.tsx"
    dashboard.parent.mkdir(parents=True, exist_ok=True)
    selected = AUDITOR.COPILOT_MOUNT if copilot else AUDITOR.LEGACY_MOUNT
    dashboard.write_text(f'const mount = "{selected}";\n', encoding="utf-8")


def test_live_repository_has_single_owner_mount() -> None:
    result = AUDITOR.audit()
    # The staged consumer branch must not declare release readiness while the
    # retired assistant-ui packages and their second AG-UI client still exist.
    # Strict architecture violations are reported, never silently ignored.
    assert result["chat_mount"] in {"assistant-ui", "copilotkit"}
    if result["chat_mount"] == "copilotkit":
        manifest = json.loads(
            (AUDITOR.ROOT / AUDITOR.WEB / "package.json").read_text(encoding="utf-8")
        )
        dependencies = manifest.get("dependencies", {})
        legacy_present = any(
            package in dependencies
            for package in ("@assistant-ui/react", "@assistant-ui/react-ag-ui")
        )
        assert any(
            "Assistant-ui dependencies remain after primary cutover" in message
            for message in result["violations"]
        ) is legacy_present
        assert any(
            "requires one AG-UI client version" in message
            for message in result["violations"]
        ) is (len(result["ag_ui_client_versions"]) > 1)
    else:
        assert result["violations"] == []
    assert result["runtime_verification"] == "not_run"
    assert result["static_evidence_only"] is True
    assert result["schema_version"] == 2
    assert result["consumer_cutover"]["release_ready"] is False
    assert result["consumer_cutover"]["live_browser_acceptance"] == "not_run"
    assert result["consumer_cutover"]["active_renderer"] in {"assistant-ui", "copilotkit"}


def test_missing_runtime_authority_is_rejected(tmp_path: Path) -> None:
    fixture(tmp_path)
    (tmp_path / AUDITOR.OWNERS["approval_service"]).unlink()
    result = AUDITOR.audit(tmp_path)
    assert any("approval_service" in item for item in result["violations"])


def test_dual_chat_mount_is_rejected(tmp_path: Path) -> None:
    fixture(tmp_path)
    dashboard = tmp_path / AUDITOR.WEB / "src/app/dashboard/page.tsx"
    dashboard.write_text(
        AUDITOR.LEGACY_MOUNT + "\n" + AUDITOR.COPILOT_MOUNT,
        encoding="utf-8",
    )
    result = AUDITOR.audit(tmp_path)
    assert any("exactly one canonical chat mount" in item for item in result["violations"])


def test_development_only_agent_bypass_is_rejected(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    component = tmp_path / AUDITOR.WEB_SDK_ROOT / "KarenCopilotChat.tsx"
    component.parent.mkdir(parents=True, exist_ok=True)
    component.write_text(
        "const agents__unsafe_dev_only = {};\n", encoding="utf-8"
    )
    route = tmp_path / AUDITOR.WEB_GATEWAY / "[[...slug]]" / "route.ts"
    route.parent.mkdir(parents=True, exist_ok=True)
    route.write_text(
        'import { createCopilotRuntimeHandler } from "@copilotkit/runtime/v2";\n',
        encoding="utf-8",
    )
    result = AUDITOR.audit(tmp_path)
    assert any("Unapproved CopilotKit production shortcut" in x for x in result["violations"])


def test_cutover_with_old_ui_dependencies_is_rejected(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    manifest = tmp_path / AUDITOR.WEB / "package.json"
    manifest.write_text(
        json.dumps({"dependencies": {
            "@copilotkit/react-core": "1.70.2",
            "@assistant-ui/react": "0.15.29",
        }}),
        encoding="utf-8",
    )
    result = AUDITOR.audit(tmp_path)
    assert any("remain after primary cutover" in item for item in result["violations"])


def test_unversioned_runtime_adapter_is_rejected(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    route = tmp_path / AUDITOR.WEB_GATEWAY / "[[...slug]]" / "route.ts"
    route.parent.mkdir(parents=True, exist_ok=True)
    route.write_text('import { CopilotRuntime } from "@copilotkit/runtime";\n', encoding="utf-8")
    result = AUDITOR.audit(tmp_path)
    assert any("gateway must use the v2 runtime" in item for item in result["violations"])


def test_valid_copilotkit_static_fixture_remains_explicitly_unverified(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    route = tmp_path / AUDITOR.WEB_GATEWAY / "[[...slug]]" / "route.ts"
    route.parent.mkdir(parents=True, exist_ok=True)
    route.write_text(
        'import { CopilotRuntime } from "@copilotkit/runtime/v2";\n',
        encoding="utf-8",
    )
    result = AUDITOR.audit(tmp_path)
    assert result["violations"] == []
    assert result["chat_mount"] == "copilotkit"
    assert result["runtime_verification"] == "not_run"
    assert result["consumer_cutover"]["copilotkit_consumer_mounted"] is True
    assert result["consumer_cutover"]["release_ready"] is False
    assert result["consumer_cutover"]["human_ux_signoff"] == "not_run"


def test_legacy_mount_never_claims_copilotkit_consumer_cutover(tmp_path: Path) -> None:
    fixture(tmp_path)
    result = AUDITOR.audit(tmp_path)
    assert result["violations"] == []
    assert result["consumer_cutover"]["active_renderer"] == "assistant-ui"
    assert result["consumer_cutover"]["copilotkit_consumer_mounted"] is False
    assert result["consumer_cutover"]["release_ready"] is False


def test_duplicate_ag_ui_implementations_block_copilot_cutover(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    lock = tmp_path / AUDITOR.WEB / "package-lock.json"
    lock.write_text(
        json.dumps({"packages": {
            "node_modules/@ag-ui/client": {"version": "0.0.59"},
            "node_modules/@copilotkit/runtime/node_modules/@ag-ui/client": {
                "version": "1.0.2"
            },
        }}),
        encoding="utf-8",
    )
    result = AUDITOR.audit(tmp_path)
    assert result["ag_ui_client_versions"] == ["0.0.59", "1.0.2"]
    assert any(
        "requires one AG-UI client version" in message
        for message in result["violations"]
    )



def test_cutover_enforcement_rejects_legacy_consumer(tmp_path: Path) -> None:
    fixture(tmp_path)
    result = AUDITOR.audit(tmp_path, require_cutover=True)
    assert result["cutover_required"] is True
    assert result["consumer_cutover"]["active_renderer"] == "assistant-ui"
    assert any("dashboard still mounts assistant-ui" in item for item in result["violations"])
    assert result["consumer_cutover"]["release_ready"] is False


def test_cutover_enforcement_accepts_only_static_copilot_mount(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    route = tmp_path / AUDITOR.WEB_GATEWAY / "[[...slug]]" / "route.ts"
    route.parent.mkdir(parents=True, exist_ok=True)
    route.write_text('import { CopilotRuntime } from "@copilotkit/runtime/v2";\n', encoding="utf-8")
    result = AUDITOR.audit(tmp_path, require_cutover=True)
    assert result["cutover_required"] is True
    assert result["violations"] == []
    assert result["consumer_cutover"]["active_renderer"] == "copilotkit"
    assert result["consumer_cutover"]["release_ready"] is False
    assert result["runtime_verification"] == "not_run"


def test_cutover_enforcement_rejects_missing_chat_mount(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    dashboard = tmp_path / AUDITOR.WEB / "src/app/dashboard/page.tsx"
    dashboard.write_text("export default function Dashboard() { return null; }\n", encoding="utf-8")
    result = AUDITOR.audit(tmp_path, require_cutover=True)
    assert any("CopilotKit is not the active renderer" in item for item in result["violations"])



def test_strict_cutover_rejects_temporary_ag_ui_alias(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    manifest = tmp_path / AUDITOR.WEB / "package.json"
    manifest.write_text(
        json.dumps({"dependencies": {
            "@copilotkit/react-core": "1.79.1",
            "@ag-ui/client-v1": "npm:@ag-ui/client@1.0.2",
        }, "devDependencies": {}}),
        encoding="utf-8",
    )
    result = AUDITOR.audit(tmp_path, require_cutover=True)
    assert any(
        "Temporary AG-UI client-v1 alias" in item
        for item in result["violations"]
    )
    # The default inventory mode remains informative during migration.
    inventory = AUDITOR.audit(tmp_path)
    assert not any(
        "Temporary AG-UI client-v1 alias" in item
        for item in inventory["violations"]
    )


def test_strict_cutover_rejects_legacy_import_inside_copilotkit(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    component = tmp_path / AUDITOR.WEB_SDK_ROOT / "KarenCopilotChat.tsx"
    component.parent.mkdir(parents=True, exist_ok=True)
    component.write_text(
        'import { KarenPersonaSelector } from "../assistant-ui/KarenPersonaSelector";\\n',
        encoding="utf-8",
    )
    route = tmp_path / AUDITOR.WEB_GATEWAY / "[[...slug]]" / "route.ts"
    route.parent.mkdir(parents=True, exist_ok=True)
    route.write_text(
        'import { CopilotRuntime } from "@copilotkit/runtime/v2";\\n',
        encoding="utf-8",
    )
    result = AUDITOR.audit(tmp_path, require_cutover=True)
    assert any(
        "CopilotKit production path imports retired assistant-ui" in item
        for item in result["violations"]
    )


def test_declared_ag_ui_version_must_match_root_lock_and_installed_version(
    tmp_path: Path,
) -> None:
    fixture(tmp_path, copilot=True)
    manifest = tmp_path / AUDITOR.WEB / "package.json"
    manifest.write_text(
        json.dumps({"dependencies": {
            "@copilotkit/react-core": "1.79.1",
            "@ag-ui/client": "1.0.2",
        }}),
        encoding="utf-8",
    )
    lock = tmp_path / AUDITOR.WEB / "package-lock.json"
    for direct, installed in [("0.0.59", "1.0.2"), ("1.0.2", "0.0.59")]:
        lock.write_text(
            json.dumps({"packages": {
                "": {"dependencies": {"@ag-ui/client": direct}},
                "node_modules/@ag-ui/client": {"version": installed},
            }}),
            encoding="utf-8",
        )
        result = AUDITOR.audit(tmp_path, require_cutover=True)
        assert any(
            "Canonical AG-UI client manifest and lockfile disagree" in item
            for item in result["violations"]
        )

    lock.write_text(
        json.dumps({"packages": {
            "": {"dependencies": {"@ag-ui/client": "1.0.2"}},
            "node_modules/@ag-ui/client": {"version": "1.0.2"},
        }}),
        encoding="utf-8",
    )
    result = AUDITOR.audit(tmp_path)
    assert not any(
        "Canonical AG-UI client manifest and lockfile disagree" in item
        for item in result["violations"]
    )


def test_strict_cutover_finds_legacy_caller_outside_chat_tree(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    route = tmp_path / AUDITOR.WEB_GATEWAY / "[[...slug]]" / "route.ts"
    route.parent.mkdir(parents=True, exist_ok=True)
    route.write_text(
        'import { CopilotRuntime } from "@copilotkit/runtime/v2";\n',
        encoding="utf-8",
    )
    caller = tmp_path / AUDITOR.WEB / "src/app/settings/old-chat.tsx"
    caller.parent.mkdir(parents=True, exist_ok=True)
    caller.write_text(
        'import Legacy from "@/components/chat/assistant-ui/KarenAssistantChat";\n',
        encoding="utf-8",
    )
    result = AUDITOR.audit(tmp_path, require_cutover=True)
    assert result["legacy_import_callers"] == [
        str(caller.relative_to(tmp_path))
    ]
    assert any(
        "Retired assistant-ui is still imported by production source" in item
        for item in result["violations"]
    )


def test_compatibility_facade_is_not_a_production_caller(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    legacy = (tmp_path / AUDITOR.WEB /
              "src/components/chat/assistant-ui/KarenPersonaSelector.tsx")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        'export * from "../persona/KarenPersonaSelector";\n',
        encoding="utf-8",
    )
    result = AUDITOR.audit(tmp_path)
    assert result["legacy_import_callers"] == []


def test_strict_cutover_refuses_retired_renderer_file(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    legacy = tmp_path / AUDITOR.WEB / (
        "src/components/chat/assistant-ui/KarenAssistantChat.tsx"
    )
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("export default function OldRenderer() {}\\n", encoding="utf-8")
    result = AUDITOR.audit(tmp_path, require_cutover=True)
    assert any(
        "Retired assistant-ui renderer source still exists" in issue
        for issue in result["violations"]
    )


def test_legacy_packages_still_in_lock_block_cutover(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    route = tmp_path / AUDITOR.WEB_GATEWAY / "[[...slug]]" / "route.ts"
    route.parent.mkdir(parents=True, exist_ok=True)
    route.write_text(
        'import { CopilotRuntime } from "@copilotkit/runtime/v2";\n',
        encoding="utf-8",
    )
    lock = tmp_path / AUDITOR.WEB / "package-lock.json"
    lock.write_text(json.dumps({"packages": {
        "": {"dependencies": {"@assistant-ui/react": "0.15.29"}},
        "node_modules/@assistant-ui/react": {"version": "0.15.29"},
        "node_modules/@ag-ui/client": {"version": "1.0.2"},
    }}), encoding="utf-8")
    result = AUDITOR.audit(tmp_path, require_cutover=True)
    assert any(
        "Retired assistant-ui packages remain in committed npm lock" in issue
        for issue in result["violations"]
    )


def test_stale_ag_ui_protocol_module_blocks_cutover_even_with_one_client_version(
    tmp_path: Path,
) -> None:
    fixture(tmp_path, copilot=True)
    lock = tmp_path / AUDITOR.WEB / "package-lock.json"
    lock.write_text(json.dumps({"packages": {
        "node_modules/@ag-ui/client": {"version": "1.0.2"},
        "node_modules/@ag-ui/core": {"version": "0.0.59"},
        "node_modules/@ag-ui/encoder": {"version": "1.0.2"},
        "node_modules/@ag-ui/proto": {"version": "1.0.2"},
    }}), encoding="utf-8")
    bad = AUDITOR.audit(tmp_path, require_cutover=True)
    assert bad["ag_ui_client_versions"] == ["1.0.2"]
    assert bad["ag_ui_protocol_versions"] == ["0.0.59", "1.0.2"]
    assert any(
        "requires one AG-UI protocol generation" in issue
        for issue in bad["violations"]
    )

    lock.write_text(json.dumps({"packages": {
        "node_modules/@ag-ui/client": {"version": "1.0.2"},
        "node_modules/@ag-ui/core": {"version": "1.0.2"},
        "node_modules/@ag-ui/encoder": {"version": "1.0.2"},
        "node_modules/@ag-ui/proto": {"version": "1.0.2"},
    }}), encoding="utf-8")
    good = AUDITOR.audit(tmp_path, require_cutover=True)
    assert good["ag_ui_protocol_versions"] == ["1.0.2"]
    assert not any(
        "requires one AG-UI protocol generation" in issue
        for issue in good["violations"]
    )


def test_ag_ui_lock_dependency_edge_rejects_stale_or_missing_protocol(
    tmp_path: Path,
) -> None:
    fixture(tmp_path, copilot=True)
    lock = tmp_path / AUDITOR.WEB / "package-lock.json"
    for encoder_edge in ("0.0.59", "1.0.2"):
        packages = {
            "node_modules/@ag-ui/client": {
                "version": "1.0.2",
                "dependencies": {"@ag-ui/encoder": encoder_edge},
            },
            "node_modules/@ag-ui/encoder": {"version": "1.0.2"},
        }
        lock.write_text(json.dumps({"packages": packages}), encoding="utf-8")
        observed = AUDITOR.audit(tmp_path, require_cutover=True)
        assert any(
            "AG-UI protocol lock dependency edge is unresolved" in issue
            for issue in observed["violations"]
        ) is (encoder_edge != "1.0.2")

    lock.write_text(json.dumps({"packages": {
        "node_modules/@ag-ui/client": {
            "version": "1.0.2",
            "dependencies": {"@ag-ui/proto": "1.0.2"},
        },
    }}), encoding="utf-8")
    missing = AUDITOR.audit(tmp_path, require_cutover=True)
    assert any(
        "AG-UI protocol lock dependency edge is unresolved" in issue
        for issue in missing["violations"]
    )


def test_ag_ui_lock_nearest_nested_protocol_dependency_is_valid(tmp_path: Path) -> None:
    fixture(tmp_path, copilot=True)
    lock = tmp_path / AUDITOR.WEB / "package-lock.json"
    lock.write_text(json.dumps({"packages": {
        "node_modules/@ag-ui/client": {"version": "1.0.2"},
        "node_modules/@ag-ui/core": {"version": "1.0.2"},
        "node_modules/@copilotkit/runtime": {
            "version": "1.79.1",
            "dependencies": {"@ag-ui/core": "1.0.2"},
        },
        "node_modules/@copilotkit/runtime/node_modules/@ag-ui/core": {
            "version": "1.0.2",
        },
    }}), encoding="utf-8")
    result = AUDITOR.audit(tmp_path, require_cutover=True)
    assert not any(
        "AG-UI protocol lock dependency edge is unresolved" in issue
        for issue in result["violations"]
    )

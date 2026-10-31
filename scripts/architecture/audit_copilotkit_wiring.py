"""Static ownership and migration wiring checks for Karen's CopilotKit cutover.

This tool deliberately makes no claim that installed SDKs, live providers,
database writes, user sessions, or UI interactions have been tested.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WEB = Path("src/ui_launchers/Karen-AI-Theme")
LEGACY_MOUNT = '@/components/chat/assistant-ui/KarenAssistantChat'
COPILOT_MOUNT = '@/components/chat/copilotkit/KarenCopilotConsumerChat'

OWNERS = {
    "runtime": "src/ai_karen_engine/core/runtime/chat_runtime.py",
    "ag_ui_ingress": "src/ai_karen_engine/api_routes/chat/runtime.py",
    "ag_ui_projection": "src/ai_karen_engine/core/runtime/ag_ui_event_projection.py",
    "runtime_config": "src/ai_karen_engine/config/runtime.py",
    "extension_kernel": "src/ai_karen_engine/extensions/plugin_kernel.py",
    "channel_contract": "src/ai_karen_engine/extensions/channels/contracts.py",
    "channel_host": "src/ai_karen_engine/services/channels/host.py",
    "channel_ingress": "src/ai_karen_engine/services/channels/ingress.py",
    "channel_execution": "src/ai_karen_engine/services/channels/execution.py",
    "channel_store": "src/ai_karen_engine/persistence/repositories/channel_repository.py",
    "channel_config": "src/ai_karen_engine/config/channels.py",
    "approval_service": "src/ai_karen_engine/services/approvals.py",
    "approval_store": "src/ai_karen_engine/persistence/repositories/approval_repository.py",
    "web_ag_ui_proxy": str(WEB / "src/app/api/chat/ag-ui/route.ts"),
    "web_sessions": str(WEB / "src/components/chat/SessionProvider.tsx"),
    "web_design_tokens": str(WEB / "src/app/globals.css"),
}

WEB_SDK_ROOT = WEB / "src/components/chat/copilotkit"
WEB_GATEWAY = WEB / "src/app/api/copilotkit"
FORBIDDEN_NEW_SDK_TOKENS = (
    "agents__unsafe_dev_only",
    "publicApiKey=",
    "new InMemoryAgentRunner(",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _new_sdk_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for subdir in (WEB_SDK_ROOT, WEB_GATEWAY):
        directory = root / subdir
        if directory.is_dir():
            files.extend(
                path for path in directory.rglob("*")
                if path.is_file() and path.suffix in {".ts", ".tsx", ".js", ".jsx"}
            )
    return sorted(files)


def audit(root: Path = ROOT, *, require_cutover: bool = False) -> dict[str, Any]:
    """Return a reproducible report with distinct observation and violation lists."""
    evidence = {name: (root / path).is_file() for name, path in OWNERS.items()}
    violations: list[str] = []
    warnings: list[str] = []
    for name, present in evidence.items():
        if not present:
            violations.append(f"Missing canonical owner: {name}: {OWNERS[name]}")

    manifest = root / WEB / "package.json"
    dependencies: dict[str, str] = {}
    if not manifest.is_file():
        violations.append(f"Missing web package manifest: {manifest.relative_to(root)}")
    else:
        try:
            data = json.loads(_read(manifest))
            for section in ("dependencies", "devDependencies"):
                values = data.get(section, {})
                if not isinstance(values, dict):
                    raise ValueError(f"{section} must be an object")
                dependencies.update(
                    (name, version)
                    for name, version in values.items()
                    if isinstance(version, str)
                )
        except (ValueError, OSError) as exc:
            violations.append(f"Invalid web package manifest: {exc}")

    dashboard_path = root / WEB / "src/app/dashboard/page.tsx"
    dashboard = _read(dashboard_path) if dashboard_path.is_file() else ""
    if not dashboard:
        violations.append("Missing active dashboard")
    legacy_mount = LEGACY_MOUNT in dashboard
    copilot_mount = COPILOT_MOUNT in dashboard
    if legacy_mount == copilot_mount:
        violations.append(
            "Dashboard must reference exactly one canonical chat mount "
            "(legacy or CopilotKit). A second render path is not allowed."
        )

    copilot_installed = "@copilotkit/react-core" in dependencies
    if "@copilotkit/react-ui" in dependencies:
        violations.append("Legacy CopilotKit v1 react-ui is not permitted")
    if copilot_mount and not copilot_installed:
        violations.append("CopilotKit chat mounted without the v2 React package")
    if copilot_mount and any(
        name in dependencies
        for name in ("@assistant-ui/react", "@assistant-ui/react-ag-ui")
    ):
        violations.append("Assistant-ui dependencies remain after primary cutover")
    if require_cutover and "@ag-ui/client-v1" in dependencies:
        violations.append("Temporary AG-UI client-v1 alias remains after consumer cutover")

    runtime_config = root / OWNERS["runtime_config"]
    if runtime_config.is_file() and "enable_ag_ui_bridge" not in _read(runtime_config):
        violations.append("Canonical AG-UI feature gate missing")
    ingress = root / OWNERS["ag_ui_ingress"]
    if ingress.is_file():
        content = _read(ingress)
        required = (
            '@router.post("/chat/ag-ui")',
            "get_runtime_settings().features.enable_ag_ui_bridge",
            "if request.tools or request.state or request.context:",
            "get_chat_runtime()",
        )
        for required_token in required:
            if required_token not in content:
                violations.append(f"Canonical AG-UI ingress contract missing: {required_token}")

    gateway_files = _new_sdk_files(root)
    for path in gateway_files:
        source = _read(path)
        for token in FORBIDDEN_NEW_SDK_TOKENS:
            if token in source:
                violations.append(
                    f"Unapproved CopilotKit production shortcut: "
                    f"{path.relative_to(root)}: {token}"
                )

    if copilot_installed:
        if not gateway_files:
            warnings.append("CopilotKit declared but no canonical adapter or gateway exists")
        else:
            runtime_routes = [
                p for p in gateway_files
                if p.relative_to(root).parts[:len(WEB_GATEWAY.parts)] == WEB_GATEWAY.parts
                and p.name == "route.ts"
            ]
            for route in runtime_routes:
                content = _read(route)
                if "@copilotkit/runtime/v2" not in content:
                    violations.append(
                        f"CopilotKit gateway must use the v2 runtime handler: "
                        f"{route.relative_to(root)}"
                    )
    else:
        warnings.append("CopilotKit v2 React package not declared: migration not installed")

    # Cutover must not keep runtime dependencies on the retired UI framework.
    # Restrict this check to production CopilotKit code, not migration tests or
    # compatibility shims whose removal is tracked separately.
    if require_cutover and copilot_mount:
        for path in gateway_files:
            source = _read(path)
            if any(token in source for token in (
                'from "@assistant-ui/', "from '@assistant-ui/",
                'import("@assistant-ui/', "import('@assistant-ui/",
                'from "../assistant-ui/Karen', "from '../assistant-ui/Karen",
                'from "@/components/chat/assistant-ui/',
                "from '@/components/chat/assistant-ui/",
            )):
                violations.append(
                    "CopilotKit production path imports retired assistant-ui: "
                    + str(path.relative_to(root))
                )

    retired_renderer = root / WEB / "src/components/chat/assistant-ui/KarenAssistantChat.tsx"
    if require_cutover and copilot_mount and retired_renderer.is_file():
        violations.append(
            "Retired assistant-ui renderer source still exists after consumer cutover"
        )

    # Inspect *all* production frontend sources before deleting the retired
    # renderer. A missing import from a different route must block cutover too.
    # Existing legacy compatibility files are accounted for by the dependency
    # gate and are deliberately excluded from the caller search.
    legacy_import_callers: list[str] = []
    frontend_source = root / WEB / "src"
    retired_dir = root / WEB / "src/components/chat/assistant-ui"
    if frontend_source.is_dir():
        for source_path in sorted(frontend_source.rglob("*")):
            if not source_path.is_file() or source_path.suffix not in {
                ".ts", ".tsx", ".js", ".jsx",
            }:
                continue
            if source_path.is_relative_to(retired_dir):
                continue
            source = _read(source_path)
            if any(token in source for token in (
                'from "@/components/chat/assistant-ui/',
                "from '@/components/chat/assistant-ui/",
                'from "../assistant-ui/',
                "from '../assistant-ui/",
                'from "@assistant-ui/',
                "from '@assistant-ui/",
                'import("@assistant-ui/',
                "import('@assistant-ui/",
                'KarenAssistantChat',
            )):
                legacy_import_callers.append(str(source_path.relative_to(root)))
    if require_cutover and copilot_mount and legacy_import_callers:
        violations.extend(
            "Retired assistant-ui is still imported by production source: "
            + caller
            for caller in legacy_import_callers
        )

    # Tests are part of the active quality contract. Importing a physically
    # deleted adapter from a test must fail before Vitest module collection.
    # Search actual import/require statements, not descriptions documenting the
    # historical migration or negative "not.toContain" assertions.
    retired_test_imports: list[str] = []
    frontend_tests = root / WEB / "tests"
    if frontend_tests.is_dir():
        for test_path in sorted(frontend_tests.rglob("*")):
            if not test_path.is_file() or test_path.suffix not in {
                ".ts", ".tsx", ".js", ".jsx",
            }:
                continue
            test_source = _read(test_path)
            for line in test_source.splitlines():
                stripped = line.strip()
                if (
                    stripped.startswith("import ")
                    or stripped.startswith("export ")
                    or stripped.startswith("const ") and "require(" in stripped
                ) and (
                    "/assistant-ui/" in stripped
                    or "from \"@assistant-ui/" in stripped
                    or "from '@assistant-ui/" in stripped
                    or "require(\"@assistant-ui/" in stripped
                    or "require('@assistant-ui/" in stripped
                ):
                    retired_test_imports.append(str(test_path.relative_to(root)))
                    break
    if require_cutover and copilot_mount and retired_test_imports:
        violations.extend(
            "Retired assistant-ui is imported by frontend test: " + caller
            for caller in retired_test_imports
        )

    lock_path = root / WEB / "package-lock.json"
    ag_ui_client_versions: dict[str, str] = {}
    ag_ui_family_versions: dict[str, str] = {}
    if lock_path.is_file():
        try:
            lock = json.loads(_read(lock_path))
            packages = lock.get("packages", {})
            if not isinstance(packages, dict):
                raise ValueError("packages must be an object")
            for package_path, metadata in packages.items():
                if (
                    isinstance(package_path, str)
                    and isinstance(metadata, dict)
                    and isinstance(metadata.get("version"), str)
                    and (
                        package_path.startswith("node_modules/@ag-ui/")
                        or "/node_modules/@ag-ui/" in package_path
                    )
                ):
                    family_name = package_path.rsplit("/@ag-ui/", 1)[-1]
                    if family_name in {"client", "core", "encoder", "proto"}:
                        ag_ui_family_versions[package_path] = metadata["version"]
                if (
                    isinstance(package_path, str)
                    and (package_path == "node_modules/@ag-ui/client"
                         or package_path.endswith("/node_modules/@ag-ui/client"))
                    and isinstance(metadata, dict)
                    and isinstance(metadata.get("version"), str)
                ):
                    ag_ui_client_versions[package_path] = metadata["version"]
        except (OSError, ValueError) as exc:
            violations.append(f"AG-UI dependency lockfile is unreadable: {exc}")
    elif copilot_installed:
        violations.append("CopilotKit dependency declared without a committed package-lock.json")

    # A direct runtime import can be resolved differently from what a stale
    # root package-lock claims. Compare only declared dependencies so that
    # historical minimal fixtures without a pinned direct client remain valid.
    if lock_path.is_file() and dependencies.get("@ag-ui/client"):
        try:
            lock_data = json.loads(_read(lock_path))
            lock_packages = lock_data.get("packages", {})
            root_packages = lock_packages.get("", {})
            lock_dependencies = root_packages.get("dependencies", {})
            declared = dependencies["@ag-ui/client"]
            installed = lock_packages.get("node_modules/@ag-ui/client", {})
            if (lock_dependencies.get("@ag-ui/client") != declared
                    or installed.get("version") != declared):
                violations.append(
                    "Canonical AG-UI client manifest and lockfile disagree"
                )
        except (TypeError, AttributeError, ValueError, OSError) as exc:
            violations.append(f"Canonical AG-UI dependency verification failed: {exc}")

    # Removed UI packages must also be absent from the committed lock, not
    # merely omitted from package.json while npm still installs their graph.
    if copilot_mount and lock_path.is_file():
        try:
            lock_data = json.loads(_read(lock_path))
            lock_packages = lock_data.get("packages", {})
            if not isinstance(lock_packages, dict):
                raise ValueError("Invalid packages mapping")
            retired = [
                key for key in lock_packages
                if isinstance(key, str) and (
                    key.startswith("node_modules/@assistant-ui/")
                    or "/node_modules/@assistant-ui/" in key
                )
            ]
            lock_root = lock_packages.get("", {})
            lock_root_deps = lock_root.get("dependencies", {})
            if any(key in lock_root_deps for key in (
                "@assistant-ui/react", "@assistant-ui/react-ag-ui",
            )):
                retired.append("root dependencies")
            if retired:
                violations.append(
                    "Retired assistant-ui packages remain in committed npm lock: "
                    + ", ".join(sorted(retired)[:10])
                )
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            violations.append(f"Retired npm package audit failed: {exc}")

    # Validate every locked AG-UI protocol dependency edge against npm's
    # nearest node_modules resolution path. Matching package versions alone do
    # not prove that the dependency graph is satisfiable after manual pruning.
    if copilot_mount and lock_path.is_file():
        try:
            edge_packages = json.loads(_read(lock_path)).get("packages", {})
            protocol_names = {
                "@ag-ui/client", "@ag-ui/core",
                "@ag-ui/encoder", "@ag-ui/proto",
            }
            if not isinstance(edge_packages, dict):
                raise ValueError("Invalid npm package map")
            for package_path, metadata in edge_packages.items():
                if not isinstance(package_path, str) or not isinstance(metadata, dict):
                    continue
                edges = metadata.get("dependencies", {})
                if not isinstance(edges, dict):
                    raise ValueError("Invalid npm dependency edges")
                for dependency, required_version in edges.items():
                    if dependency not in protocol_names:
                        continue
                    location = package_path
                    resolved = None
                    while location:
                        nested = location + "/node_modules/" + dependency
                        if nested in edge_packages:
                            resolved = nested
                            break
                        boundary = location.rfind("/node_modules/")
                        location = location[:boundary] if boundary >= 0 else ""
                    if resolved is None:
                        root_dependency = "node_modules/" + dependency
                        if root_dependency in edge_packages:
                            resolved = root_dependency
                    if resolved is None or (
                        edge_packages[resolved].get("version") != required_version
                    ):
                        violations.append(
                            "AG-UI protocol lock dependency edge is unresolved: "
                            + package_path + " -> " + dependency
                        )
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            violations.append(f"AG-UI protocol edge audit failed: {exc}")

    # Every AG-UI protocol module must match, not just the HttpAgent client.
    # A stale root core/encoder/proto can survive dependency pruning and
    # silently reintroduce a second protocol generation.
    ag_ui_protocol_versions = sorted(set(ag_ui_family_versions.values()))
    if copilot_mount and len(ag_ui_protocol_versions) > 1:
        violations.append(
            "CopilotKit cutover requires one AG-UI protocol generation; found "
            + ", ".join(ag_ui_protocol_versions)
        )

    unique_client_versions = sorted(set(ag_ui_client_versions.values()))
    if copilot_installed and len(unique_client_versions) > 1:
        if copilot_mount:
            violations.append(
                "CopilotKit chat cutover requires one AG-UI client version; "
                f"found {', '.join(unique_client_versions)}"
            )
        else:
            warnings.append(
                "Migration-only duplicate AG-UI versions; do not merge as consumer-ready: "
                + ", ".join(unique_client_versions)
            )

    if legacy_mount:
        warnings.append("Assistant-ui still owns the consumer chat mount")
        if require_cutover:
            violations.append("Consumer cutover required: dashboard still mounts assistant-ui")
    if require_cutover and not copilot_mount:
        violations.append("Consumer cutover required: CopilotKit is not the active renderer")
    if not (root / WEB_GATEWAY).exists():
        warnings.append("CopilotKit production runtime gateway not installed")

    # Static SDK or acceptance-preview presence is not consumer cutover proof.
    consumer_cutover = {
        "consumer_entry": str(WEB / "src/app/dashboard/page.tsx"),
        "active_renderer": (
            "copilotkit" if copilot_mount else
            "assistant-ui" if legacy_mount else "unknown"
        ),
        "copilotkit_consumer_mounted": bool(copilot_mount and not legacy_mount),
        "copilotkit_sdk_declared": copilot_installed,
        "live_browser_acceptance": "not_run",
        "model_and_persona_acceptance": "not_run",
        "rich_history_replay_acceptance": "not_run",
        "human_ux_signoff": "not_run",
        "release_ready": False,
    }

    return {
        "schema_version": 2,
        "consumer_cutover": consumer_cutover,
        "static_evidence_only": True,
        "cutover_required": require_cutover,
        "runtime_verification": "not_run",
        "owners": evidence,
        "chat_mount": "copilotkit" if copilot_mount else "assistant-ui" if legacy_mount else "unknown",
        "sdk_dependency_declared": copilot_installed,
        "new_sdk_files_checked": len(gateway_files),
        "legacy_import_callers": legacy_import_callers,
        "retired_test_imports": retired_test_imports,
        "ag_ui_client_versions": unique_client_versions,
        "ag_ui_protocol_versions": ag_ui_protocol_versions,
        "violations": sorted(set(violations)),
        "warnings": sorted(set(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable evidence")
    parser.add_argument(
        "--require-cutover", action="store_true",
        help="Fail when assistant-ui still owns the dashboard; does not certify runtime or UX",
    )
    args = parser.parse_args()
    result = audit(args.root.resolve(), require_cutover=args.require_cutover)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for warning in result["warnings"]:
            print(f"UNVERIFIED: {warning}")
        for violation in result["violations"]:
            print(f"VIOLATION: {violation}")
        cutover = result["consumer_cutover"]
        print(
            f"CONSUMER MOUNT: {cutover['active_renderer']}; "
            "CopilotKit browser/human acceptance NOT VERIFIED."
        )
        if not result["violations"]:
            print("Static ownership contracts passed; consumer release NOT VERIFIED.")
    return 1 if result["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

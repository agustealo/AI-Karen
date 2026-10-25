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
COPILOT_MOUNT = '@/components/chat/copilotkit/KarenCopilotChat'

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


def audit(root: Path = ROOT) -> dict[str, Any]:
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

    lock_path = root / WEB / "package-lock.json"
    ag_ui_client_versions: dict[str, str] = {}
    if lock_path.is_file():
        try:
            lock = json.loads(_read(lock_path))
            packages = lock.get("packages", {})
            if not isinstance(packages, dict):
                raise ValueError("packages must be an object")
            for package_path, metadata in packages.items():
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
    if not (root / WEB_GATEWAY).exists():
        warnings.append("CopilotKit production runtime gateway not installed")

    return {
        "schema_version": 1,
        "static_evidence_only": True,
        "runtime_verification": "not_run",
        "owners": evidence,
        "chat_mount": "copilotkit" if copilot_mount else "assistant-ui" if legacy_mount else "unknown",
        "sdk_dependency_declared": copilot_installed,
        "new_sdk_files_checked": len(gateway_files),
        "ag_ui_client_versions": unique_client_versions,
        "violations": sorted(set(violations)),
        "warnings": sorted(set(warnings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable evidence")
    args = parser.parse_args()
    result = audit(args.root.resolve())
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for warning in result["warnings"]:
            print(f"UNVERIFIED: {warning}")
        for violation in result["violations"]:
            print(f"VIOLATION: {violation}")
        if not result["violations"]:
            print("Static ownership contracts passed; live CopilotKit integration NOT verified.")
    return 1 if result["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

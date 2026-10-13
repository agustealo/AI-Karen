#!/usr/bin/env python3
"""Read-only API environment diagnostic. Run inside the API container.

No secret contents, auth tokens, or permission grants are printed.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def dependency(name: str, module: str) -> bool:
    try:
        installed = version(name)
    except PackageNotFoundError:
        installed = None
    try:
        importlib.import_module(module)
        importable = True
    except (ImportError, OSError, RuntimeError, ValueError):
        importable = False
    print(json.dumps({"check": "dependency", "package": name, "installed_version": installed, "module_available": importable}))
    return bool(installed and importable)


def permissions() -> bool:
    override = os.getenv("KARI_PERMISSIONS_CONFIG") or os.getenv("PERMISSIONS_CONFIG_PATH")
    source = Path(override) if override else Path("config_assets/permissions.json")
    if not source.is_file():
        print(json.dumps({"check": "rbac_source", "source_kind": "override" if override else "canonical", "available": False}))
        return False
    try:
        parsed = json.loads(source.read_text(encoding="utf-8"))
        roles = parsed.get("roles", parsed.get("role_permissions", {}))
        if not isinstance(roles, dict):
            raise ValueError("roles must be an object")
        invalid_role_tokens = sorted({
            token for entry in roles.values() if isinstance(entry, dict)
            for token in entry.get("permissions", []) if token in {"admin", "user"}
        })
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"check": "rbac_source", "source_kind": "override" if override else "canonical", "valid": False, "error_type": type(exc).__name__}))
        return False
    print(json.dumps({"check": "rbac_source", "source_kind": "override" if override else "canonical", "valid": True, "role_names_used_as_permissions": invalid_role_tokens}))
    return not invalid_role_tokens


def main() -> int:
    print(json.dumps({"check": "interpreter", "python": sys.version.split()[0], "working_directory": str(Path.cwd())}))
    crawler_ok = dependency("crawl4ai", "crawl4ai")
    browser_ok = dependency("playwright", "playwright")
    supabase_ok = dependency("supabase", "supabase")
    rbac_ok = permissions()
    print(json.dumps({"check": "summary", "crawler_deps_ready": crawler_ok and browser_ok, "supabase_sdk_ready": supabase_ok, "rbac_config_ready": rbac_ok}))
    return 0 if crawler_ok and browser_ok and supabase_ok and rbac_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

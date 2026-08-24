#!/usr/bin/env python3
"""
Check for any runtime errors or issues with the web-search plugin.
"""

import json
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def check_plugin_directories():
    """Check plugin directories and their structure."""
    print("Checking Plugin Directory Structure")
    print("=" * 50)

    extensions_dir = Path("src/ai_karen_engine/extensions/plugins")

    if not extensions_dir.exists():
        print(f"✗ Extensions directory not found: {extensions_dir}")
        return

    print(f"✓ Extensions directory found: {extensions_dir}")

    # List all plugin directories
    plugin_dirs = []
    for item in extensions_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            plugin_dirs.append(item)

    print(f"Found {len(plugin_dirs)} plugin directories:")

    for plugin_dir in plugin_dirs:
        print(f"\n📁 Plugin: {plugin_dir.name}")

        # Check for manifest files
        manifest_files = []
        for manifest_name in ["plugin_manifest.json", "manifest.json"]:
            manifest_file = plugin_dir / manifest_name
            if manifest_file.exists():
                manifest_files.append(manifest_file)

        if manifest_files:
            print(f"  📄 Manifest files: {[f.name for f in manifest_files]}")

            # Load and check the first manifest (priority order)
            manifest_file = manifest_files[0]
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)

                print(f"  ✓ Plugin name: {manifest_data.get('name', 'Unknown')}")
                print(f"  ✓ Version: {manifest_data.get('version', 'Unknown')}")

                # Check entrypoint
                entrypoint = manifest_data.get("entrypoint")
                if entrypoint:
                    print(f"  ✓ Entrypoint: {entrypoint}")
                else:
                    print(f"  ⚠ No entrypoint specified")

                # Check handler file
                handler_file = plugin_dir / "handler.py"
                if handler_file.exists():
                    print(f"  ✓ Handler file: handler.py")

                    # Check for MainExtension class
                    with open(handler_file, "r", encoding="utf-8") as f:
                        handler_content = f.read()

                    if "class MainExtension" in handler_content:
                        print(f"  ✓ MainExtension class found")
                    else:
                        print(f"  ✗ MainExtension class not found")
                else:
                    print(f"  ✗ Handler file missing: handler.py")

            except Exception as e:
                print(f"  ✗ Error reading manifest: {e}")
        else:
            print(f"  ✗ No manifest files found")


def check_handler_imports():
    """Check if handler files can be imported."""
    print(f"\n{'=' * 50}")
    print("Checking Handler File Imports")
    print(f"{'=' * 50}")

    extensions_dir = Path("src/ai_karen_engine/extensions/plugins")

    for plugin_dir in extensions_dir.iterdir():
        if plugin_dir.is_dir() and not plugin_dir.name.startswith("_"):
            handler_file = plugin_dir / "handler.py"

            if handler_file.exists():
                print(f"\n🔍 Checking imports for {plugin_dir.name}")

                try:
                    # Read the handler file
                    with open(handler_file, "r", encoding="utf-8") as f:
                        content = f.read()

                    # Check for import issues
                    import_lines = [
                        line
                        for line in content.split("\n")
                        if line.strip().startswith("from ")
                        or line.strip().startswith("import ")
                    ]

                    if import_lines:
                        print(f"  📦 Imports found:")
                        for line in import_lines[:5]:  # Show first 5 imports
                            print(f"    {line}")
                        if len(import_lines) > 5:
                            print(f"    ... and {len(import_lines) - 5} more")
                    else:
                        print(f"  ℹ️  No explicit imports found")

                    # Check for MainExtension class
                    if "class MainExtension" in content:
                        print(f"  ✓ MainExtension class found")

                        # Check if it inherits from ExtensionBase
                        if (
                            "class MainExtension" in content
                            and "ExtensionBase" in content
                        ):
                            print(f"  ✓ MainExtension inherits from ExtensionBase")
                        else:
                            print(
                                f"  ⚠ MainExtension may not inherit from ExtensionBase"
                            )
                    else:
                        print(f"  ✗ MainExtension class not found")

                except Exception as e:
                    print(f"  ✗ Error reading handler file: {e}")


def main():
    """Main function."""
    check_plugin_directories()
    check_handler_imports()

    print(f"\n{'=' * 50}")
    print("SUMMARY")
    print(f"{'=' * 50}")
    print("If the web-search plugin is not being discovered, the issue could be:")
    print("1. Missing or invalid manifest file")
    print("2. Missing handler.py file")
    print("3. Missing MainExtension class in handler.py")
    print("4. Import errors in handler.py")
    print("5. Issues with the plugin service initialization")
    print(
        "6. Category validation issues (web-search uses 'plugins' which is non-standard)"
    )


if __name__ == "__main__":
    main()

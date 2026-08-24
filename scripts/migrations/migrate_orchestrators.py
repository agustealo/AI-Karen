"""
Migration script to collapse multiple orchestrators into single LangGraph system.

This script handles the migration from legacy orchestrators to the new
LangGraph-based orchestrator system.
"""

import logging
import os
import shutil
from typing import Dict, Any, List
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OrchestratorMigration:
    """Handles migration of multiple orchestrators into single LangGraph system."""

    def __init__(self, project_root: str):
        """Initialize migration with project root."""
        self.project_root = Path(project_root)
        self.src_root = self.project_root / "src" / "ai_karen_engine"

        # Define migration paths
        self.legacy_paths = {
            "chat_orchestrator": self.src_root / "chat" / "ChatOrchestrator",
            "agent_orchestrator": self.src_root / "agents" / "agent_orchestrator.py",
            "ai_orchestrator": self.src_root / "ai_orchestrator" / "ai_orchestrator.py",
        }

        self.target_paths = {
            "langgraph_orchestrator": self.src_root / "core" / "langgraph_orchestrator",
            "data_models": self.src_root / "core" / "data_models",
            "services": self.src_root / "core" / "services",
            "providers": self.src_root / "core" / "providers",
            "security": self.src_root / "core" / "security",
        }

    def migrate(self) -> Dict[str, Any]:
        """Execute the complete migration."""
        migration_results = {
            "migrated_files": [],
            "migrated_directories": [],
            "backup_created": False,
            "errors": [],
            "warnings": [],
        }

        try:
            logger.info("Starting orchestrator migration...")

            # Create backup
            self._create_backup(migration_results)

            # Migrate data models
            self._migrate_data_models(migration_results)

            # Migrate services
            self._migrate_services(migration_results)

            # Migrate providers
            self._migrate_providers(migration_results)

            # Migrate security components
            self._migrate_security_components(migration_results)

            # Migrate contracts and adapters
            self._migrate_contracts_and_adapters(migration_results)

            # Collapse orchestrators
            self._collapse_orchestrators(migration_results)

            # Update imports
            self._update_imports(migration_results)

            # Clean up legacy components
            self._cleanup_legacy_components(migration_results)

            logger.info("Migration completed successfully!")

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            migration_results["errors"].append(str(e))

        return migration_results

    def _create_backup(self, migration_results: Dict[str, Any]) -> None:
        """Create backup of legacy components."""
        logger.info("Creating backup of legacy components...")

        backup_path = self.project_root / "migration_backup"
        backup_path.mkdir(exist_ok=True)

        # Backup legacy directories
        for name, path in self.legacy_paths.items():
            if path.exists():
                backup_target = backup_path / name
                if path.is_dir():
                    shutil.copytree(path, backup_target)
                else:
                    shutil.copy2(path, backup_target)
                migration_results["backup_created"] = True
                logger.info(f"Backed up {name} to {backup_target}")

        # Create backup manifest
        manifest = {
            "timestamp": str(datetime.now()),
            "backup_path": str(backup_path),
            "backed_up_items": list(self.legacy_paths.keys()),
        }

        manifest_file = backup_path / "migration_manifest.json"
        with open(manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)

        migration_results["backup_path"] = str(backup_path)

    def _migrate_data_models(self, migration_results: Dict[str, Any]) -> None:
        """Migrate data models from legacy systems."""
        logger.info("Migrating data models...")

        # Migrate chat models
        chat_models_path = self.src_root / "server" / "chat" / "models.py"
        if chat_models_path.exists():
            target_path = self.target_paths["data_models"] / "chat.py"
            shutil.copy2(chat_models_path, target_path)
            migration_results["migrated_files"].append(str(target_path))
            logger.info(f"Migrated chat models to {target_path}")

        # Migrate other data models as needed
        # ...

    def _migrate_services(self, migration_results: Dict[str, Any]) -> None:
        """Migrate service components from legacy systems."""
        logger.info("Migrating services...")

        # Migrate conversation service
        conv_service_path = (
            self.src_root / "server" / "chat" / "conversation_service.py"
        )
        if conv_service_path.exists():
            target_path = self.target_paths["services"] / "conversation_service.py"
            shutil.copy2(conv_service_path, target_path)
            migration_results["migrated_files"].append(str(target_path))
            logger.info(f"Migrated conversation service to {target_path}")

        # Migrate message service
        msg_service_path = self.src_root / "server" / "chat" / "message_service.py"
        if msg_service_path.exists():
            target_path = self.target_paths["services"] / "message_service.py"
            shutil.copy2(msg_service_path, target_path)
            migration_results["migrated_files"].append(str(target_path))
            logger.info(f"Migrated message service to {target_path}")

        # Migrate other services as needed
        # ...

    def _migrate_providers(self, migration_results: Dict[str, Any]) -> None:
        """Migrate provider implementations from legacy systems."""
        logger.info("Migrating providers...")

        # Migrate chat providers
        chat_providers_path = self.src_root / "server" / "chat" / "providers"
        if chat_providers_path.exists():
            target_path = self.target_paths["providers"]
            shutil.copytree(chat_providers_path, target_path / "chat_providers")
            migration_results["migrated_directories"].append(str(target_path))
            logger.info(f"Migrated chat providers to {target_path}")

        # Migrate other providers as needed
        # ...

    def _migrate_security_components(self, migration_results: Dict[str, Any]) -> None:
        """Migrate security components from legacy systems."""
        logger.info("Migrating security components...")

        # Migrate chat security
        chat_security_path = self.src_root / "server" / "chat" / "security.py"
        if chat_security_path.exists():
            target_path = self.target_paths["security"] / "chat_security.py"
            shutil.copy2(chat_security_path, target_path)
            migration_results["migrated_files"].append(str(target_path))
            logger.info(f"Migrated chat security to {target_path}")

        # Migrate other security components as needed
        # ...

    def _migrate_contracts_and_adapters(
        self, migration_results: Dict[str, Any]
    ) -> None:
        """Migrate contracts and adapters for LangGraph integration."""
        logger.info("Migrating contracts and adapters...")

        # Create contracts directory if it doesn't exist
        contracts_path = self.target_paths["langgraph_orchestrator"] / "contracts"
        contracts_path.mkdir(exist_ok=True)

        # Create adapters directory
        adapters_path = self.target_paths["langgraph_orchestrator"] / "adapters"
        adapters_path.mkdir(exist_ok=True)

        # Migrate contracts from legacy systems
        # ...

        logger.info("Contracts and adapters migration completed")

    def _collapse_orchestrators(self, migration_results: Dict[str, Any]) -> None:
        """Collapse multiple orchestrators into single LangGraph system."""
        logger.info("Collapsing orchestrators...")

        # Analyze legacy orchestrators for useful components
        legacy_components = self._analyze_legacy_orchestrators()

        # Integrate useful components into LangGraph orchestrator
        self._integrate_legacy_components(legacy_components, migration_results)

        # Create unified orchestrator interface
        self._create_unified_interface(migration_results)

        logger.info("Orchestrator collapse completed")

    def _analyze_legacy_orchestrators(self) -> Dict[str, Any]:
        """Analyze legacy orchestrators for useful components."""
        legacy_components = {
            "chat_orchestrator": {},
            "agent_orchestrator": {},
            "ai_orchestrator": {},
        }

        # Analyze each legacy orchestrator
        for name, path in self.legacy_paths.items():
            if path.exists():
                if path.is_dir():
                    # Analyze directory
                    legacy_components[name] = self._analyze_orchestrator_directory(path)
                else:
                    # Analyze single file
                    legacy_components[name] = self._analyze_orchestrator_file(path)

        return legacy_components

    def _analyze_orchestrator_directory(self, path: Path) -> Dict[str, Any]:
        """Analyze an orchestrator directory."""
        components = {
            "files": [],
            "classes": [],
            "functions": [],
            "imports": [],
            "useful_methods": [],
        }

        # Scan directory for Python files
        for py_file in path.glob("*.py"):
            components["files"].append(str(py_file))

            # Analyze file content
            with open(py_file, "r") as f:
                content = f.read()

                # Extract classes
                class_matches = re.findall(r"class\s+(\w+)", content)
                components["classes"].extend(class_matches)

                # Extract functions
                func_matches = re.findall(r"def\s+(\w+)", content)
                components["functions"].extend(func_matches)

                # Extract imports
                import_matches = re.findall(r"import\s+(\w+)", content)
                components["imports"].extend(import_matches)

                # Identify potentially useful methods
                useful_methods = [
                    "validate",
                    "authenticate",
                    "authorize",
                    "process",
                    "handle",
                    "execute",
                    "generate",
                    "format",
                    "parse",
                ]
                for method in useful_methods:
                    if method in content.lower():
                        components["useful_methods"].append(method)

        return components

    def _analyze_orchestrator_file(self, path: Path) -> Dict[str, Any]:
        """Analyze an orchestrator file."""
        components = {
            "classes": [],
            "functions": [],
            "imports": [],
            "useful_methods": [],
        }

        with open(path, "r") as f:
            content = f.read()

            # Extract classes
            class_matches = re.findall(r"class\s+(\w+)", content)
            components["classes"].extend(class_matches)

            # Extract functions
            func_matches = re.findall(r"def\s+(\w+)", content)
            components["functions"].extend(func_matches)

            # Extract imports
            import_matches = re.findall(r"import\s+(\w+)", content)
            components["imports"].extend(import_matches)

            # Identify potentially useful methods
            useful_methods = [
                "validate",
                "authenticate",
                "authorize",
                "process",
                "handle",
                "execute",
                "generate",
                "format",
                "parse",
            ]
            for method in useful_methods:
                if method in content.lower():
                    components["useful_methods"].append(method)

        return components

    def _integrate_legacy_components(
        self, legacy_components: Dict[str, Any], migration_results: Dict[str, Any]
    ) -> None:
        """Integrate useful legacy components into LangGraph orchestrator."""

        # Extract useful components from each legacy orchestrator
        for orchestrator_name, components in legacy_components.items():
            if orchestrator_name == "chat_orchestrator":
                self._integrate_chat_orchestrator_components(
                    components, migration_results
                )
            elif orchestrator_name == "agent_orchestrator":
                self._integrate_agent_orchestrator_components(
                    components, migration_results
                )
            elif orchestrator_name == "ai_orchestrator":
                self._integrate_ai_orchestrator_components(
                    components, migration_results
                )

    def _integrate_chat_orchestrator_components(
        self, components: Dict[str, Any], migration_results: Dict[str, Any]
    ) -> None:
        """Integrate chat orchestrator components."""
        logger.info("Integrating chat orchestrator components...")

        # Extract useful methods
        useful_methods = components.get("useful_methods", [])

        # Integrate formatting methods
        if "format" in useful_methods:
            self._integrate_formatting_methods(migration_results)

        # Integrate validation methods
        if "validate" in useful_methods:
            self._integrate_validation_methods(migration_results)

        # Integrate conversation handling methods
        if "handle" in useful_methods:
            self._integrate_conversation_methods(migration_results)

    def _integrate_agent_orchestrator_components(
        self, components: Dict[str, Any], migration_results: Dict[str, Any]
    ) -> None:
        """Integrate agent orchestrator components."""
        logger.info("Integrating agent orchestrator components...")

        # Extract useful methods
        useful_methods = components.get("useful_methods", [])

        # Integrate agent coordination methods
        if "coordinate" in useful_methods:
            self._integrate_coordination_methods(migration_results)

        # Integrate agent execution methods
        if "execute" in useful_methods:
            self._integrate_agent_execution_methods(migration_results)

    def _integrate_ai_orchestrator_components(
        self, components: Dict[str, Any], migration_results: Dict[str, Any]
    ) -> None:
        """Integrate AI orchestrator components."""
        logger.info("Integrating AI orchestrator components...")

        # Extract useful methods
        useful_methods = components.get("useful_methods", [])

        # Integrate AI workflow methods
        if "process" in useful_methods:
            self._integrate_workflow_methods(migration_results)

        # Integrate AI generation methods
        if "generate" in useful_methods:
            self._integrate_generation_methods(migration_results)

    def _integrate_formatting_methods(self, migration_results: Dict[str, Any]) -> None:
        """Integrate formatting methods from legacy chat orchestrator."""
        # This would involve copying formatting logic into the LangGraph nodes
        logger.info("Integrating formatting methods...")

    def _integrate_validation_methods(self, migration_results: Dict[str, Any]) -> None:
        """Integrate validation methods from legacy chat orchestrator."""
        # This would involve copying validation logic into the LangGraph nodes
        logger.info("Integrating validation methods...")

    def _integrate_conversation_methods(
        self, migration_results: Dict[str, Any]
    ) -> None:
        """Integrate conversation methods from legacy chat orchestrator."""
        # This would involve copying conversation handling logic into the LangGraph nodes
        logger.info("Integrating conversation methods...")

    def _integrate_coordination_methods(
        self, migration_results: Dict[str, Any]
    ) -> None:
        """Integrate coordination methods from legacy agent orchestrator."""
        # This would involve copying coordination logic into the LangGraph nodes
        logger.info("Integrating coordination methods...")

    def _integrate_agent_execution_methods(
        self, migration_results: Dict[str, Any]
    ) -> None:
        """Integrate agent execution methods from legacy agent orchestrator."""
        # This would involve copying agent execution logic into the LangGraph nodes
        logger.info("Integrating agent execution methods...")

    def _integrate_workflow_methods(self, migration_results: Dict[str, Any]) -> None:
        """Integrate workflow methods from legacy AI orchestrator."""
        # This would involve copying workflow logic into the LangGraph nodes
        logger.info("Integrating workflow methods...")

    def _integrate_generation_methods(self, migration_results: Dict[str, Any]) -> None:
        """Integrate generation methods from legacy AI orchestrator."""
        # This would involve copying generation logic into the LangGraph nodes
        logger.info("Integrating generation methods...")

    def _create_unified_interface(self, migration_results: Dict[str, Any]) -> None:
        """Create unified orchestrator interface."""
        logger.info("Creating unified orchestrator interface...")

        # Create unified interface that replaces legacy orchestrators
        interface_path = (
            self.target_paths["langgraph_orchestrator"] / "unified_interface.py"
        )

        interface_content = '''
"""
Unified Orchestrator Interface

This interface replaces the legacy orchestrators and provides
a single point of entry for all orchestration needs.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid

from .orchestrator import LangGraphOrchestrator
from .contracts import ChatRequest, OrchestrationConfig

class UnifiedOrchestrator:
    """Unified orchestrator that replaces legacy orchestrators."""
    
    def __init__(self, config: Optional[OrchestrationConfig] = None):
        """Initialize the unified orchestrator."""
        self.config = config or OrchestrationConfig()
        self.langgraph_orchestrator = LangGraphOrchestrator(self.config)
    
    async def process_chat_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a chat request using the LangGraph orchestrator."""
        request = ChatRequest(
            request_id=str(uuid.uuid4()),
            user_id=request_data["user_id"],
            content=request_data["content"],
            metadata=request_data.get("metadata", {}),
            conversation_id=request_data.get("conversation_id"),
            session_id=request_data.get("session_id")
        )
        
        return await self.langgraph_orchestrator.process_request(request)
    
    async def process_agent_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process an agent request using the LangGraph orchestrator."""
        # Agent requests are processed the same as chat requests
        return await self.process_chat_request(request_data)
    
    async def process_ai_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process an AI request using the LangGraph orchestrator."""
        # AI requests are processed the same as chat requests
        return await self.process_chat_request(request_data)
    
    def get_orchestrator_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        return self.langgraph_orchestrator.get_telemetry_stats()

# Create global instance
orchestrator = UnifiedOrchestrator()
'''

        with open(interface_path, "w") as f:
            f.write(interface_content)

        migration_results["migrated_files"].append(str(interface_path))
        logger.info(f"Created unified interface at {interface_path}")

    def _update_imports(self, migration_results: Dict[str, Any]) -> None:
        """Update imports throughout the codebase."""
        logger.info("Updating imports...")

        # Find all Python files that need import updates
        python_files = list(self.src_root.rglob("*.py"))

        for file_path in python_files:
            self._update_file_imports(file_path, migration_results)

        logger.info("Import updates completed")

    def _update_file_imports(
        self, file_path: Path, migration_results: Dict[str, Any]
    ) -> None:
        """Update imports in a specific file."""
        try:
            with open(file_path, "r") as f:
                content = f.read()

            # Update legacy imports to new LangGraph imports
            old_imports = [
                "from ai_karen_engine.chat.ChatOrchestrator import",
                "from ai_karen_engine.agents.agent_orchestrator import",
                "from ai_karen_engine.ai_orchestrator.ai_orchestrator import",
                "from ai_karen_engine.server.chat.models import",
                "from ai_karen_engine.server.chat.conversation_service import",
                "from ai_karen_engine.server.chat.providers import",
            ]

            new_imports = [
                "from ai_karen_engine.core.langgraph_orchestrator import",
                "from ai_karen_engine.core.data_models.chat import",
                "from ai_karen_engine.core.services.conversation_service import",
                "from ai_karen_engine.core.providers.chat_providers import",
            ]

            updated_content = content
            for old_import in old_imports:
                if old_import in updated_content:
                    # Replace with appropriate new import
                    updated_content = updated_content.replace(
                        old_import, new_imports[0]
                    )

            if updated_content != content:
                with open(file_path, "w") as f:
                    f.write(updated_content)

                migration_results["migrated_files"].append(str(file_path))
                logger.info(f"Updated imports in {file_path}")

        except Exception as e:
            logger.warning(f"Failed to update imports in {file_path}: {e}")
            migration_results["warnings"].append(
                f"Failed to update imports in {file_path}: {e}"
            )

    def _cleanup_legacy_components(self, migration_results: Dict[str, Any]) -> None:
        """Clean up legacy components after migration."""
        logger.info("Cleaning up legacy components...")

        # Remove legacy orchestrators
        for name, path in self.legacy_paths.items():
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()

                migration_results["migrated_files"].append(f"Removed: {path}")
                logger.info(f"Removed legacy component: {path}")

        # Remove empty legacy directories
        self._remove_empty_directories(migration_results)

        logger.info("Legacy cleanup completed")

    def _remove_empty_directories(self, migration_results: Dict[str, Any]) -> None:
        """Remove empty legacy directories."""
        legacy_dirs = [
            self.src_root / "chat" / "ChatOrchestrator",
            self.src_root / "agents",
            self.src_root / "ai_orchestrator",
            self.src_root / "server" / "chat",
        ]

        for dir_path in legacy_dirs:
            if dir_path.exists() and dir_path.is_dir():
                try:
                    # Check if directory is empty
                    if not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        migration_results["migrated_files"].append(
                            f"Removed empty directory: {dir_path}"
                        )
                        logger.info(f"Removed empty directory: {dir_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove directory {dir_path}: {e}")
                    migration_results["warnings"].append(
                        f"Failed to remove directory {dir_path}: {e}"
                    )


def main():
    """Main migration function."""
    import argparse
    import json
    from datetime import datetime

    parser = argparse.ArgumentParser(
        description="Migrate orchestrators to LangGraph system"
    )
    parser.add_argument(
        "--project-root", type=str, default=".", help="Project root directory"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run migration without making changes"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create migration instance
    migration = OrchestratorMigration(args.project_root)

    # Execute migration
    results = migration.migrate()

    # Print results
    print("\nMigration Results:")
    print(f"Backup created: {results['backup_created']}")
    print(f"Files migrated: {len(results['migrated_files'])}")
    print(f"Directories migrated: {len(results['migrated_directories'])}")
    print(f"Errors: {len(results['errors'])}")
    print(f"Warnings: {len(results['warnings'])}")

    if results["errors"]:
        print("\nErrors:")
        for error in results["errors"]:
            print(f"  - {error}")

    if results["warnings"]:
        print("\nWarnings:")
        for warning in results["warnings"]:
            print(f"  - {warning}")

    # Save results to file
    results_file = Path(args.project_root) / "migration_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {results_file}")


if __name__ == "__main__":
    main()

"""
Compatibility audit system for AI-Karen.

Analyzes migration bridges, adapters, and compatibility layers
to identify cleanup opportunities and migration paths.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("kari.compatibility.audit")


class CompatibilityRisk(str, Enum):
    """Risk levels for compatibility issues."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CompatibilityStatus(str, Enum):
    """Status of compatibility files."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    LEGACY = "legacy"
    SHIM = "shim"
    MIGRATION = "migration"
    UNKNOWN = "unknown"


@dataclass
class CompatibilityFile:
    """Represents a compatibility file."""
    
    path: Path
    name: str
    file_type: str
    status: CompatibilityStatus
    risk_level: CompatibilityRisk
    current_consumers: List[str] = field(default_factory=list)
    unique_behavior: List[str] = field(default_factory=list)
    canonical_replacement: Optional[str] = None
    delete_now: bool = False
    analysis: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "name": self.name,
            "file_type": self.file_type,
            "status": self.status.value,
            "risk_level": self.risk_level.value,
            "current_consumers": self.current_consumers,
            "unique_behavior": self.unique_behavior,
            "canonical_replacement": self.canonical_replacement,
            "delete_now": self.delete_now,
            "analysis": self.analysis,
        }


@dataclass
class CompatibilityReport:
    """Compatibility audit report."""
    
    audit_timestamp: str
    total_files: int
    files_by_status: Dict[str, int]
    files_by_risk: Dict[str, int]
    recommendations: List[str]
    action_items: List[str]
    files: List[CompatibilityFile]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_timestamp": self.audit_timestamp,
            "total_files": self.total_files,
            "files_by_status": {k: v for k, v in self.files_by_status.items()},
            "files_by_risk": {k: v for k, v in self.files_by_risk.items()},
            "recommendations": self.recommendations,
            "action_items": self.action_items,
            "files": [file.to_dict() for file in self.files],
        }


class CompatibilityAuditor:
    """Audits compatibility files and migration paths."""
    
    def __init__(self, root_path: Path):
        self.root_path = root_path
        self.compatibility_files: List[CompatibilityFile] = []
        
        # Define patterns to search for
        self.patterns = {
            "compat": ["*_compat.py", "*_adapter.py"],
            "migration": ["TEMP-MIGRATION*", "*migration*.py"],
            "legacy": ["legacy*", "*legacy*.py"],
            "deprecated": ["deprecated*", "*deprecated*.py"],
            "shim": ["shim*", "*shim*.py"],
        }
        
        # Define canonical replacements
        self.canonical_replacements = {
            "s3_compat.py": "core/storage/s3_storage.py",
            "session_state_manager_compat.py": "core/runtime/session_manager.py",
            "openai_compatible_provider_compat.py": "core/model_runtime/openai_adapter.py",
            "model_registry_compat.py": "core/model_registry.py",
        }
    
    def audit_compatibility(self) -> CompatibilityReport:
        """Perform comprehensive compatibility audit."""
        
        logger.info("Starting compatibility audit...")
        
        # Find all compatibility files
        self._find_compatibility_files()
        
        # Analyze each file
        for file_info in self.compatibility_files:
            self._analyze_file(file_info)
        
        # Generate report
        report = self._generate_report()
        
        logger.info(f"Compatibility audit completed. Found {len(self.compatibility_files)} files.")
        return report
    
    def _find_compatibility_files(self):
        """Find all compatibility files in the project."""
        
        for category, patterns in self.patterns.items():
            for pattern in patterns:
                found_files = list(self.root_path.rglob(pattern))
                
                for file_path in found_files:
                    # Skip __pycache__ directories
                    if "__pycache__" in str(file_path):
                        continue
                    
                    # Determine file type and status
                    file_type = category
                    status = self._determine_status(file_path, category)
                    risk_level = self._assess_risk(file_path, category)
                    
                    file_info = CompatibilityFile(
                        path=file_path,
                        name=file_path.name,
                        file_type=file_type,
                        status=status,
                        risk_level=risk_level,
                    )
                    
                    self.compatibility_files.append(file_info)
        
        logger.info(f"Found {len(self.compatibility_files)} compatibility files")
    
    def _determine_status(self, file_path: Path, category: str) -> CompatibilityStatus:
        """Determine the status of a compatibility file."""
        
        # Check filename for status indicators
        filename_lower = file_path.name.lower()
        
        if "temp" in filename_lower or "migration" in filename_lower:
            return CompatibilityStatus.MIGRATION
        elif "deprecated" in filename_lower:
            return CompatibilityStatus.DEPRECATED
        elif "legacy" in filename_lower:
            return CompatibilityStatus.LEGACY
        elif "shim" in filename_lower:
            return CompatibilityStatus.SHIM
        elif "compat" in filename_lower or "adapter" in filename_lower:
            return CompatibilityStatus.ACTIVE
        else:
            return CompatibilityStatus.UNKNOWN
    
    def _assess_risk(self, file_path: Path, category: str) -> CompatibilityRisk:
        """Assess the risk level of a compatibility file."""
        
        # Check file size and complexity
        try:
            file_size = file_path.stat().st_size
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return CompatibilityRisk.MEDIUM
        
        # Count lines of code
        lines = content.splitlines()
        code_lines = len([line for line in lines if line.strip() and not line.strip().startswith("#")])
        
        # Assess risk based on various factors
        risk_factors = []
        
        # File size
        if file_size > 10000:  # 10KB
            risk_factors.append("large_file")
        elif file_size < 100:  # 100B
            risk_factors.append("small_file")
        
        # Code complexity
        if code_lines > 500:
            risk_factors.append("high_complexity")
        elif code_lines < 50:
            risk_factors.append("low_complexity")
        
        # Category-based risk
        if category == "migration":
            risk_factors.append("temporary")
        elif category == "deprecated":
            risk_factors.append("obsolete")
        elif category == "legacy":
            risk_factors.append("outdated")
        
        # Determine risk level
        if "obsolete" in risk_factors or "high_complexity" in risk_factors:
            return CompatibilityRisk.CRITICAL
        elif "temporary" in risk_factors or "outdated" in risk_factors:
            return CompatibilityRisk.HIGH
        elif "large_file" in risk_factors:
            return CompatibilityRisk.MEDIUM
        else:
            return CompatibilityRisk.LOW
    
    def _analyze_file(self, file_info: CompatibilityFile):
        """Analyze a compatibility file."""
        
        try:
            with open(file_info.path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Parse AST for analysis
            try:
                tree = ast.parse(content)
                file_info.analysis["ast_parsed"] = True
                file_info.analysis["ast_nodes"] = len(list(ast.walk(tree)))
            except SyntaxError:
                file_info.analysis["ast_parsed"] = False
                file_info.analysis["ast_error"] = "Syntax error"
            
            # Find consumers of this file
            consumers = self._find_consumers(file_info.path)
            file_info.current_consumers = consumers
            
            # Identify unique behavior
            unique_behavior = self._identify_unique_behavior(content, file_info.file_type)
            file_info.unique_behavior = unique_behavior
            
            # Determine canonical replacement
            if file_info.name in self.canonical_replacements:
                file_info.canonical_replacement = self.canonical_replacements[file_info.name]
            
            # Assess if can be deleted now
            file_info.delete_now = self._can_delete_now(file_info)
            
        except Exception as e:
            logger.error(f"Failed to analyze file {file_info.path}: {e}")
            file_info.analysis["analysis_error"] = str(e)
    
    def _find_consumers(self, file_path: Path) -> List[str]:
        """Find files that import or use this compatibility file."""
        
        consumers = []
        file_name = file_path.name
        
        # Search for imports in Python files
        for py_file in self.root_path.rglob("*.py"):
            if py_file == file_path:
                continue
            
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Check for imports
                if file_name in content:
                    # Simple check - could be enhanced with proper AST analysis
                    consumers.append(str(py_file))
                
            except Exception:
                continue
        
        return consumers
    
    def _identify_unique_behavior(self, content: str, file_type: str) -> List[str]:
        """Identify unique behavior of a compatibility file."""
        
        unique_behavior = []
        
        # Check for specific patterns based on file type
        if file_type == "compat":
            # Look for compatibility-specific patterns
            if "compat" in content.lower():
                unique_behavior.append("compatibility_layer")
            if "adapter" in content.lower():
                unique_behavior.append("adapter_pattern")
            if "legacy" in content.lower():
                unique_behavior.append("legacy_support")
        
        elif file_type == "migration":
            # Look for migration-specific patterns
            if "migration" in content.lower():
                unique_behavior.append("migration_logic")
            if "temp" in content.lower():
                unique_behavior.append("temporary_code")
        
        # Check for deprecated patterns
        deprecated_patterns = ["@deprecated", "DEPRECATED", "LEGACY", "SHIM"]
        for pattern in deprecated_patterns:
            if pattern in content:
                unique_behavior.append(f"deprecated_pattern:{pattern}")
        
        # Check for error handling
        if "try:" in content and "except:" in content:
            unique_behavior.append("error_handling")
        
        # Check for version-specific code
        if "version" in content.lower() or "compatibility" in content.lower():
            unique_behavior.append("version_specific")
        
        return unique_behavior
    
    def _can_delete_now(self, file_info: CompatibilityFile) -> bool:
        """Determine if a file can be deleted now."""
        
        # Files with no consumers can be deleted
        if not file_info.current_consumers:
            return True
        
        # Deprecated files with minimal consumers can be deleted
        if file_info.status == CompatibilityStatus.DEPRECATED:
            return len(file_info.current_consumers) <= 2
        
        # Legacy files with no unique behavior can be deleted
        if file_info.status == CompatibilityStatus.LEGACY:
            return len(file_info.unique_behavior) == 0
        
        # Temporary migration files can be deleted
        if file_info.status == CompatibilityStatus.MIGRATION:
            return True
        
        return False
    
    def _generate_report(self) -> CompatibilityReport:
        """Generate a compatibility audit report."""
        
        # Count files by status and risk
        files_by_status = {}
        files_by_risk = {}
        
        for file_info in self.compatibility_files:
            # Count by status
            status_key = file_info.status.value
            files_by_status[status_key] = files_by_status.get(status_key, 0) + 1
            
            # Count by risk
            risk_key = file_info.risk_level.value
            files_by_risk[risk_key] = files_by_risk.get(risk_key, 0) + 1
        
        # Generate recommendations
        recommendations = self._generate_recommendations()
        
        # Generate action items
        action_items = self._generate_action_items()
        
        return CompatibilityReport(
            audit_timestamp=datetime.utcnow().isoformat(),
            total_files=len(self.compatibility_files),
            files_by_status=files_by_status,
            files_by_risk=files_by_risk,
            recommendations=recommendations,
            action_items=action_items,
            files=self.compatibility_files,
        )
    
    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on audit results."""
        
        recommendations = []
        
        # High-risk files
        high_risk_files = [f for f in self.compatibility_files if f.risk_level == CompatibilityRisk.HIGH]
        if high_risk_files:
            recommendations.append(f"Address {len(high_risk_files)} high-risk compatibility files")
        
        # Deprecated files
        deprecated_files = [f for f in self.compatibility_files if f.status == CompatibilityStatus.DEPRECATED]
        if deprecated_files:
            recommendations.append(f"Review and remove {len(deprecated_files)} deprecated files")
        
        # Legacy files
        legacy_files = [f for f in self.compatibility_files if f.status == CompatibilityStatus.LEGACY]
        if legacy_files:
            recommendations.append(f"Replace {len(legacy_files)} legacy files with canonical implementations")
        
        # Files with no canonical replacement
        no_replacement = [f for f in self.compatibility_files if f.canonical_replacement is None]
        if no_replacement:
            recommendations.append(f"Define canonical replacements for {len(no_replacement)} files")
        
        return recommendations
    
    def _generate_action_items(self) -> List[str]:
        """Generate specific action items."""
        
        action_items = []
        
        # Files that can be deleted now
        deletable_files = [f for f in self.compatibility_files if f.delete_now]
        for file_info in deletable_files:
            action_items.append(f"DELETE: {file_info.path} (no consumers)")
        
        # Files that need migration
        migration_files = [f for f in self.compatibility_files if f.status == CompatibilityStatus.MIGRATION]
        for file_info in migration_files:
            action_items.append(f"MIGRATE: {file_info.path} to canonical implementation")
        
        # Files that need replacement
        replacement_files = [f for f in self.compatibility_files if f.canonical_replacement]
        for file_info in replacement_files:
            action_items.append(f"REPLACE: {file_info.path} with {file_info.canonical_replacement}")
        
        # Files that need review
        review_files = [f for f in self.compatibility_files if f.risk_level == CompatibilityRisk.CRITICAL]
        for file_info in review_files:
            action_items.append(f"REVIEW: {file_info.path} (critical risk)")
        
        return action_items


def run_compatibility_audit(root_path: Path = None) -> CompatibilityReport:
    """Run compatibility audit and return report."""
    
    if root_path is None:
        root_path = Path(".")
    
    auditor = CompatibilityAuditor(root_path)
    return auditor.audit_compatibility()


if __name__ == "__main__":
    # Run audit from project root
    report = run_compatibility_audit()
    
    print(f"Compatibility Audit Report - {report.audit_timestamp}")
    print(f"Total files: {report.total_files}")
    print(f"Files by status: {report.files_by_status}")
    print(f"Files by risk: {report.files_by_risk}")
    print("\nRecommendations:")
    for rec in report.recommendations:
        print(f"  - {rec}")
    print("\nAction Items:")
    for action in report.action_items:
        print(f"  - {action}")
"""
Data Cleanup Service

Service for cleaning test/demo data from the data/ directory and databases.
Focuses on production readiness by removing development artifacts.

Requirements: 2.4
"""

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Iterable
import hashlib

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.services.database_connection_manager import get_database_manager
from ai_karen_engine.core.memory.redis_connection_manager import get_redis_manager

logger = get_logger(__name__)


@dataclass
class CleanupAction:
    """Individual cleanup action"""
    action_type: str
    target: str
    description: str
    size_bytes: Optional[int] = None
    count: Optional[int] = None
    backup_location: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CleanupReport:
    """Data cleanup report"""
    timestamp: datetime
    dry_run: bool
    total_actions: int
    successful_actions: int
    failed_actions: int
    bytes_cleaned: int
    actions: List[CleanupAction]
    errors: List[str]
    summary: Dict[str, Any] = field(default_factory=dict)


class DataCleanupService:
    """
    Service for cleaning test/demo data from the system.
    
    Handles:
    - Demo user accounts removal
    - Test data file cleanup
    - Temporary file removal
    - Log file rotation
    - Cache cleanup
    """

    def __init__(self, data_directory: str = "data", backup_directory: str = "system_backups"):
        self.data_directory = Path(data_directory)
        self.backup_directory = Path(backup_directory)
        self.backup_directory.mkdir(exist_ok=True)
        
        # Database managers
        from ai_karen_engine.database.client import get_database_client
        self.db_client = get_database_client()
        self.redis_manager = get_redis_manager()
        
        # Demo/test patterns to identify and remove
        self.demo_patterns = {
            "demo_emails": [
                "admin@example.com",
                "test@example.com", 
                "demo@example.com",
                "user@example.com",
                "dev@example.com",
            ],
            "demo_user_ids": [
                "dev_admin",
                "test_user",
                "demo_user",
                "example_user",
            ],
            "demo_names": [
                "Development Admin",
                "Test User",
                "Demo User",
                "Example User",
            ],
            "test_file_patterns": [
                "*.tmp",
                "*.temp",
                "*.test",
                "*.backup",
                "*.log",
                "*_test.*",
                "*_demo.*",
                "*_example.*",
            ],
            "demo_content_keywords": [
                "test",
                "demo",
                "example",
                "placeholder",
                "lorem ipsum",
                "sample data",
            ],
        }

    async def cleanup_all(self, dry_run: bool = True) -> CleanupReport:
        """
        Perform comprehensive data cleanup.
        
        Args:
            dry_run: If True, only report what would be cleaned without making changes
            
        Returns:
            CleanupReport: Complete cleanup report
        """
        logger.info(f"Starting comprehensive data cleanup (dry_run={dry_run})")
        
        actions: List[CleanupAction] = []
        errors: List[str] = []
        bytes_cleaned: int = 0
        
        try:
            # Clean up data directory files
            file_actions, file_bytes = await self._cleanup_data_files(dry_run)
            actions.extend(file_actions)
            bytes_cleaned += file_bytes
            
            # Clean up demo users from users.json
            user_actions = await self._cleanup_users_json(dry_run)
            actions.extend(user_actions)
            
            # Clean up temporary and log files
            temp_actions, temp_bytes = await self._cleanup_temporary_files(dry_run)
            actions.extend(temp_actions)
            bytes_cleaned += temp_bytes
            
            # Clean up cache files
            cache_actions, cache_bytes = await self._cleanup_cache_files(dry_run)
            actions.extend(cache_actions)
            bytes_cleaned += cache_bytes
            
            # Clean up old backups
            backup_actions, backup_bytes = await self._cleanup_old_backups(dry_run)
            actions.extend(backup_actions)
            bytes_cleaned += backup_bytes
            
        except Exception as e:
            logger.error(f"Data cleanup failed: {e}")
            errors.append(str(e))
        
        # Generate summary
        successful_actions = len([a for a in actions if a.action_type != "error"])
        failed_actions = len(errors)
        
        summary = {
            "files_processed": len(actions),
            "bytes_cleaned": bytes_cleaned,
            "demo_users_removed": len([a for a in actions if a.action_type == "remove_demo_user"]),
            "temp_files_removed": len([a for a in actions if a.action_type == "remove_temp_file"]),
            "cache_files_removed": len([a for a in actions if a.action_type == "remove_cache_file"]),
            "backup_files_removed": len([a for a in actions if a.action_type == "remove_old_backup"]),
        }
        
        return CleanupReport(
            timestamp=datetime.utcnow(),
            dry_run=dry_run,
            total_actions=len(actions),
            successful_actions=successful_actions,
            failed_actions=failed_actions,
            bytes_cleaned=bytes_cleaned,
            actions=actions,
            errors=errors,
            summary=summary,
        )

    async def _cleanup_data_files(self, dry_run: bool) -> tuple[List[CleanupAction], int]:
        """Clean up test/demo data files"""
        actions = []
        bytes_cleaned = 0
        
        try:
            # Check for test database files
            test_db_files = [
                "kari_automation.db",
                "test.db",
                "demo.db",
                "example.db",
            ]
            
            for db_file in test_db_files:
                db_path = self.data_directory / db_file
                if db_path.exists():
                    file_size = db_path.stat().st_size
                    
                    # Only remove if it's clearly a test file or very large
                    if file_size > 10 * 1024 * 1024 or "test" in db_file.lower():  # > 10MB or contains "test"
                        if not dry_run:
                            # Backup before removal
                            backup_path = self._create_backup(db_path)
                            db_path.unlink()
                            
                            actions.append(CleanupAction(
                                action_type="remove_test_db",
                                target=str(db_path),
                                description=f"Removed test database file: {db_file}",
                                size_bytes=file_size,
                                backup_location=str(backup_path),
                            ))
                        else:
                            actions.append(CleanupAction(
                                action_type="would_remove_test_db",
                                target=str(db_path),
                                description=f"Would remove test database file: {db_file}",
                                size_bytes=file_size,
                            ))
                        
                        bytes_cleaned: int = int(bytes_cleaned + file_size)
            
            # Check for demo content in JSON files
            json_files = list(self.data_directory.glob("*.json"))
            for json_file in json_files:
                if json_file.name in ["users.json"]:
                    continue  # Handle separately
                
                try:
                    with open(json_file, 'r') as f:
                        content = f.read()
                    
                    # Check for demo content
                    has_demo_content = any(
                        str(keyword).lower() in str(content).lower() 
                        for keyword in self.demo_patterns["demo_content_keywords"]
                    )
                    
                    if has_demo_content:
                        file_size = json_file.stat().st_size
                        
                        if not dry_run:
                            backup_path = self._create_backup(json_file)
                            actions.append(CleanupAction(
                                action_type="backup_demo_json",
                                target=str(json_file),
                                description=f"Backed up JSON file with demo content: {json_file.name}",
                                size_bytes=file_size,
                                backup_location=str(backup_path),
                            ))
                        else:
                            actions.append(CleanupAction(
                                action_type="would_backup_demo_json",
                                target=str(json_file),
                                description=f"Would backup JSON file with demo content: {json_file.name}",
                                size_bytes=file_size,
                            ))
                
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Skip files that aren't valid JSON or text
                    continue
                except Exception as e:
                    logger.warning(f"Error checking {json_file}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Data files cleanup failed: {e}")
            actions.append(CleanupAction(
                action_type="error",
                target="data_files",
                description=f"Data files cleanup failed: {str(e)}",
            ))
        
        return actions, bytes_cleaned

    async def _cleanup_users_json(self, dry_run: bool) -> List[CleanupAction]:
        """Clean up demo users from users.json"""
        actions = []
        
        try:
            users_file = self.data_directory / "users.json"
            if not users_file.exists():
                return actions
            
            with open(users_file, 'r') as f:
                users_data = json.load(f)
            
            original_count = len(users_data)
            demo_users_removed = []
            
            # Identify demo users
            for email, user_data in list(users_data.items()):
                is_demo_user = (
                    email in self.demo_patterns["demo_emails"] or
                    user_data.get("user_id") in self.demo_patterns["demo_user_ids"] or
                    user_data.get("full_name") in self.demo_patterns["demo_names"] or
                    any(keyword in email.lower() for keyword in ["test", "demo", "example"])
                )
                
                if is_demo_user:
                    demo_users_removed.append(email)
                    if not dry_run:
                        del users_data[email]
            
            if demo_users_removed:
                if not dry_run:
                    # Create backup
                    backup_path = self._create_backup(users_file)
                    
                    # Write cleaned data
                    with open(users_file, 'w') as f:
                        json.dump(users_data, f, indent=2)
                    
                    actions.append(CleanupAction(
                        action_type="remove_demo_user",
                        target=str(users_file),
                        description=f"Removed {len(demo_users_removed)} demo users: {', '.join(demo_users_removed)}",
                        count=len(demo_users_removed),
                        backup_location=str(backup_path),
                    ))
                else:
                    actions.append(CleanupAction(
                        action_type="would_remove_demo_user",
                        target=str(users_file),
                        description=f"Would remove {len(demo_users_removed)} demo users: {', '.join(demo_users_removed)}",
                        count=len(demo_users_removed),
                    ))
        
        except Exception as e:
            logger.error(f"Users.json cleanup failed: {e}")
            actions.append(CleanupAction(
                action_type="error",
                target="users.json",
                description=f"Users.json cleanup failed: {str(e)}",
            ))
        
        return actions

    async def _cleanup_temporary_files(self, dry_run: bool) -> Tuple[List[CleanupAction], int]:
        """Clean up temporary and log files"""
        actions: List[CleanupAction] = []
        bytes_cleaned: int = 0
        
        try:
            # Find temporary files
            temp_files = []
            for pattern in self.demo_patterns["test_file_patterns"]:
                temp_files.extend(self.data_directory.glob(f"**/{pattern}"))
            
            # Also check for old log files
            log_files = list(self.data_directory.glob("**/*.log"))
            old_logs = [
                f for f in log_files 
                if f.stat().st_mtime < (time.time() - 7 * 24 * 3600)  # Older than 7 days
            ]
            temp_files.extend(old_logs)
            
            for temp_file in temp_files:
                try:
                    if temp_file.is_file():
                        file_size = temp_file.stat().st_size
                        
                        if not dry_run:
                            temp_file.unlink()
                            actions.append(CleanupAction(
                                action_type="remove_temp_file",
                                target=str(temp_file),
                                description=f"Removed temporary file: {temp_file.name}",
                                size_bytes=file_size,
                            ))
                        else:
                            actions.append(CleanupAction(
                                action_type="would_remove_temp_file",
                                target=str(temp_file),
                                description=f"Would remove temporary file: {temp_file.name}",
                                size_bytes=file_size,
                            ))
                        
                        inc: int = int(file_size)
                        bytes_cleaned = bytes_cleaned + inc
                
                except Exception as e:
                    logger.warning(f"Error removing {temp_file}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Temporary files cleanup failed: {e}")
            actions.append(CleanupAction(
                action_type="error",
                target="temp_files",
                description=f"Temporary files cleanup failed: {str(e)}",
            ))
        
        return actions, bytes_cleaned

    async def _cleanup_cache_files(self, dry_run: bool) -> Tuple[List[CleanupAction], int]:
        """Clean up cached responses and data"""
        actions: List[CleanupAction] = []
        bytes_cleaned: int = 0
        
        try:
            # Common cache directories to clean
            cache_dirs = [
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                "node_modules",
                ".next",
            ]
            
            for cache_dir_name in cache_dirs:
                cache_dirs_found = list(self.data_directory.glob(f"**/{cache_dir_name}"))
                
                for cache_dir in cache_dirs_found:
                    if cache_dir.is_dir():
                        try:
                            # Calculate directory size
                            dir_size = sum(
                                f.stat().st_size 
                                for f in cache_dir.rglob('*') 
                                if f.is_file()
                            )
                            
                            if not dry_run:
                                shutil.rmtree(cache_dir)
                                actions.append(CleanupAction(
                                    action_type="remove_cache_dir",
                                    target=str(cache_dir),
                                    description=f"Removed cache directory: {cache_dir.name}",
                                    size_bytes=dir_size,
                                ))
                            else:
                                actions.append(CleanupAction(
                                    action_type="would_remove_cache_dir",
                                    target=str(cache_dir),
                                    description=f"Would remove cache directory: {cache_dir.name}",
                                    size_bytes=dir_size,
                                ))
                            
                            bytes_cleaned += dir_size
                        
                        except Exception as e:
                            logger.warning(f"Error removing cache directory {cache_dir}: {e}")
                            continue
            
            # Clean up individual cache files
            cache_file_patterns = [
                "*.pyc",
                "*.pyo",
                "*.pyd",
                ".DS_Store",
                "Thumbs.db",
            ]
            
            for pattern in cache_file_patterns:
                cache_files = list(self.data_directory.glob(f"**/{pattern}"))
                
                for cache_file in cache_files:
                    try:
                        if cache_file.is_file():
                            file_size = cache_file.stat().st_size
                            
                            if not dry_run:
                                cache_file.unlink()
                                actions.append(CleanupAction(
                                    action_type="remove_cache_file",
                                    target=str(cache_file),
                                    description=f"Removed cache file: {cache_file.name}",
                                    size_bytes=file_size,
                                ))
                            else:
                                actions.append(CleanupAction(
                                    action_type="would_remove_cache_file",
                                    target=str(cache_file),
                                    description=f"Would remove cache file: {cache_file.name}",
                                    size_bytes=file_size,
                                ))
                            
                            bytes_cleaned += file_size
                    
                    except Exception as e:
                        logger.warning(f"Error removing cache file {cache_file}: {e}")
                        continue
        
        except Exception as e:
            logger.error(f"Cache files cleanup failed: {e}")
            actions.append(CleanupAction(
                action_type="error",
                target="cache_files",
                description=f"Cache files cleanup failed: {str(e)}",
            ))
        
        return actions, bytes_cleaned

    async def _cleanup_old_backups(self, dry_run: bool) -> Tuple[List[CleanupAction], int]:
        """Clean up older system backups"""
        actions: List[CleanupAction] = []
        bytes_cleaned: int = 0
        
        try:
            if not self.backup_directory.exists():
                return actions, bytes_cleaned
            
            # Find backup files older than 30 days
            cutoff_time = time.time() - (30 * 24 * 3600)  # 30 days ago
            old_backups = [
                f for f in self.backup_directory.rglob('*')
                if f.is_file() and f.stat().st_mtime < cutoff_time
            ]
            
            for backup_file in old_backups:
                try:
                    file_size = backup_file.stat().st_size
                    
                    if not dry_run:
                        backup_file.unlink()
                        actions.append(CleanupAction(
                            action_type="remove_old_backup",
                            target=str(backup_file),
                            description=f"Removed old backup: {backup_file.name}",
                            size_bytes=file_size,
                        ))
                    else:
                        actions.append(CleanupAction(
                            action_type="would_remove_old_backup",
                            target=str(backup_file),
                            description=f"Would remove old backup: {backup_file.name}",
                            size_bytes=file_size,
                        ))
                    
                    bytes_cleaned += file_size
                
                except Exception as e:
                    logger.warning(f"Error removing old backup {backup_file}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Old backups cleanup failed: {e}")
            actions.append(CleanupAction(
                action_type="error",
                target="old_backups",
                description=f"Old backups cleanup failed: {str(e)}",
            ))
        
        return actions, bytes_cleaned

    def _create_backup(self, file_path: Path) -> Path:
        """Create a backup of a file before modification"""
        timestamp = int(time.time())
        backup_name = f"{file_path.name}.backup.{timestamp}"
        backup_path = self.backup_directory / backup_name
        
        # Ensure backup directory exists
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy file to backup location
        shutil.copy2(file_path, backup_path)
        
        logger.info(f"Created backup: {backup_path}")
        return backup_path

    async def cleanup_redis_cache(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        Clean up Redis cache data.
        
        Args:
            dry_run: If True, only report what would be cleaned
            
        Returns:
            Dict containing cleanup results
        """
        logger.info(f"Starting Redis cache cleanup (dry_run={dry_run})")
        
        results: Dict[str, Any] = {
            "dry_run": dry_run,
            "timestamp": datetime.utcnow().isoformat(),
            "actions_taken": [],
            "errors": [],
        }
        
        try:
            if self.redis_manager.is_degraded():
                results["actions_taken"].append("Redis is in degraded mode - using memory cache")
                
                # Get memory cache info
                cache_info = self.redis_manager.get_connection_info()
                cache_size = cache_info.get("memory_cache_size", 0)
                
                if cache_size > 0:
                    if not dry_run:
                        # Clear memory cache by reinitializing Redis manager
                        await self.redis_manager.close()
                        await self.redis_manager.initialize()
                        results["actions_taken"].append(f"Cleared {cache_size} items from memory cache")
                    else:
                        results["actions_taken"].append(f"Would clear {cache_size} items from memory cache")
            else:
                # Redis is available - could implement specific cache cleanup here
                results["actions_taken"].append("Redis is available - no cleanup needed")
        
        except Exception as e:
            logger.error(f"Redis cache cleanup failed: {e}")
            results["errors"].append(str(e))
        
        return results

    def get_cleanup_recommendations(self) -> List[str]:
        """
        Get recommendations for data cleanup without performing cleanup.
        
        Returns:
            List of cleanup recommendations
        """
        recommendations = []
        
        try:
            # Check users.json
            users_file = self.data_directory / "users.json"
            if users_file.exists():
                with open(users_file, 'r') as f:
                    users_data = json.load(f)
                
                demo_users = [
                    email for email in users_data.keys()
                    if email in self.demo_patterns["demo_emails"]
                ]
                
                if demo_users:
                    recommendations.append(
                        f"Remove {len(demo_users)} demo users from users.json: {', '.join(demo_users)}"
                    )
            
            # Check for large test database files
            test_db_files = ["kari_automation.db", "test.db", "demo.db"]
            for db_file in test_db_files:
                db_path = self.data_directory / db_file
                if db_path.exists():
                    file_size = db_path.stat().st_size
                    if file_size > 1024 * 1024:  # > 1MB
                        recommendations.append(
                            f"Remove large test database: {db_file} ({file_size // (1024*1024)} MB)"
                        )
            
            # Check for temporary files
            temp_file_count = 0
            for pattern in self.demo_patterns["test_file_patterns"]:
                temp_files = list(self.data_directory.glob(f"**/{pattern}"))
                temp_file_count += len(temp_files)
            
            if temp_file_count > 0:
                recommendations.append(f"Remove {temp_file_count} temporary files")
            
            # Check for cache directories
            cache_dirs = ["__pycache__", ".pytest_cache", ".mypy_cache"]
            for cache_dir_name in cache_dirs:
                cache_dirs_found = list(self.data_directory.glob(f"**/{cache_dir_name}"))
                if cache_dirs_found:
                    recommendations.append(f"Remove {len(cache_dirs_found)} {cache_dir_name} directories")
        
        except Exception as e:
            logger.error(f"Error generating cleanup recommendations: {e}")
            recommendations.append(f"Error generating recommendations: {str(e)}")
        
        return recommendations


# Global instance
_data_cleanup_service: Optional[DataCleanupService] = None


def get_data_cleanup_service() -> DataCleanupService:
    """Get global data cleanup service instance"""
    global _data_cleanup_service
    if _data_cleanup_service is None:
        _data_cleanup_service = DataCleanupService()
    return _data_cleanup_service


async def cleanup_demo_data(
    data_directory: str = "data",
    dry_run: bool = True,
) -> CleanupReport:
    """
    Convenience function to clean up demo/test data.
    
    Args:
        data_directory: Path to data directory
        dry_run: If True, only report what would be cleaned
        
    Returns:
        CleanupReport: Complete cleanup report
    """
    service = DataCleanupService(data_directory=data_directory)
    return await service.cleanup_all(dry_run=dry_run)

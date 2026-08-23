"""
File System Tool for AI-Karen
Production-ready file system operations with safety checks.
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import aiofiles
import hashlib
from datetime import datetime

from ai_karen_engine.services.tooling.tool_service import BaseTool, ToolMetadata, ToolCategory, ToolParameter

logger = logging.getLogger(__name__)


class FileSystemTool(BaseTool):
    """
    Production-grade file system tool with safety checks.

    Features:
    - Read, write, list, delete, move, copy operations
    - Safety checks for destructive operations
    - Path validation and sandboxing
    - File metadata extraction
    - Directory traversal protection
    - Size limits and validation
    - Async file operations
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.config = config or {}
        self.max_file_size = self.config.get('max_file_size', 100 * 1024 * 1024)
        self.allowed_paths = self.config.get('allowed_paths', [])
        self.forbidden_paths = self.config.get('forbidden_paths', ['/etc', '/sys', '/proc'])
        self.allow_absolute_paths = self.config.get('allow_absolute_paths', False)
        self.base_directory = self.config.get('base_directory', os.getcwd())

    def _create_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="filesystem",
            description="Perform file system operations (read, write, list, delete, move, copy)",
            category=ToolCategory.SYSTEM,
            version="1.0.0",
            author="AI Karen",
            parameters=[
                ToolParameter(
                    name="operation",
                    type=str,
                    description="Operation to perform (read, write, list, delete, move, copy, info, mkdir)",
                    required=True
                ),
                ToolParameter(
                    name="path",
                    type=str,
                    description="File or directory path",
                    required=True
                ),
                ToolParameter(
                    name="content",
                    type=str,
                    description="Content to write (for write operation)",
                    required=False
                ),
                ToolParameter(
                    name="destination",
                    type=str,
                    description="Destination path (for move/copy operations)",
                    required=False
                ),
                ToolParameter(
                    name="pattern",
                    type=str,
                    description="Pattern for filtering (for list operation)",
                    required=False
                ),
                ToolParameter(
                    name="recursive",
                    type=bool,
                    description="Recursive operation",
                    required=False,
                    default=False
                )
            ],
            return_type=dict,
            examples=[
                {
                    "description": "Read file contents",
                    "parameters": {
                        "operation": "read",
                        "path": "/path/to/file.txt"
                    }
                },
                {
                    "description": "List directory contents",
                    "parameters": {
                        "operation": "list",
                        "path": "/path/to/directory",
                        "pattern": "*.py",
                        "recursive": True
                    }
                }
            ],
            tags=["filesystem", "file", "directory", "io"],
            timeout=30
        )

    async def _execute(self, parameters: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Any:
        operation = parameters["operation"]
        path = parameters["path"]

        if operation == "read":
            return await self.read_file(path)

        elif operation == "write":
            content = parameters.get("content", "")
            overwrite = parameters.get("overwrite", True)
            return await self.write_file(path, content, overwrite=overwrite)

        elif operation == "list":
            pattern = parameters.get("pattern")
            recursive = parameters.get("recursive", False)
            return await self.list_directory(path, pattern=pattern, recursive=recursive)

        elif operation == "delete":
            return await self.delete_file(path)

        elif operation == "move":
            destination = parameters["destination"]
            return await self.move_file(path, destination)

        elif operation == "copy":
            destination = parameters["destination"]
            return await self.copy_file(path, destination)

        elif operation == "info":
            return await self.get_file_info(path)

        elif operation == "mkdir":
            parents = parameters.get("parents", True)
            return await self.create_directory(path, parents=parents)

        else:
            raise ValueError(f"Unknown operation: {operation}")

    def _validate_path(self, path: Union[str, Path]) -> Path:
        path = Path(path)

        try:
            resolved = path.resolve()
        except Exception as e:
            raise ValueError(f"Invalid path: {e}")

        for forbidden in self.forbidden_paths:
            if str(resolved).startswith(forbidden):
                raise ValueError(f"Access to forbidden path: {forbidden}")

        if self.allowed_paths:
            allowed = False
            for allowed_path in self.allowed_paths:
                if str(resolved).startswith(allowed_path):
                    allowed = True
                    break
            if not allowed:
                raise ValueError(f"Path not in allowed paths: {resolved}")

        if not self.allow_absolute_paths and path.is_absolute():
            raise ValueError("Absolute paths not allowed")

        return resolved

    async def read_file(
        self,
        path: Union[str, Path],
        encoding: str = 'utf-8',
        max_size: Optional[int] = None
    ) -> str:
        validated_path = self._validate_path(path)

        if not validated_path.exists():
            raise FileNotFoundError(f"File not found: {validated_path}")

        if not validated_path.is_file():
            raise ValueError(f"Not a file: {validated_path}")

        file_size = validated_path.stat().st_size
        max_size_check = max_size or self.max_file_size
        if file_size > max_size_check:
            raise ValueError(
                f"File too large: {file_size} bytes (max: {max_size_check})"
            )

        async with aiofiles.open(validated_path, 'r', encoding=encoding) as f:
            content = await f.read()

        logger.info(f"Read file: {validated_path} ({file_size} bytes)")
        return content

    async def write_file(
        self,
        path: Union[str, Path],
        content: str,
        encoding: str = 'utf-8',
        create_dirs: bool = True,
        overwrite: bool = True
    ) -> Dict[str, Any]:
        validated_path = self._validate_path(path)

        if validated_path.exists() and not overwrite:
            raise FileExistsError(f"File exists and overwrite=False: {validated_path}")

        if create_dirs:
            validated_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(validated_path, 'w', encoding=encoding) as f:
            await f.write(content)

        file_size = validated_path.stat().st_size
        logger.info(f"Wrote file: {validated_path} ({file_size} bytes)")

        return {
            'path': str(validated_path),
            'size': file_size,
            'created': not validated_path.exists()
        }

    async def list_directory(
        self,
        path: Union[str, Path],
        pattern: Optional[str] = None,
        recursive: bool = False,
        include_hidden: bool = False
    ) -> List[Dict[str, Any]]:
        validated_path = self._validate_path(path)

        if not validated_path.exists():
            raise FileNotFoundError(f"Directory not found: {validated_path}")

        if not validated_path.is_dir():
            raise ValueError(f"Not a directory: {validated_path}")

        results = []

        if recursive and pattern:
            paths = validated_path.rglob(pattern)
        elif recursive:
            paths = validated_path.rglob('*')
        elif pattern:
            paths = validated_path.glob(pattern)
        else:
            paths = validated_path.iterdir()

        for item_path in paths:
            if not include_hidden and item_path.name.startswith('.'):
                continue

            stat = item_path.stat()
            results.append({
                'name': item_path.name,
                'path': str(item_path),
                'type': 'directory' if item_path.is_dir() else 'file',
                'size': stat.st_size if item_path.is_file() else None,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                'permissions': oct(stat.st_mode)[-3:]
            })

        logger.info(f"Listed directory: {validated_path} ({len(results)} items)")
        return results

    async def delete_file(self, path: Union[str, Path]) -> Dict[str, Any]:
        validated_path = self._validate_path(path)

        if not validated_path.exists():
            raise FileNotFoundError(f"File not found: {validated_path}")

        if validated_path.is_dir():
            raise ValueError(f"Cannot delete directory with delete_file: {validated_path}")

        file_size = validated_path.stat().st_size
        validated_path.unlink()

        logger.info(f"Deleted file: {validated_path} ({file_size} bytes)")

        return {
            'path': str(validated_path),
            'size': file_size,
            'deleted': True
        }

    async def delete_directory(
        self,
        path: Union[str, Path],
        recursive: bool = False
    ) -> Dict[str, Any]:
        validated_path = self._validate_path(path)

        if not validated_path.exists():
            raise FileNotFoundError(f"Directory not found: {validated_path}")

        if not validated_path.is_dir():
            raise ValueError(f"Not a directory: {validated_path}")

        if recursive:
            shutil.rmtree(validated_path)
            logger.info(f"Deleted directory recursively: {validated_path}")
        else:
            validated_path.rmdir()
            logger.info(f"Deleted empty directory: {validated_path}")

        return {
            'path': str(validated_path),
            'deleted': True,
            'recursive': recursive
        }

    async def move_file(
        self,
        source: Union[str, Path],
        destination: Union[str, Path]
    ) -> Dict[str, Any]:
        validated_source = self._validate_path(source)
        validated_dest = self._validate_path(destination)

        if not validated_source.exists():
            raise FileNotFoundError(f"Source not found: {validated_source}")

        shutil.move(str(validated_source), str(validated_dest))

        logger.info(f"Moved: {validated_source} -> {validated_dest}")

        return {
            'source': str(validated_source),
            'destination': str(validated_dest),
            'moved': True
        }

    async def copy_file(
        self,
        source: Union[str, Path],
        destination: Union[str, Path]
    ) -> Dict[str, Any]:
        validated_source = self._validate_path(source)
        validated_dest = self._validate_path(destination)

        if not validated_source.exists():
            raise FileNotFoundError(f"Source not found: {validated_source}")

        if not validated_source.is_file():
            raise ValueError(f"Source is not a file: {validated_source}")

        shutil.copy2(str(validated_source), str(validated_dest))

        source_size = validated_source.stat().st_size
        dest_size = validated_dest.stat().st_size

        logger.info(f"Copied: {validated_source} -> {validated_dest} ({dest_size} bytes)")

        return {
            'source': str(validated_source),
            'destination': str(validated_dest),
            'size': dest_size,
            'copied': True
        }

    async def get_file_info(self, path: Union[str, Path]) -> Dict[str, Any]:
        validated_path = self._validate_path(path)

        if not validated_path.exists():
            raise FileNotFoundError(f"Path not found: {validated_path}")

        stat = validated_path.stat()

        file_hash = None
        if validated_path.is_file() and stat.st_size < self.max_file_size:
            hasher = hashlib.sha256()
            async with aiofiles.open(validated_path, 'rb') as f:
                while chunk := await f.read(8192):
                    hasher.update(chunk)
            file_hash = hasher.hexdigest()

        return {
            'path': str(validated_path),
            'name': validated_path.name,
            'type': 'directory' if validated_path.is_dir() else 'file',
            'size': stat.st_size if validated_path.is_file() else None,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'accessed': datetime.fromtimestamp(stat.st_atime).isoformat(),
            'permissions': oct(stat.st_mode)[-3:],
            'owner_uid': stat.st_uid,
            'group_gid': stat.st_gid,
            'sha256': file_hash,
            'extension': validated_path.suffix if validated_path.is_file() else None
        }

    async def create_directory(
        self,
        path: Union[str, Path],
        parents: bool = True,
        exist_ok: bool = True
    ) -> Dict[str, Any]:
        validated_path = self._validate_path(path)

        validated_path.mkdir(parents=parents, exist_ok=exist_ok)

        logger.info(f"Created directory: {validated_path}")

        return {
            'path': str(validated_path),
            'created': True,
            'parents': parents
        }


_filesystem_tool_instance = None


def get_filesystem_tool(config: Optional[Dict[str, Any]] = None) -> FileSystemTool:
    global _filesystem_tool_instance
    if _filesystem_tool_instance is None:
        _filesystem_tool_instance = FileSystemTool(config)
    return _filesystem_tool_instance

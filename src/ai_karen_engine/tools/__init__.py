"""
Tools Package for AI-Karen
Production-ready tool plugins for agent execution

Provides comprehensive tool plugins including:
- Search tools (web search via SearxNG)
- Document processing tools (PDF, DOCX, etc.)
- Image analysis tools (vision models)
- HTTP client tools (API calls, web requests)
- File system tools (read, write, list, etc.)
- Text processing tools (analysis, extraction, formatting)
- Data analysis tools (statistics, aggregation, filtering)
- Code interpreters (Python, IPython, Docker, subprocess)
- Excel tools (spreadsheet operations)
"""

from . import interpreters
from . import search
from . import documents

from ai_karen_engine.tools.http_client_tool import HTTPClientTool
from ai_karen_engine.tools.filesystem_tool import FileSystemTool
from ai_karen_engine.tools.text_processing_tool import TextProcessingTool
from ai_karen_engine.tools.data_analysis_tool import DataAnalysisTool
from ai_karen_engine.tools.web_search_tool import (
    WebSearchTool,
    get_production_tools,
    register_production_tools,
)

__all__ = [
    "interpreters",
    "search",
    "documents",
    "HTTPClientTool",
    "FileSystemTool",
    "TextProcessingTool",
    "DataAnalysisTool",
    "WebSearchTool",
    "get_production_tools",
    "register_production_tools",
]

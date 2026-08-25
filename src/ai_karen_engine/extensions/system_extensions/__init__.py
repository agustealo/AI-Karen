"""
System Extensions Module

Contains built-in system extension packages for the extension system.
"""

from ai_karen_engine.extensions.system_extensions.crawl4ai import Crawl4AIExtension

SYSTEM_EXTENSIONS = {
    "crawl4ai": Crawl4AIExtension,
}

__all__ = ["SYSTEM_EXTENSIONS", "Crawl4AIExtension"]

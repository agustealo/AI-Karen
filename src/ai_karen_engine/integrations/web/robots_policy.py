"""
Robots.txt policy enforcement for web crawling.

This module fetches, parses, and evaluates robots.txt rules so that
crawlers can respect site policies without silently claiming compliance.
"""

from __future__ import annotations

import logging
from typing import Optional, Set
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


class RobotsPolicy:
    """
    Simple robots.txt policy checker.

    Supported directives:
    - User-agent
    - Disallow
    - Allow
    - Crawl-delay (parsed but not enforced here)
    - Sitemap (ignored)
    """

    def __init__(self, user_agent: str = "AI-Karen-Bot") -> None:
        self.user_agent = user_agent
        self._cache: dict[str, tuple[bool, str]] = {}

    async def is_allowed(self, url: str, session: Optional[aiohttp.ClientSession] = None) -> tuple[bool, str]:
        """
        Check whether the given URL is allowed by robots.txt.

        Returns (allowed, reason).
        """
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False, "Invalid URL"

        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        key = f"{parsed.scheme}://{parsed.netloc}"

        if key in self._cache:
            allowed, reason = self._cache[key]
            return allowed, reason

        allowed, reason = await self._fetch_and_check(robots_url, url, session=session)
        self._cache[key] = (allowed, reason)
        return allowed, reason

    async def _fetch_and_check(
        self,
        robots_url: str,
        target_url: str,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> tuple[bool, str]:
        try:
            if session is not None:
                async with session.get(robots_url, timeout=10) as response:
                    if response.status != 200:
                        return True, "robots.txt not found or unreachable; allowed by default"
                    body = await response.text()
            else:
                async with aiohttp.ClientSession() as local_session:
                    async with local_session.get(robots_url, timeout=10) as response:
                        if response.status != 200:
                            return True, "robots.txt not found or unreachable; allowed by default"
                        body = await local_session.text()

            return self._evaluate(body, target_url)
        except Exception as exc:
            logger.debug("Failed to fetch robots.txt from %s: %s", robots_url, exc)
            return True, f"robots.txt fetch failed ({exc}); allowed by default"

    def _evaluate(self, body: str, target_url: str) -> tuple[bool, str]:
        parsed = urlparse(target_url)
        path = parsed.path or "/"

        user_agent_rules: list[tuple[list[str], list[str], str]] = []
        current_agent: Optional[str] = None
        current_disallows: list[str] = []
        current_allows: list[str] = []

        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            if key == "user-agent":
                if current_agent is not None:
                    user_agent_rules.append((current_disallows[:], current_allows[:], current_agent))
                current_agent = value.lower()
                current_disallows = []
                current_allows = []
            elif key == "disallow":
                if current_agent is not None and value:
                    current_disallows.append(value)
            elif key == "allow":
                if current_agent is not None and value:
                    current_allows.append(value)

        if current_agent is not None:
            user_agent_rules.append((current_disallows, current_allows, current_agent))

        matched_ua = None
        for disallows, allows, agent in reversed(user_agent_rules):
            if agent == "*" or agent == self.user_agent.lower():
                matched_ua = (disallows, allows)
                break
            if agent == "*":
                matched_ua = (disallows, allows)

        if matched_ua is None:
            return True, "No applicable user-agent rules; allowed by default"

        disallows, allows = matched_ua

        for allow in allows:
            if path.startswith(allow):
                return True, f"Allowed by Allow: {allow}"

        for disallow in disallows:
            if path == disallow or path.startswith(disallow):
                return False, f"Disallowed by Disallow: {disallow}"

        return True, "Allowed"

    def clear_cache(self) -> None:
        self._cache.clear()

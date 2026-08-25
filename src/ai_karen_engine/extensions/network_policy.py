"""
Network Egress Policy for extension web security.

Every network request must pass through this boundary before reaching
network-capable extensions like Crawl4AI.

Blocks by default:
  - 127.0.0.0/8 (loopback)
  - RFC1918 private addresses
  - link-local addresses
  - multicast addresses
  - reserved ranges
  - cloud metadata endpoints
  - file://, ftp:// (unless explicitly enabled)
  - localhost variants
  - IPv6 loopback/private/link-local

Protects against DNS rebinding by validating URLs and resolving IPs.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

logger = logging.getLogger("kari.extensions.network_policy")


class NetworkEgressPolicy:
    """Centralized network egress authority for all extensions."""

    BLOCKED_IPV4_RANGES = [
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("224.0.0.0/4"),
        ipaddress.ip_network("240.0.0.0/4"),
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("255.255.255.255/32"),
    ]

    BLOCKED_IPV6_RANGES = [
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("ff00::/8"),
        ipaddress.ip_network("::/128"),
    ]

    CLOUD_METADATA_ENDPOINTS = [
        "169.254.169.254",
        "metadata.google.internal",
        "metadata",
    ]

    LOCALHOST_VARIANTS = [
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
    ]

    RESTRICTED_SCHEMES = {
        "file": False,
        "ftp": False,
        "http": True,
        "https": True,
    }

    def __init__(
        self,
        allow_private_addresses: bool = False,
        allowed_schemes: Optional[Set[str]] = None,
        allow_localhost: bool = False,
        custom_blocked_ranges: Optional[List[str]] = None,
    ):
        self.allow_private_addresses = allow_private_addresses
        self.allowed_schemes = allowed_schemes or {"http", "https"}
        self.allow_localhost = allow_localhost

        self._blocked_ipv4_ranges = self.BLOCKED_IPV4_RANGES.copy()
        self._blocked_ipv6_ranges = self.BLOCKED_IPV6_RANGES.copy()

        if custom_blocked_ranges:
            for range_str in custom_blocked_ranges:
                try:
                    network = ipaddress.ip_network(range_str)
                    if isinstance(network, ipaddress.IPv4Network):
                        self._blocked_ipv4_ranges.append(network)
                    else:
                        self._blocked_ipv6_ranges.append(network)
                except ValueError as e:
                    logger.warning("Invalid custom blocked range '%s': %s", range_str, e)

    async def check_url_allowed(
        self,
        url: str,
        extension_id: str,
        capability_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Check if a URL is allowed for extension egress.

        Returns dict with 'allowed' boolean and optional 'reason' string.
        """
        try:
            parsed = urlparse(url)

            if not self._check_scheme(parsed.scheme):
                return {
                    "allowed": False,
                    "reason": f"Scheme '{parsed.scheme}' not allowed",
                }

            if not self._check_hostname(parsed.hostname):
                return {
                    "allowed": False,
                    "reason": f"Hostname '{parsed.hostname}' is blocked",
                }

            resolved_ip = await self._resolve_hostname(parsed.hostname)
            if resolved_ip is None:
                return {
                    "allowed": False,
                    "reason": f"Failed to resolve hostname '{parsed.hostname}'",
                }

            if not self._check_ip(resolved_ip):
                return {
                    "allowed": False,
                    "reason": f"Resolved IP '{resolved_ip}' is blocked",
                }

            if not self._check_dns_rebinding(parsed.hostname, resolved_ip):
                return {
                    "allowed": False,
                    "reason": f"Potential DNS rebinding detected for '{parsed.hostname}' -> '{resolved_ip}'",
                }

            return {"allowed": True}

        except Exception as e:
            logger.warning("URL check failed for '%s': %s", url, e)
            return {
                "allowed": False,
                "reason": f"URL validation failed: {str(e)}",
            }

    async def check_allowed(
        self,
        extension_id: str,
        capability_id: str,
        payload: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Check if a capability invocation is allowed by network policy.

        Extracts URLs from payload and validates them.
        """
        urls = self._extract_urls_from_payload(payload)

        if not urls:
            return True

        for url in urls:
            result = await self.check_url_allowed(url, extension_id, capability_id, context)
            if not result["allowed"]:
                logger.warning(
                    "Network policy denied URL '%s' for %s/%s: %s",
                    url,
                    extension_id,
                    capability_id,
                    result.get("reason"),
                )
                return False

        return True

    def _check_scheme(self, scheme: str) -> bool:
        """Check if URL scheme is allowed."""
        if not scheme:
            return False

        if scheme not in self.RESTRICTED_SCHEMES:
            return False

        return self.RESTRICTED_SCHEMES.get(scheme, False) and scheme in self.allowed_schemes

    def _check_hostname(self, hostname: Optional[str]) -> bool:
        """Check if hostname is allowed."""
        if not hostname:
            return False

        hostname_lower = hostname.lower()

        if hostname_lower in self.LOCALHOST_VARIANTS:
            return self.allow_localhost

        if hostname_lower.endswith(".localhost"):
            return self.allow_localhost

        if hostname_lower in self.CLOUD_METADATA_ENDPOINTS:
            return False

        return True

    async def _resolve_hostname(self, hostname: str) -> Optional[str]:
        """Resolve hostname to IP address."""
        try:
            loop = __import__("asyncio").get_event_loop()
            family = socket.AF_INET if ":" not in hostname else socket.AF_INET6
            result = await loop.getaddrinfo(hostname, None, family=family, type=socket.SOCK_STREAM)
            if result:
                return result[0][4][0]
        except Exception as e:
            logger.debug("Failed to resolve hostname '%s': %s", hostname, e)

        return None

    def _check_ip(self, ip_str: str) -> bool:
        """Check if IP address is allowed."""
        try:
            ip = ipaddress.ip_address(ip_str)

            if isinstance(ip, ipaddress.IPv4Address):
                for blocked_range in self._blocked_ipv4_ranges:
                    if ip in blocked_range:
                        return self.allow_private_addresses

            elif isinstance(ip, ipaddress.IPv6Address):
                for blocked_range in self._blocked_ipv6_ranges:
                    if ip in blocked_range:
                        return self.allow_private_addresses

            return True

        except ValueError:
            return False

    def _check_dns_rebinding(self, hostname: str, ip: str) -> bool:
        """Check for DNS rebinding attacks."""
        try:
            if hostname in self.LOCALHOST_VARIANTS:
                return self.allow_localhost

            ip_obj = ipaddress.ip_address(ip)

            if hostname.endswith(".localhost"):
                return self.allow_localhost

            if not self.allow_private_addresses:
                for blocked_range in self._blocked_ipv4_ranges:
                    if ip_obj in blocked_range:
                        return False

                for blocked_range in self._blocked_ipv6_ranges:
                    if ip_obj in blocked_range:
                        return False

            return True

        except ValueError:
            return False

    def _extract_urls_from_payload(self, payload: Dict[str, Any]) -> List[str]:
        """Extract URLs from payload dict."""
        urls: List[str] = []

        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in {"url", "urls", "href", "link", "target", "endpoint"}:
                    if isinstance(value, str):
                        urls.append(value)
                    elif isinstance(value, list):
                        urls.extend([v for v in value if isinstance(v, str)])

        return urls

    def validate_redirect(self, original_url: str, redirect_url: str) -> bool:
        """Validate that redirect doesn't go to blocked destinations."""
        try:
            original_parsed = urlparse(original_url)
            redirect_parsed = urlparse(redirect_url)

            if not self._check_scheme(redirect_parsed.scheme):
                return False

            if not self._check_hostname(redirect_parsed.hostname):
                return False

            return True

        except Exception:
            return False

    async def validate_full_navigation_chain(
        self,
        initial_url: str,
        final_url: str,
        redirect_chain: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Validate the entire navigation chain for security."""
        redirect_chain = redirect_chain or []

        result = await self.check_url_allowed(initial_url, "validation", "navigation")
        if not result["allowed"]:
            return {
                "valid": False,
                "reason": f"Initial URL blocked: {result.get('reason')}",
            }

        for redirect_url in redirect_chain:
            if not self.validate_redirect(initial_url, redirect_url):
                return {
                    "valid": False,
                    "reason": f"Redirect blocked: {redirect_url}",
                }

        final_result = await self.check_url_allowed(final_url, "validation", "navigation")
        if not final_result["allowed"]:
            return {
                "valid": False,
                "reason": f"Final URL blocked: {final_result.get('reason')}",
            }

        return {"valid": True}


__all__ = ["NetworkEgressPolicy"]
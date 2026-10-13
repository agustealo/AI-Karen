"""Generic response validator for LLM completions."""

import re
from urllib.parse import urlsplit
import logging
from dataclasses import dataclass
from typing import Optional, List, Any

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class ValidationResult:
    valid: bool
    reason: Optional[str] = None
    message: Optional[str] = None

# Generic menu detection
MENU_LIKE_PATTERNS = [
    re.compile(r"what do you want to hear\??", re.IGNORECASE),
    re.compile(r"which (one|option) (do you want|would you like)", re.IGNORECASE),
    re.compile(r"^\s*\(?1\)?[.)]\s+.+", re.MULTILINE),
    re.compile(r"^\s*\(?2\)?[.)]\s+.+", re.MULTILINE),
    re.compile(r"^\s*\(?3\)?[.)]\s+.+", re.MULTILINE),
]

# Generic debug/provider prefix detection
DEBUG_PREFIX_PATTERNS = [
    re.compile(r"^\s*\[[a-z0-9_.:-]+\]\s*", re.IGNORECASE),
    re.compile(r"^\s*\([a-z0-9_.:-]+\s+provider\)\s*", re.IGNORECASE),
]

class ResponseValidator:
    """Validates LLM responses against generic quality and format contracts."""

    def validate(self, text: str, contract: Any) -> ValidationResult:
        """
        Validate response text against a ResponseContract.
        Args:
            text: Raw response from LLM.
            contract: ResponseContract instance defining requirements.
        """
        if not text or not text.strip():
            return ValidationResult(valid=False, reason="empty_response")

        # Citation URLs must be backed by authorized tool evidence.
        if getattr(contract, "purpose", None) == "tool_synthesis" and getattr(contract, "requires_live_data", False):
            allowed: set[str] = set()
            def collect(value: Any) -> None:
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key in {"url", "canonical_url", "final_url"} and isinstance(item, str):
                            parsed = urlsplit(item)
                            if parsed.scheme in {"http", "https"} and parsed.netloc:
                                allowed.add(item.rstrip("/"))
                        else:
                            collect(item)
                elif isinstance(value, list):
                    for item in value:
                        collect(item)
            collect(getattr(contract, "tool_results", []))
            cited = re.findall(r"https?://[^\\s)\\]>]+", text)
            if allowed and not cited:
                return ValidationResult(valid=False, reason="missing_evidence_citation")
            if any(url.rstrip("/").rstrip(".,;") not in allowed for url in cited):
                return ValidationResult(valid=False, reason="unverified_citation_url")

        # 1. Check for debug/provider prefixes
        if getattr(contract, "disallow_debug_prefixes", True):
            for pattern in DEBUG_PREFIX_PATTERNS:
                if pattern.search(text):
                    return ValidationResult(valid=False, reason="debug_prefix_detected")

        # 2. Check for unrequested menus in direct answer mode
        if getattr(contract, "response_mode", "direct_answer") == "direct_answer":
            if getattr(contract, "disallow_unrequested_menu", True):
                if self._looks_like_unrequested_menu(text):
                    return ValidationResult(valid=False, reason="unrequested_menu")

        # 3. Check for prompt echo/leaked instructions
        if getattr(contract, "disallow_prompt_echo", True):
            if self._looks_like_prompt_echo(text, contract):
                return ValidationResult(valid=False, reason="prompt_echo_detected")

        return ValidationResult(valid=True)

    def _looks_like_unrequested_menu(self, text: str) -> bool:
        """Detect if text looks like a menu or a list of options."""
        # A simple check: if more than 2 patterns match or if we have a list-like structure
        matches = 0
        for pattern in MENU_LIKE_PATTERNS:
            if pattern.search(text):
                matches += 1
        
        return matches >= 1

    def _looks_like_prompt_echo(self, text: str, contract: Any) -> bool:
        """Detect if the LLM is just echoing the prompt or instructions."""
        normalized = text.lower()
        
        # Leaked instruction markers
        markers = [
            "latest user message:",
            "assistant context:",
            "system instructions:",
            "respond directly",
            "do not return a menu",
            "ready to help",
            "i'm ready to help",
        ]
        
        for marker in markers:
            if marker in normalized:
                return True
                
        # If it exactly matches the latest user message (echoing)
        user_msg = getattr(contract, "latest_user_message", "").lower()
        if user_msg and user_msg in normalized and len(normalized) < len(user_msg) + 20:
            return True
            
        return False

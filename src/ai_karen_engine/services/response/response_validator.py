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
                    # Discovery links are not fetched evidence and cannot
                    # authorize a citation to page content.
                    # Only verified fetched pages may authorize model citations.
                    # Other nested tool metadata is never a source of truth.
                    if value.get("evidence_level") != "fetched_page":
                        for key, item in value.items():
                            if key not in {"url", "canonical_url", "final_url"}:
                                collect(item)
                        return
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
            if not allowed:
                return ValidationResult(valid=False, reason="missing_authorized_source_evidence")
            cited = re.findall(r"https?://[^\s)\]>]+", text)
            if not cited:
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

    def validate_observation(self, text: str, intent: str, evidence: dict[str, Any]) -> ValidationResult:
        """Conservative second gate for model-authored live observations.

        Reject unsupported facts rather than turning ambiguous generation into
        apparently verified weather or time. Numeric fidelity is necessary but
        is not a substitute for the structured evidence in the presentation.
        """
        if not evidence or intent not in {"search.weather", "time.current"}:
            return ValidationResult(valid=False, reason="missing_observation_evidence")
        # Verified observations are not fetched pages and authorize no URL citations.
        if re.search(r"https?://[^\\s)\\]>]+", text, re.IGNORECASE):
            return ValidationResult(valid=False, reason="unverified_observation_url")
        number_pattern = r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)"
        authorized = set(re.findall(number_pattern, " ".join(map(str, evidence.values()))))
        reported = set(re.findall(number_pattern, text))
        if not reported.issubset(authorized):
            return ValidationResult(valid=False, reason="unverified_observation_number")

        lowered = text.casefold()
        if intent == "search.weather":
            # Never let a current observation silently become a future forecast.
            forecast_words = r"\b(?:tomorrow|next week|next month|will rain|will snow|forecast)\b"
            if re.search(forecast_words, lowered) and not evidence.get("forecast"):
                return ValidationResult(valid=False, reason="unsupported_forecast")
            allowed_conditions = " ".join(
                str(evidence.get(k) or "") for k in ("condition", "conditions")
            ).casefold()
            condition_terms = (
                "sunny", "cloudy", "rainy", "raining", "snowy", "snowing",
                "stormy", "foggy", "clear", "overcast", "windy",
            )
            stated = {term for term in condition_terms if re.search(r"\b" + term + r"\b", lowered)}
            if stated and not all(term in allowed_conditions for term in stated):
                return ValidationResult(valid=False, reason="unsupported_weather_condition")
            # Explicit temperature-unit claims must be supported by the same
            # field or a declared unit. Do not infer units from country.
            unit = str(evidence.get("unit") or evidence.get("units") or "").casefold()
            celsius = bool(re.search(r"\b(?:celsius|degrees c|°c)\b", lowered))
            fahrenheit = bool(re.search(r"\b(?:fahrenheit|degrees f|°f)\b", lowered))
            if celsius and "temperature_c" not in evidence and unit not in {"c", "°c", "celsius"}:
                return ValidationResult(valid=False, reason="unsupported_temperature_unit")
            if fahrenheit and "temperature_f" not in evidence and unit not in {"f", "°f", "fahrenheit"}:
                return ValidationResult(valid=False, reason="unsupported_temperature_unit")
        else:
            zones = [
                str(evidence[k]).casefold() for k in ("timezone", "resolved_timezone")
                if evidence.get(k)
            ]
            claimed = re.findall(r"\b(?:America|Europe|Asia|Africa|Australia|Pacific)/[A-Za-z_]+\b", text)
            if any(zone.casefold() not in zones for zone in claimed):
                return ValidationResult(valid=False, reason="unsupported_timezone")
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

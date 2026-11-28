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
    # Ordered, deduplicated fetched URL identities from an entirely valid
    # grounded answer; no claim-level entailment or current-access grant.
    verified_citation_urls: tuple[str, ...] = ()

# Generic menu detection
MENU_LIKE_PATTERNS = [
    re.compile(r"what do you want to hear\??", re.IGNORECASE),
    re.compile(r"which (one|option) (do you want|would you like)", re.IGNORECASE),
]

# Generic debug/provider prefix detection
DEBUG_PREFIX_PATTERNS = [
    re.compile(r"^\s*\[[a-z0-9_.:-]+\]\s*", re.IGNORECASE),
    re.compile(r"^\s*\([a-z0-9_.:-]+\s+provider\)\s*", re.IGNORECASE),
]

# Match schemes case-insensitively: browsers accept uppercase HTTPS, so a
# lowercase-only scanner could miss a second, unauthorized link.
_HTTP_CITATION = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)


def _citation_url_identity(value: str) -> Optional[str]:
    """Return exact fetched URL identity, normalizing only scheme case.

    Do not collapse path slashes, query strings or fragments; those may
    identify different evidence. Reject ambiguous parser inputs rather than
    letting malformed tool data throw or silently change the destination.
    """
    if (
        not value or len(value) > 2000
        or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch == chr(92)
               for ch in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.port == 0
        ):
            return None
    except ValueError:
        return None
    # Preserve every byte after the scheme, including an empty query or
    # fragment delimiter. Re-serializing the URL can discard delimiters.
    return parsed.scheme + value[value.index(":"):]


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

        verified_citations: dict[str, None] = {}
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
                            identity = _citation_url_identity(item)
                            if identity is not None:
                                allowed.add(identity)
                        else:
                            collect(item)
                elif isinstance(value, list):
                    for item in value:
                        collect(item)
            collect(getattr(contract, "tool_results", []))
            if not allowed:
                return ValidationResult(valid=False, reason="missing_authorized_source_evidence")
            cited = _HTTP_CITATION.findall(text)
            if not cited:
                return ValidationResult(valid=False, reason="missing_evidence_citation")
            for url in cited:
                # Prefer the exact URL. Only sentence punctuation may be
                # removed, and only when the resulting URL is authorized.
                identity = _citation_url_identity(url)
                if identity is None or identity not in allowed:
                    identity = _citation_url_identity(url.rstrip(".,;"))
                if identity is None or identity not in allowed:
                    return ValidationResult(valid=False, reason="unverified_citation_url")
                verified_citations[identity] = None
                if len(verified_citations) > 50:
                    return ValidationResult(valid=False, reason="citation_limit_exceeded")

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

        # No partial result escapes if any later response check fails.
        return ValidationResult(valid=True, verified_citation_urls=tuple(verified_citations))

    def validate_observation(self, text: str, intent: str, evidence: dict[str, Any]) -> ValidationResult:
        """Conservative second gate for model-authored live observations.

        Reject unsupported facts rather than turning ambiguous generation into
        apparently verified weather or time. Numeric fidelity is necessary but
        is not a substitute for the structured evidence in the presentation.
        """
        if not evidence or intent not in {"search.weather", "time.current"}:
            return ValidationResult(valid=False, reason="missing_observation_evidence")
        # Do not surface policy and memory-routing terminology as an answer,
        # even when every factual number matches a verified observation.
        # Keep this refusal in the single response-validation owner. The
        # runtime falls back to the tool's actual observation without
        # attributing the rejected output to a model.
        if re.search(
            r"\b(?:time\.current|search\.weather|continuity\s+(?:primary\s+)?candidate|"
            r"recurring\s+behavioral\s+patterns|execution\s+policy\s+decision|"
            r"authorized\s+execution\s+plan|hidden\s+system\s+prompt)\b",
            text, re.IGNORECASE,
        ):
            return ValidationResult(
                valid=False, reason="internal_observation_metadata",
            )
        # Verified observations are not fetched pages and authorize no URL citations.
        if re.search(r"https?://[^\s)\]>]+", text, re.IGNORECASE):
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
        # Numbered steps, outlines and research sections are valid direct
        # answers. Only explicit choice-seeking language is a menu signal.
        return any(pattern.search(text) for pattern in MENU_LIKE_PATTERNS)

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

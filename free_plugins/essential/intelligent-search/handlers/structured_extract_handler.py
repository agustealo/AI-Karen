import logging
from typing import Any, Dict, Optional

from .base import BaseWebSearchModeHandler

logger = logging.getLogger(__name__)


class StructuredExtractHandler(BaseWebSearchModeHandler):
    """
    Structured extraction intent handler.
    """

    MODE = "structured_extract"

    DEFAULTS: Dict[str, Any] = {
        "max_urls": 5,
        "depth": 1,
        "require_citations": True,
        "query_strategy": "targeted_extract",
        "extraction_preference": "schema_first",
        "allow_llm_fallback": True,
        "freshness_bias": 0.5,
    }

    async def prepare(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        safe_context = context or {}
        normalized_query = self._normalize_query(query)
        can_execute, reason = self._can_execute(normalized_query)

        extraction_schema = (
            safe_context.get("schema")
            or safe_context.get("extraction_schema")
            or self._read_manifest_setting("schema")
        )
        extraction_type = self._resolve_extraction_type(safe_context, extraction_schema)
        extraction_instruction = self._resolve_extraction_instruction(safe_context)
        target_fields = self._normalize_list(safe_context.get("target_fields"))
        target_selectors = self._normalize_dict(safe_context.get("target_selectors"))

        max_urls = self._coerce_positive_int(
            safe_context.get("max_urls"),
            self._read_manifest_setting("max_urls"),
            self.DEFAULTS["max_urls"],
        )
        depth = self._coerce_positive_int(
            safe_context.get("depth"),
            self._read_manifest_setting("depth"),
            self.DEFAULTS["depth"],
        )
        allow_llm_fallback = self._coerce_bool(
            safe_context.get("allow_llm_fallback"),
            self._read_manifest_setting("allow_llm_fallback"),
            self.DEFAULTS["allow_llm_fallback"],
        )

        response = {
            "extension_id": self._get_manifest_id(),
            "extension_name": self._get_manifest_name(),
            "intent_type": "web_search",
            "mode": self.MODE,
            "query": normalized_query,
            "can_execute": can_execute,
            "reason": reason,
            "max_urls": max_urls,
            "depth": depth,
            "require_citations": self.DEFAULTS["require_citations"],
            "query_strategy": self.DEFAULTS["query_strategy"],
            "freshness_bias": self.DEFAULTS["freshness_bias"],
            "extraction": {
                "type": extraction_type,
                "schema": extraction_schema,
                "instruction": extraction_instruction,
                "target_fields": target_fields,
                "target_selectors": target_selectors,
                "preference": self.DEFAULTS["extraction_preference"],
                "allow_llm_fallback": allow_llm_fallback,
            },
            "domain_policy": {
                "allowed_domains": self._normalize_list(
                    safe_context.get("allowed_domains")
                ),
                "blocked_domains": self._normalize_list(
                    safe_context.get("blocked_domains")
                ),
            },
            "context_hints": self._extract_context_hints(safe_context),
            "telemetry": {
                "handler": self.__class__.__name__,
                "manifest_id": self._get_manifest_id(),
                "mode": self.MODE,
                "extraction_type": extraction_type,
            },
        }

        logger.debug(
            "Prepared structured extraction intent strategy",
            extra={
                "extension_id": response["extension_id"],
                "mode": response["mode"],
                "can_execute": response["can_execute"],
                "extraction_type": extraction_type,
            },
        )

        return response

    async def execute(self, config: Dict[str, Any], query: str) -> Dict[str, Any]:
        prepared = dict(config or {})
        normalized_query = self._normalize_query(query or prepared.get("query", ""))

        if not prepared.get("query"):
            prepared["query"] = normalized_query

        if "can_execute" not in prepared or "reason" not in prepared:
            can_execute, reason = self._can_execute(normalized_query)
            prepared["can_execute"] = can_execute
            prepared["reason"] = reason

        prepared.setdefault("extension_id", self._get_manifest_id())
        prepared.setdefault("extension_name", self._get_manifest_name())
        prepared.setdefault("intent_type", "web_search")
        prepared.setdefault("mode", self.MODE)
        prepared.setdefault("require_citations", self.DEFAULTS["require_citations"])
        prepared.setdefault("query_strategy", self.DEFAULTS["query_strategy"])

        extraction = dict(prepared.get("extraction") or {})
        extraction.setdefault(
            "type", "schema" if extraction.get("schema") else "instruction"
        )
        extraction.setdefault("preference", self.DEFAULTS["extraction_preference"])
        extraction.setdefault("allow_llm_fallback", self.DEFAULTS["allow_llm_fallback"])
        extraction.setdefault("schema", None)
        extraction.setdefault("instruction", None)
        extraction.setdefault("target_fields", [])
        extraction.setdefault("target_selectors", {})
        prepared["extraction"] = extraction

        prepared.setdefault(
            "domain_policy",
            {
                "allowed_domains": [],
                "blocked_domains": [],
            },
        )

        return prepared

    def _resolve_extraction_type(
        self,
        context: Dict[str, Any],
        extraction_schema: Any,
    ) -> str:
        explicit = context.get("extraction_type") or self._read_manifest_setting(
            "extraction_type"
        )
        if isinstance(explicit, str):
            normalized = explicit.strip().lower().replace("-", "_")
            if normalized in {"schema", "css", "xpath", "instruction", "llm"}:
                return normalized

        if extraction_schema:
            return "schema"

        if context.get("target_selectors"):
            return "css"

        return "instruction"

    def _resolve_extraction_instruction(self, context: Dict[str, Any]) -> Optional[str]:
        instruction = (
            context.get("extraction_instruction")
            or context.get("instruction")
            or self._read_manifest_setting("extraction_instruction")
            or self._read_manifest_setting("instruction")
        )

        if not isinstance(instruction, str):
            return None

        normalized = " ".join(instruction.strip().split())
        return normalized or None

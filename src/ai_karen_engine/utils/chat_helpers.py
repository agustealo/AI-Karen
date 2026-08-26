import re
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)


def strip_internal_analysis_leakage(text: str) -> str:
    """Remove common model thought leakage or internal markers."""
    if not text:
        return ""

    original = str(text or "").replace("\r\n", "\n")
    cleaned = original
    lowered = cleaned.lower()

    # Known internal-analysis scaffold markers
    internal_markers = (
        "to complete the session continuity summary",
        "session continuity summary:",
        "since the user has greeted again without a specific new request",
        "this is not a complete meaningful response",
    )

    for marker in internal_markers:
        index = lowered.find(marker)
        if 0 <= index <= 240:
            cleaned = cleaned[:index]
            lowered = cleaned.lower()

    # Known internal-analysis line patterns
    internal_patterns = (
        r"^\s*to complete the session continuity summary.*$",
        r"^\s*session continuity summary:\s*.*$",
        r"^\s*in summary:\s*$",
        r"^\s*let'?s see if we can make sure the chat response is complete.*$",
        r"^\s*i(?:'|\u2019)ll acknowledge their greeting and be ready to assist.*$",
    )

    for pattern in internal_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.MULTILINE)

    # Standard thought tag cleanup
    cleaned = re.sub(
        r"<(thought|analysis|internal|reasoning)>.*?</\1>",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(
        r"<(thought|analysis|internal|reasoning)>.*$",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )

    cleaned = re.sub(r"^\s*=+\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    
    return cleaned.strip()


def is_low_information_content(content: str) -> bool:
    """Check if the content is functionally empty or low value."""
    text = str(content or "").strip()
    if not text:
        return True
    if len(text) == 1 and not text.isalnum():
        return True
    # If it only consists of punctuation or whitespace
    punctuation_only_chars = set(".-_=`'\"!?,:;()[]{}|/\\ \n\t")
    if all(ch in punctuation_only_chars for ch in text):
        return True
    return False


def is_plain_heading_line(line: str) -> bool:
    """Heuristic for plain (non-markdown) section headings."""
    stripped = (line or "").strip()
    if not stripped:
        return False
    if stripped.startswith(("#", "-", "*", ">", "`")):
        return False
    if len(stripped) > 80:
        return False
    if stripped.endswith((".", "!", "?", ":", ";", ",")):
        return False
    if re.search(r"\d{2,}", stripped):
        return False
    words = [w for w in stripped.split() if w]
    known_single_word_headings = {
        "introduction",
        "conclusion",
        "summary",
        "overview",
        "appendix",
    }
    if len(words) == 1 and stripped.lower() not in known_single_word_headings:
        return False
    if len(words) > 8:
        return False
    alpha_words = [w for w in words if re.search(r"[A-Za-z]", w)]
    if not alpha_words:
        return False
    title_like = sum(1 for w in alpha_words if w[:1].isupper())
    return title_like >= max(1, int(len(alpha_words) * 0.6))


def collapse_repeated_sentences(text: str) -> str:
    """Collapse obvious consecutive repeated sentences in long-form text."""
    raw = str(text or "").strip()
    if not raw:
        return raw

    blocks = [blk for blk in re.split(r"\n{2,}", raw) if blk.strip()]
    collapsed_blocks: List[str] = []

    for block in blocks:
        sentence_parts = re.split(r"(?<=[.!?])\s+", block.strip())
        normalized_prev = ""
        kept: List[str] = []
        repeat_run = 0

        for sentence in sentence_parts:
            stripped = sentence.strip()
            if not stripped:
                continue
            normalized = re.sub(r"\s+", " ", stripped).lower()
            if normalized == normalized_prev:
                repeat_run += 1
                if repeat_run >= 1:
                    continue
            else:
                repeat_run = 0
                normalized_prev = normalized
            kept.append(stripped)

        collapsed_blocks.append(" ".join(kept).strip())

    return "\n\n".join(blk for blk in collapsed_blocks if blk).strip()


def dedupe_and_markdown_sections(text: str) -> str:
    """Remove repeated section blocks and normalize plain headings into markdown."""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    if not lines:
        return str(text or "")

    has_markdown_heading = any(re.match(r"^\s*#{1,6}\s+\S", ln) for ln in lines)
    sections: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {"heading": None, "is_heading": False, "body": []}

    def push_current() -> None:
        if current["heading"] is None and not current["body"]:
            return
        sections.append({
            "heading": current["heading"],
            "is_heading": current["is_heading"],
            "body": list(current["body"]),
        })

    for line in lines:
        is_md_heading = bool(re.match(r"^\s*#{1,6}\s+\S", line))
        is_plain_heading = is_plain_heading_line(line)
        if is_md_heading or is_plain_heading:
            push_current()
            current = {"heading": line.strip(), "is_heading": True, "body": []}
            continue
        current["body"].append(line)
    push_current()

    seen_sections: set[tuple[str, str]] = set()
    deduped: List[Dict[str, Any]] = []
    for sec in sections:
        heading = sec.get("heading")
        body_lines = sec.get("body", [])
        body_text = collapse_repeated_sentences("\n".join(body_lines).strip())
        if heading:
            canon_heading = re.sub(r"\s+", " ", re.sub(r"^#+\s*", "", heading).strip()).lower()
            key = (canon_heading, re.sub(r"\s+", " ", body_text).strip())
            if key in seen_sections:
                continue
            seen_sections.add(key)
        deduped.append(sec)

    output: List[str] = []
    heading_index = 0
    for sec in deduped:
        heading = sec.get("heading")
        body_lines = sec.get("body", [])
        if heading:
            cleaned_heading = re.sub(r"^#+\s*", "", heading).strip()
            if has_markdown_heading:
                output.append(f"## {cleaned_heading}" if not heading.lstrip().startswith("#") else heading)
            else:
                output.append(f"# {cleaned_heading}" if heading_index == 0 else f"## {cleaned_heading}")
            heading_index += 1
        if body_lines:
            body_text = collapse_repeated_sentences("\n".join(body_lines).strip())
            if body_text:
                output.append(body_text)

    rendered = "\n\n".join(chunk.strip() for chunk in output if str(chunk).strip())
    rendered = re.sub(r"\n{3,}", "\n\n", rendered).strip()
    return rendered or str(text or "").strip()


def finalize_user_visible_text(response_text: str, user_message: str) -> str:
    """Final pass for user-visible text quality and article structure cleanup."""
    sanitized = strip_internal_analysis_leakage(response_text)
    if not sanitized or is_low_information_content(sanitized):
        return sanitized

    user_lower = str(user_message or "").lower()
    response = str(sanitized or "")
    
    article_triggers = ("full article", "write an article", "article on", "long-form", "blog post")
    should_enforce = any(trigger in user_lower for trigger in article_triggers)
    
    if not should_enforce:
        plain_heading_count = sum(1 for ln in response.splitlines() if is_plain_heading_line(ln))
        markdown_heading_count = len(re.findall(r"(?m)^\s*#{1,6}\s+\S", response))
        should_enforce = (plain_heading_count + markdown_heading_count) >= 4 and len(response) >= 500

    if should_enforce:
        return dedupe_and_markdown_sections(sanitized)
    return sanitized


def extract_stream_text(payload: Dict[str, Any]) -> str:
    """Extract user-visible response text from a runtime payload."""
    for key in ("answer", "message", "response", "final", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_processing_status(status: Any, default: str = "processing") -> str:
    """Normalize processing status values to stable snake_case keys."""
    if status is None:
        return default

    raw_status = getattr(status, "value", status)
    status_text = str(raw_status or "").strip().lower()
    if not status_text:
        return default

    return status_text.replace("-", "_").replace(" ", "_")


def normalize_session_id(session_id: Optional[str]) -> str:
    """Return a UUID session id for downstream memory/orchestration services."""
    raw = str(session_id or "").strip()
    if not raw:
        return str(uuid.uuid4())

    candidates = [raw]
    if raw.startswith("chat_"):
        candidates.append(raw[len("chat_") :])

    for candidate in candidates:
        try:
            return str(uuid.UUID(candidate))
        except Exception:
            continue

    generated = str(uuid.uuid4())
    logger.warning(
        "Invalid session_id received; generated replacement.",
        extra={
            "provided_session_id": raw,
            "normalized_session_id": generated,
        },
    )
    return generated


def json_safe(value: Any) -> Any:
    """Convert response metadata into JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


async def resolve_user_context(request: Any) -> Optional[Dict[str, Any]]:
    """Resolve user context from FastAPI request state or authenticated context."""
    # First check request state (set by middleware)
    try:
        if (
            hasattr(request, "state")
            and hasattr(request.state, "user")
            and request.state.user
        ):
            return request.state.user
    except AttributeError:
        pass

    # Best-effort fallback to dependency resolver
    try:
        from ai_karen_engine.core.services.dependencies import bypass_user_context_func

        return await bypass_user_context_func(request)
    except Exception:
        return None


def is_production_env() -> bool:
    """Check if the environment is production."""
    env = os.getenv("ENVIRONMENT", os.getenv("KARI_ENV", "development")).lower()
    return env in ("production", "prod")


async def resolve_display_name(
    auth_service: Any, user_id: str, request_context: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """Resolve the display name for a given user ID."""
    if not user_id:
        return None

    # Fast path: Check context/request
    if request_context and isinstance(request_context, dict):
        if request_context.get("full_name"):
            return str(request_context["full_name"])
        if request_context.get("display_name"):
            return str(request_context["display_name"])

    # Try the auth service
    if auth_service and hasattr(auth_service, "get_user_display_name"):
        try:
            return await auth_service.get_user_display_name(user_id)
        except Exception:
            pass

    return None


def resolve_tenant_id(request_context: Optional[Dict[str, Any]] = None) -> str:
    """Resolve the tenant ID for a given request block."""
    if not request_context:
        return "default"

    tenant_id = (
        request_context.get("tenant_id") or request_context.get("org_id") or "default"
    )
    return str(tenant_id)


def build_user_identity_line(display_name: str) -> str:
    """Return a line to inject into the system prompt for user identity."""
    return f"The current user is: {display_name}."


def _extract_recent_history_lines(history: Any, limit: int = 6) -> List[str]:
    lines: List[str] = []
    if not isinstance(history, list):
        return lines
    for item in history[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not role or not content:
            continue
        lines.append(f"{role.title()}: {content}")
    return lines


def wants_long_form_markdown_article(
    current_user_message: str,
    recent_messages: Any,
) -> bool:
    """Detect if the user is asking for a long-form article/blog post."""
    text_parts: List[str] = [str(current_user_message or "").lower()]
    if isinstance(recent_messages, list):
        for item in recent_messages[-6:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip().lower()
            if role == "user" and content:
                text_parts.append(content)

    combined = "\n".join(text_parts)
    long_form_markers = (
        "full article",
        "write an article",
        "blog article",
        "blog post",
        "full post",
        "in-depth article",
        "technical write-up",
        "comprehensive guide",
    )
    return any(marker in combined for marker in long_form_markers)

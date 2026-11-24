"""Canonical search document chunking, boilerplate rejection, and lexical ranking."""

from __future__ import annotations

import hashlib
import html
import logging
import math
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_MARKDOWN_IMAGE = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"\[([^\]\n]+)\]\((?:\\.|[^)\n])*\)", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
_WORD = re.compile(r"\b\w+\b", re.UNICODE)
_TAG = re.compile(r"<[^>\n]{1,500}>")
_UNTRUSTED_HTML_BLOCK = re.compile(
    r"<(script|style|nav|aside|footer)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_CITATION = re.compile(r"\[(?:\d+|citation needed|edit)\]", re.IGNORECASE)
_NAVIGATION = re.compile(
    r"^(?:jump to content|main menu|navigation|personal tools|contribute|"
    r"contents|toggle the table of contents|tools|print/export|in other projects|"
    r"appearance|languages|edit links|from wikipedia|read|view history|"
    r"create account|log in|donate|sidebar|move to sidebar|hide)$",
    re.IGNORECASE,
)
# Page furniture is NOT evidence, regardless of how many tokens it contains.
# Match section starts only, never reject a factual paragraph just because it
# mentions "references" or "navigation" in the middle of a sentence.
_BOILERPLATE_START = re.compile(
    r"^(?:related posts?|recommended articles?|reader interactions?|"
    r"leave a reply|cancel reply|recent posts?|this day in history|"
    r"references(?:\s*\[edit\]|\s*\d+[.)]|:)|"
    r"notes(?:\s*\[edit\]|\s*\d+[.)]|:)|"
    r"external links|see also|further reading|"
    r"navigation|personal tools|tools|print/export|appearance|"
    r"main menu|jump to content|table of contents|posted in|"
    r"edit links|in other projects)(?:\s|:|\[|$)",
    re.IGNORECASE,
)

def _plain_text(text: str) -> str:
    """Canonical display/evidence text; never render untrusted markup."""
    normalized = html.unescape(str(text or ""))
    normalized = _UNTRUSTED_HTML_BLOCK.sub(" ", normalized)
    normalized = _MARKDOWN_IMAGE.sub("", normalized)
    normalized = _MARKDOWN_LINK.sub(lambda match: match.group(1), normalized)
    normalized = _TAG.sub(" ", normalized)
    normalized = _INLINE_CITATION.sub("", normalized)
    normalized = _URL.sub("", normalized)
    normalized = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", normalized)
    normalized = re.sub(r"(?m)^\s{0,3}>\s?", "", normalized)
    normalized = re.sub(r"\*\*(\S(?:.*?\S)?)\*\*", r"\1", normalized)
    # Preserve __init__, _field_name and ** operators in technical docs.
    normalized = normalized.replace(chr(96), "")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"[ \t]*\n[ \t]*", "\n", normalized)
    # Removing HTML tags can leave spaces before punctuation. Do not alter
    # meaningful operators or identifiers in technical source text.
    normalized = re.sub(r" +([,.;:!?])", r"\1", normalized)
    return normalized.strip()


def _is_article_content(section: str) -> bool:
    """Reject navigation, recommendations and footnotes before ranking."""
    stripped = section.strip()
    if not stripped:
        return False
    raw_lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    first = _plain_text(raw_lines[0]).strip(" *#.:") if raw_lines else ""
    if _BOILERPLATE_START.match(first) or _NAVIGATION.fullmatch(first):
        return False
    plain = _plain_text(stripped)
    if len(plain) < 90:
        return False
    # Reject link-heavy directories and headings dressed as page content.
    link_count = len(_MARKDOWN_LINK.findall(stripped)) + len(_MARKDOWN_IMAGE.findall(stripped))
    if link_count >= 3 and (
        link_count * 40 > len(plain)
        or (len(raw_lines) > 2 and
            sum(line.startswith(("* ", "- ", "![", "[ ")) for line in raw_lines) * 2 >= len(raw_lines))
    ):
        return False
    sentences = re.findall(r"[.!?](?:\s|$)", plain)
    if not sentences and len(plain.split()) < 28:
        return False
    return True


class SearchResultProcessor:
    """One canonical owner for search chunk extraction and lexical relevance."""

    def process(self, results: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        if not results:
            return []
        return self._rank(self._deduplicate(self._chunk(results)), query)[:15]

    @staticmethod
    def clean_excerpt(text: str, limit: int = 1500) -> str:
        """Bounded, presentation-safe text for user-visible discovery excerpts."""
        if not isinstance(text, str) or limit <= 0:
            return ""
        cleaned = " ".join(_plain_text(text[: max(limit * 5, 2000)]).split())
        if _BOILERPLATE_START.match(cleaned):
            return ""
        return cleaned[:limit].rstrip()

    def readable_preview(self, result: Dict[str, Any], limit: int = 12000) -> str:
        """Return source article prose, not the original web page chrome.

        This is only a preview; provenance and full document storage remain
        separate. Results are sourced from the same filter as evidence ranking.
        """
        if limit <= 0:
            return ""
        paragraphs: List[str] = []
        used: set[str] = set()
        length = 0
        for chunk in self._chunk([result]):
            paragraph = chunk["content"]
            fingerprint = hashlib.sha256(paragraph.casefold().encode()).hexdigest()
            if fingerprint in used:
                continue
            used.add(fingerprint)
            if length + len(paragraph) + 2 > limit:
                if not paragraphs:
                    paragraphs.append(paragraph[:limit].rstrip())
                break
            paragraphs.append(paragraph)
            length += len(paragraph) + 2
        return "\n\n".join(paragraphs)

    def _chunk(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        for result in results:
            document = str(result.get("markdown") or result.get("text") or "")
            url = str(result.get("url") or "")
            if not document or not urlparse(url).netloc:
                continue
            for index, section in enumerate(re.split(r"\n\s*\n", document[:500_000])):
                if not _is_article_content(section):
                    continue
                content = _plain_text(section)
                chunks.append({
                    "url": url,
                    "content": content[:2500],
                    "source_metadata": result.get("metadata", {}),
                    "chunk_id": f"{hashlib.md5(url.encode()).hexdigest()[:8]}_{index}",
                })
        return chunks

    def _deduplicate(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        unique = []
        for chunk in chunks:
            fingerprint = hashlib.sha256(" ".join(chunk["content"].casefold().split()).encode()).hexdigest()
            if fingerprint not in seen:
                seen.add(fingerprint)
                unique.append(chunk)
        return unique

    def _rank(self, chunks: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        terms = {word for word in _WORD.findall(query.casefold()) if len(word) >= 3}
        ranked = []
        for chunk in chunks:
            score = self._calculate_score(chunk["content"], terms)
            context = str(chunk.get("source_metadata", {}).get("title") or "") + " " + urlparse(chunk["url"]).path.replace("_", " ")
            # Article-level topic relevance can support otherwise factual paragraphs
            # that do not repeat the query words in every sentence.
            if score == 0 and self._calculate_score(context, terms) > 0:
                score = 0.5
            if score > 0:
                chunk["score"] = score
                ranked.append(chunk)
        return sorted(ranked, key=lambda item: item["score"], reverse=True)

    def _calculate_score(self, content: str, query_words: set[str]) -> float:
        frequencies: Dict[str, int] = {}
        for word in _WORD.findall(content.casefold()):
            frequencies[word] = frequencies.get(word, 0) + 1
        if not query_words:
            return 0.0
        matched = sum(1 for word in query_words if frequencies.get(word, 0))
        if not matched:
            return 0.0
        # Favor coverage of the whole query, then damp repetition; normalize
        # long pages so repeated incidental words cannot saturate a fixed cap.
        term_signal = sum(math.log1p(frequencies.get(word, 0)) for word in query_words)
        total_terms = sum(frequencies.values())
        return round((matched / len(query_words)) * term_signal /
                     math.sqrt(max(1.0, total_terms / 100.0)), 6)

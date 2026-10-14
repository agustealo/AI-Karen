"""Canonical search document chunking, boilerplate rejection, and lexical ranking."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_LINK = re.compile(r"!?\[[^\]]*\]\(https?://[^)]*\)", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
_WORD = re.compile(r"\b\w+\b", re.UNICODE)
_NAVIGATION = re.compile(
    r"^(?:jump to content|main menu|navigation|personal tools|contribute|"
    r"contents|toggle the table of contents|tools|print/export|in other projects|"
    r"appearance|languages|edit links|from wikipedia|read|view history|"
    r"create account|log in|donate|sidebar|move to sidebar|hide)$",
    re.IGNORECASE,
)
_MENU_MARKERS = (
    "move to sidebar", "toggle the table of contents", "main menu",
    "jump to content", "personal tools", "navigation menu",
    "learn to edit", "create account", "download as pdf",
)


def _plain_text(text: str) -> str:
    """Return readable prose from Markdown; never preserve raw link targets."""
    text = _LINK.sub(lambda m: re.sub(r"^!?\[|\]\(.*$", "", m.group()), text)
    text = _URL.sub("", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"[ 	]+", " ", text)
    return text.strip()


def _is_article_content(section: str) -> bool:
    """Reject navigation lists and short fragments before ranking."""
    stripped = section.strip()
    if not stripped:
        return False
    raw_lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    plain = _plain_text(stripped)
    if len(plain) < 90:
        return False
    if any(marker in stripped[:350].casefold() for marker in _MENU_MARKERS):
        return False
    if raw_lines and _NAVIGATION.fullmatch(raw_lines[0].strip("# *")):
        return False
    link_count = len(_LINK.findall(stripped))
    if link_count >= 3 and (link_count * 45 > len(plain) or len(raw_lines) > 2 and
                            sum(line.startswith(("* ", "- ", "![", "[ ")) for line in raw_lines) * 2 >= len(raw_lines)):
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

    def _chunk(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        for result in results:
            document = str(result.get("markdown") or result.get("text") or "")
            url = str(result.get("url") or "")
            if not document or not urlparse(url).netloc:
                continue
            for index, section in enumerate(re.split(r"\n\s*\n", document)):
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
        return float(sum(min(frequencies.get(word, 0), 5) for word in query_words))

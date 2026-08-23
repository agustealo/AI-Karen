"""
Text Processing Tool for AI-Karen
Advanced text processing, analysis, and manipulation.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter
import hashlib

from ai_karen_engine.services.tooling.tool_service import BaseTool, ToolMetadata, ToolCategory, ToolParameter

logger = logging.getLogger(__name__)


class TextProcessingTool(BaseTool):
    """
    Production-grade text processing tool.

    Features:
    - Text cleaning and normalization
    - Sentence and word tokenization
    - Text statistics and analysis
    - Pattern matching and extraction
    - Text transformation (case, formatting)
    - Similarity comparison
    - Language detection hints
    - Text summarization helpers
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.config = config or {}
        self.max_text_length = self.config.get('max_text_length', 1_000_000)

    def _create_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="text_processing",
            description="Process and analyze text (clean, tokenize, extract patterns, statistics)",
            category=ToolCategory.ANALYTICS,
            version="1.0.0",
            author="AI Karen",
            parameters=[
                ToolParameter(
                    name="operation",
                    type=str,
                    description="Operation to perform (clean, tokenize_words, tokenize_sentences, stats, extract_emails, extract_urls, similarity, hash)",
                    required=True
                ),
                ToolParameter(
                    name="text",
                    type=str,
                    description="Input text",
                    required=True
                ),
                ToolParameter(
                    name="text2",
                    type=str,
                    description="Second text (for similarity operation)",
                    required=False
                ),
                ToolParameter(
                    name="lowercase",
                    type=bool,
                    description="Convert to lowercase",
                    required=False,
                    default=False
                ),
                ToolParameter(
                    name="remove_punctuation",
                    type=bool,
                    description="Remove punctuation",
                    required=False,
                    default=False
                ),
                ToolParameter(
                    name="method",
                    type=str,
                    description="Method for operation (e.g., 'jaccard' for similarity)",
                    required=False
                )
            ],
            return_type=dict,
            examples=[
                {
                    "description": "Get text statistics",
                    "parameters": {
                        "operation": "stats",
                        "text": "This is a sample text for analysis."
                    }
                },
                {
                    "description": "Extract email addresses",
                    "parameters": {
                        "operation": "extract_emails",
                        "text": "Contact us at info@example.com or support@example.org"
                    }
                }
            ],
            tags=["text", "nlp", "processing", "analysis"],
            timeout=30
        )

    async def _execute(self, parameters: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Any:
        operation = parameters["operation"]
        text = parameters["text"]

        if operation == "clean":
            return await self.clean_text(
                text,
                remove_whitespace=True,
                remove_punctuation=parameters.get("remove_punctuation", False),
                lowercase=parameters.get("lowercase", False)
            )

        elif operation == "tokenize_words":
            return await self.tokenize_words(
                text,
                lowercase=parameters.get("lowercase", True),
                remove_punctuation=parameters.get("remove_punctuation", True)
            )

        elif operation == "tokenize_sentences":
            return await self.tokenize_sentences(text)

        elif operation == "stats":
            return await self.get_text_stats(text)

        elif operation == "extract_emails":
            return await self.extract_emails(text)

        elif operation == "extract_urls":
            return await self.extract_urls(text)

        elif operation == "extract_phones":
            return await self.extract_phone_numbers(text)

        elif operation == "similarity":
            text2 = parameters["text2"]
            method = parameters.get("method", "jaccard")
            return await self.calculate_similarity(text, text2, method=method)

        elif operation == "hash":
            algorithm = parameters.get("algorithm", "sha256")
            return await self.generate_text_hash(text, algorithm=algorithm)

        else:
            raise ValueError(f"Unknown operation: {operation}")

    async def clean_text(
        self,
        text: str,
        remove_whitespace: bool = True,
        remove_punctuation: bool = False,
        remove_numbers: bool = False,
        lowercase: bool = False
    ) -> str:
        if len(text) > self.max_text_length:
            raise ValueError(f"Text too long: {len(text)} (max: {self.max_text_length})")

        result = text

        if lowercase:
            result = result.lower()

        if remove_punctuation:
            result = re.sub(r'[^\w\s]', '', result)

        if remove_numbers:
            result = re.sub(r'\d+', '', result)

        if remove_whitespace:
            result = ' '.join(result.split())

        return result

    async def tokenize_sentences(self, text: str) -> List[str]:
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        return sentences

    async def tokenize_words(
        self,
        text: str,
        lowercase: bool = True,
        remove_punctuation: bool = True
    ) -> List[str]:
        if lowercase:
            text = text.lower()

        if remove_punctuation:
            text = re.sub(r'[^\w\s]', ' ', text)

        words = text.split()
        return [w for w in words if w]

    async def count_words(self, text: str) -> int:
        words = await self.tokenize_words(text)
        return len(words)

    async def count_sentences(self, text: str) -> int:
        sentences = await self.tokenize_sentences(text)
        return len(sentences)

    async def count_characters(self, text: str, include_spaces: bool = True) -> int:
        if include_spaces:
            return len(text)
        else:
            return len(text.replace(' ', ''))

    async def get_text_stats(self, text: str) -> Dict[str, Any]:
        words = await self.tokenize_words(text)
        sentences = await self.tokenize_sentences(text)

        char_count = len(text)
        char_count_no_spaces = len(text.replace(' ', ''))
        word_count = len(words)
        sentence_count = len(sentences)

        avg_word_length = char_count_no_spaces / word_count if word_count > 0 else 0
        avg_sentence_length = word_count / sentence_count if sentence_count > 0 else 0

        word_freq = Counter(words)
        most_common_words = word_freq.most_common(10)

        unique_words = len(set(words))
        lexical_diversity = unique_words / word_count if word_count > 0 else 0

        return {
            'character_count': char_count,
            'character_count_no_spaces': char_count_no_spaces,
            'word_count': word_count,
            'sentence_count': sentence_count,
            'average_word_length': round(avg_word_length, 2),
            'average_sentence_length': round(avg_sentence_length, 2),
            'unique_words': unique_words,
            'lexical_diversity': round(lexical_diversity, 2),
            'most_common_words': most_common_words
        }

    async def extract_patterns(
        self,
        text: str,
        pattern: str,
        case_sensitive: bool = True
    ) -> List[str]:
        flags = 0 if case_sensitive else re.IGNORECASE
        matches = re.findall(pattern, text, flags=flags)
        return matches

    async def extract_emails(self, text: str) -> List[str]:
        pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return await self.extract_patterns(text, pattern)

    async def extract_urls(self, text: str) -> List[str]:
        pattern = r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
        return await self.extract_patterns(text, pattern)

    async def extract_phone_numbers(self, text: str) -> List[str]:
        pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
        return await self.extract_patterns(text, pattern)

    async def replace_pattern(
        self,
        text: str,
        pattern: str,
        replacement: str,
        case_sensitive: bool = True
    ) -> str:
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.sub(pattern, replacement, text, flags=flags)

    async def truncate_text(
        self,
        text: str,
        max_length: int,
        suffix: str = '...'
    ) -> str:
        if len(text) <= max_length:
            return text

        return text[:max_length - len(suffix)] + suffix

    async def wrap_text(
        self,
        text: str,
        width: int = 80,
        break_long_words: bool = True
    ) -> List[str]:
        import textwrap
        wrapper = textwrap.TextWrapper(
            width=width,
            break_long_words=break_long_words,
            break_on_hyphens=True
        )
        return wrapper.wrap(text)

    async def calculate_similarity(
        self,
        text1: str,
        text2: str,
        method: str = 'jaccard'
    ) -> float:
        if method == 'jaccard':
            words1 = set(await self.tokenize_words(text1))
            words2 = set(await self.tokenize_words(text2))
            intersection = len(words1 & words2)
            union = len(words1 | words2)
            return intersection / union if union > 0 else 0.0

        elif method == 'cosine':
            words1 = await self.tokenize_words(text1)
            words2 = await self.tokenize_words(text2)
            freq1 = Counter(words1)
            freq2 = Counter(words2)

            all_words = set(words1 + words2)
            vec1 = [freq1.get(w, 0) for w in all_words]
            vec2 = [freq2.get(w, 0) for w in all_words]

            dot_product = sum(a * b for a, b in zip(vec1, vec2))
            magnitude1 = sum(a * a for a in vec1) ** 0.5
            magnitude2 = sum(b * b for b in vec2) ** 0.5

            if magnitude1 == 0 or magnitude2 == 0:
                return 0.0
            return dot_product / (magnitude1 * magnitude2)

        elif method == 'levenshtein':
            def levenshtein_distance(s1: str, s2: str) -> int:
                if len(s1) < len(s2):
                    return levenshtein_distance(s2, s1)
                if len(s2) == 0:
                    return len(s1)

                previous_row = range(len(s2) + 1)
                for i, c1 in enumerate(s1):
                    current_row = [i + 1]
                    for j, c2 in enumerate(s2):
                        insertions = previous_row[j + 1] + 1
                        deletions = current_row[j] + 1
                        substitutions = previous_row[j] + (c1 != c2)
                        current_row.append(min(insertions, deletions, substitutions))
                    previous_row = current_row

                return previous_row[-1]

            distance = levenshtein_distance(text1, text2)
            max_len = max(len(text1), len(text2))
            return 1.0 - (distance / max_len) if max_len > 0 else 1.0

        else:
            raise ValueError(f"Unknown similarity method: {method}")

    async def generate_text_hash(
        self,
        text: str,
        algorithm: str = 'sha256'
    ) -> str:
        if algorithm == 'md5':
            hasher = hashlib.md5()
        elif algorithm == 'sha1':
            hasher = hashlib.sha1()
        elif algorithm == 'sha256':
            hasher = hashlib.sha256()
        elif algorithm == 'sha512':
            hasher = hashlib.sha512()
        else:
            raise ValueError(f"Unknown hash algorithm: {algorithm}")

        hasher.update(text.encode('utf-8'))
        return hasher.hexdigest()

    async def format_text(
        self,
        text: str,
        format_type: str = 'title'
    ) -> str:
        if format_type == 'title':
            return text.title()
        elif format_type == 'sentence':
            return text.capitalize()
        elif format_type == 'upper':
            return text.upper()
        elif format_type == 'lower':
            return text.lower()
        elif format_type == 'capitalize':
            return text.capitalize()
        else:
            raise ValueError(f"Unknown format type: {format_type}")

    async def remove_duplicates(
        self,
        texts: List[str],
        case_sensitive: bool = False
    ) -> List[str]:
        seen = set()
        result = []

        for text in texts:
            compare_text = text if case_sensitive else text.lower()
            if compare_text not in seen:
                seen.add(compare_text)
                result.append(text)

        return result


_text_processing_tool_instance = None


def get_text_processing_tool(
    config: Optional[Dict[str, Any]] = None
) -> TextProcessingTool:
    global _text_processing_tool_instance
    if _text_processing_tool_instance is None:
        _text_processing_tool_instance = TextProcessingTool(config)
    return _text_processing_tool_instance

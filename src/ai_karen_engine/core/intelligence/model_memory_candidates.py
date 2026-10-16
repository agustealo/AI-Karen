"""Typed, evidence-bound REVIEW ONLY output from a model memory extraction.

This module is the trust boundary between an untrusted model's JSON and
Karen's canonical SemanticAssertion. A validated model candidate is never
a MemorySignal, an admitted fact, or a persistence authorization.

Model routing and prompt assembly remain owned by the existing runtime.
Formation/privacy/consent and NeuroVault are deliberately not called here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ai_karen_engine.core.memory.semantic_contract import (
    AssertionModality,
    FactCardinality,
    SemanticAssertion,
    SemanticConfidence,
    SemanticObject,
    SemanticPredicate,
    SemanticProvenance,
    SemanticQualifiers,
    SemanticSubject,
    SemanticTemporality,
    SubjectKind,
)
from ai_karen_engine.core.intelligence.personal_relation import (
    personal_relation_attribute,
)
from ai_karen_engine.core.memory.signals.semantic_classifier import (
    classify_explicit_user_memory,
)

PROMPT_ID = "karen.memory.semantic_candidates"
PROMPT_VERSION = "v1.0.0"
MAX_SOURCE_LENGTH = 2000
MAX_MODEL_OUTPUT_LENGTH = 8192
MAX_CANDIDATES = 3

_SELF_CUE = re.compile(r"\b(?:i|i'm|i've|my|mine)\b", re.IGNORECASE)
_UNTRUSTED_ATTRIBUTION = re.compile(
    r"\b(?:according to|someone said|she said|he said|they said|"
    r"my friend said|my partner said|my boss said|quoted|quote:)\b",
    re.IGNORECASE,
)
_NONASSERTIONS = re.compile(
    r"\b(?:maybe|perhaps|possibly|hypothetically|if i|suppose|"
    r"i might|i could|i used to|i do not|i don't|i never|"
    r"for now|this week|temporarily|until\b|last year|"
    r"right now|currently|today\b|tonight\b|"
    r"while i\b|this morning|no longer|not anymore)\b",
    re.IGNORECASE,
)
_RELATION_ALLOWED = re.compile(r"^[a-z][a-z0-9 /-]{0,79}$", re.IGNORECASE)
_DIRECT_USER_CLAUSE = re.compile(
    r"^(?:i|my)\b|^(?:during|at|in)\s+[^,!?]{1,75},\s*(?:i|my)\b",
    re.IGNORECASE,
)
_CANONICAL_VALUE_LIMIT = 120
_ALLOWED_FIELDS = frozenset({
    "evidence_text", "span_start", "span_end", "relation", "value"
})


@dataclass(frozen=True, slots=True)
class ModelMemoryCandidate:
    """Grounded evidence pending further independent formation adjudication."""

    assertion: SemanticAssertion
    review_state: str = "untrusted_model_candidate"


@dataclass(frozen=True, slots=True)
class ModelCandidateReview:
    """Non-persisting validation result with safe, enumerated rejection reasons."""

    candidates: tuple[ModelMemoryCandidate, ...]
    rejected: tuple[str, ...]
    prompt_id: str
    prompt_version: str

    @property
    def eligible_for_auto_persistence(self) -> bool:
        # Explicit invariant: the model channel NEVER authorizes a memory.
        return False


def _parse_envelope(raw: str) -> list[dict[str, Any]] | None:
    if not isinstance(raw, str) or len(raw) > MAX_MODEL_OUTPUT_LENGTH:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"candidates"}:
        return None
    items = payload["candidates"]
    if (
        not isinstance(items, list)
        or len(items) > MAX_CANDIDATES
        or any(not isinstance(item, dict) for item in items)
    ):
        return None
    return items


def _verified_span(
    candidate: dict[str, Any], source: str,
) -> tuple[str, str, str, int, int] | None:
    if set(candidate) != _ALLOWED_FIELDS:
        return None
    quote = candidate["evidence_text"]
    relation = candidate["relation"]
    value = candidate["value"]
    start = candidate["span_start"]
    end = candidate["span_end"]
    if (
        not isinstance(quote, str) or not isinstance(relation, str)
        or not isinstance(value, str)
        or type(start) is not int or type(end) is not int
        or not 0 <= start < end <= len(source)
        or not 8 <= len(quote) <= 400
        or len(value) > _CANONICAL_VALUE_LIMIT
        or not value.strip() or not _RELATION_ALLOWED.fullmatch(relation)
    ):
        return None
    if source[start:end] != quote:
        return None
    # Only direct affirmative first-person claims are in scope for this phase.
    # A source quote is evidence, not authorization to infer hidden context.
    if (
        not _SELF_CUE.search(quote)
        or any(char in quote for char in ('"', "'", "\n", "\r", "\u201c", "\u201d"))
        or _UNTRUSTED_ATTRIBUTION.search(quote)
        or _NONASSERTIONS.search(quote)
        or value.casefold() not in quote.casefold()
        or relation.casefold() not in quote.casefold()
        or any(char in source for char in ("?", "\u00bf"))
        or (
            # Relation/value overlap can fabricate an object that is only
            # a word inside the predicate, not a separately stated value.
            value.casefold() in relation.casefold()
            or quote.casefold().find(value.casefold())
            <= quote.casefold().find(relation.casefold())
        )
    ):
        return None
    identity = personal_relation_attribute(relation)
    if identity is None:
        return None
    # Canonical deterministic facts retain their original owner. A model
    # must not mint parallel identities for known birth/name/favorite facts.
    if any(
        signal.metadata.get("explicit_user_statement") is True
        and signal.signal_type in {"identity_fact", "profile_fact", "preference"}
        for signal in classify_explicit_user_memory(quote)
    ):
        return None
    return quote, relation.casefold(), value.strip(), start, end


def review_model_memory_candidates(
    *,
    raw_output: str,
    source_text: str,
    tenant_id: str,
    user_id: str,
    source_event_id: str,
    source_message_id: str,
    observed_at: datetime,
    prompt_id: str,
    prompt_version: str,
) -> ModelCandidateReview:
    """Validate untrusted JSON against runtime-supplied source and provenance.

    All source IDs are supplied by the authenticated runtime, never read from
    model JSON. Validity is evidence-binding only, *not* user fact truth.
    """
    if (
        not isinstance(prompt_id, str) or prompt_id != PROMPT_ID
        or not isinstance(prompt_version, str)
        or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", prompt_version)
    ):
        return ModelCandidateReview(
            (), ("invalid_prompt_provenance",),
            str(prompt_id), str(prompt_version),
        )
    if (
        not isinstance(source_text, str)
        or not 1 <= len(source_text) <= MAX_SOURCE_LENGTH
        or any(not isinstance(value, str) or not value.strip()
               for value in (tenant_id, user_id, source_event_id, source_message_id))
    ):
        return ModelCandidateReview((), ("invalid_source_context",), prompt_id, prompt_version)
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        return ModelCandidateReview((), ("invalid_observation_time",), prompt_id, prompt_version)
    # A clipped quote cannot upgrade third-party, hypothetical or negated
    # context into a direct autobiographical statement.
    if (
        any(char in source_text for char in ('"', "'", "\u2018", "\u2019", "\u201c", "\u201d"))
        or not _DIRECT_USER_CLAUSE.match(source_text.strip())
        or _UNTRUSTED_ATTRIBUTION.search(source_text)
        or _NONASSERTIONS.search(source_text)
    ):
        return ModelCandidateReview((), ("source_context_not_direct_assertion",), prompt_id, prompt_version)
    items = _parse_envelope(raw_output)
    if items is None:
        return ModelCandidateReview((), ("invalid_model_envelope",), prompt_id, prompt_version)

    accepted: list[ModelMemoryCandidate] = []
    rejected: list[str] = []
    seen: set[tuple[str, str, int, int]] = set()

    for item in items:
        span = _verified_span(item, source_text)
        if span is None:
            rejected.append("source_span_or_semantics_unverified")
            continue
        quote, relation, value, start, end = span
        identity = (relation, value.casefold(), start, end)
        if identity in seen:
            rejected.append("duplicate_candidate")
            continue
        seen.add(identity)
        try:
            assertion = SemanticAssertion(
                tenant_id=tenant_id,
                user_id=user_id,
                subject=SemanticSubject(kind=SubjectKind.SELF, entity_id=user_id),
                predicate=SemanticPredicate(
                    namespace="personal_relation",
                    relation=personal_relation_attribute(relation).removeprefix(
                        "personal_relation."
                    ),
                ),
                object=SemanticObject(type="text", canonical_value=value),
                qualifiers=SemanticQualifiers(),
                temporality=SemanticTemporality(observed_at=observed_at),
                modality=AssertionModality.ASSERTED,
                # This is unverified model interpretation, not belief confidence.
                confidence=SemanticConfidence(
                    extraction=0.5, assertion=0.5, source_trust=0.0,
                ),
                cardinality=FactCardinality.SINGLETON,
                provenance=SemanticProvenance(
                    source_event_id=source_event_id,
                    source_message_id=source_message_id,
                    source_origin="authenticated_user_message",
                    speaker="user",
                    evidence_text=quote,
                    evidence_span_start=start,
                    evidence_span_end=end,
                    extractor="model_semantic_candidate",
                    extractor_version="v1.0.0",
                    prompt_contract_version=PROMPT_VERSION,
                ),
            )
        except ValueError:
            rejected.append("semantic_contract_invalid")
            continue
        accepted.append(ModelMemoryCandidate(assertion=assertion))

    return ModelCandidateReview(tuple(accepted), tuple(rejected))


__all__ = [
    "MAX_CANDIDATES", "ModelMemoryCandidate", "ModelCandidateReview",
    "PROMPT_ID", "PROMPT_VERSION", "review_model_memory_candidates",
]

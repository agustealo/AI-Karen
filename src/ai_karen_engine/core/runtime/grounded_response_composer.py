"""Evidence-preserving presentation for independently authorized profile facts.

This module never retrieves memory, decides policy, or invokes a model.
Only the canonical runtime supplies facts after sufficiency authorization.
"""
from __future__ import annotations

from collections.abc import Mapping


def compose_identity_summary(facts: Mapping[str, str]) -> str:
    """Render authorized attributes without inferring missing neighbors.

    Birthplace and origin stay separate memory attributes. When their
    normalized values match, saying "born in" covers the location once.
    """
    values = {
        key: str(value).strip()
        for key, value in facts.items()
        if value is not None and str(value).strip()
    }
    clauses: list[str] = []
    name = values.get("preferred_name")
    if name:
        clauses.append(f"You're {name}")

    birthplace = values.get("birthplace")
    origin = values.get("origin_location")
    if birthplace:
        clauses.append(f"you were born in {birthplace}")
    if origin and (not birthplace or birthplace.casefold() != origin.casefold()):
        clauses.append(f"you're from {origin}")

    upbringing = values.get("upbringing_location")
    if upbringing:
        clauses.append(f"you grew up in {upbringing}")
    residence = values.get("residence_location")
    if residence:
        clauses.append(f"you live in {residence}")
    work = values.get("work_location")
    if work:
        clauses.append(f"you work in {work}")

    if not clauses:
        return "I don't have enough verified information saved to describe who you are."
    if len(clauses) == 1:
        return clauses[0] + "."
    return clauses[0] + ". " + ". ".join(
        clause[:1].upper() + clause[1:] for clause in clauses[1:]
    ) + "."

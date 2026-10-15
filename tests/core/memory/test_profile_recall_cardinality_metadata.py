"""Profile recall preserves declared cardinality without granting authority."""

from types import SimpleNamespace
from datetime import datetime
from uuid import uuid4

from ai_karen_engine.platform.memory.postgres.profile_retriever import (
    PostgresProfileRecallRetriever,
)


def row(value):
    return SimpleNamespace(
        fact_id=uuid4(),
        event_id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        attribute="favorite_artist",
        category="preference",
        value=value,
        confidence=0.9,
        source_type="chat_user",
        source_ref="conversation",
        valid_from=None,
        valid_to=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def query():
    return SimpleNamespace(conversation_id="c1", session_id="s1")


def test_set_annotation_and_scope_survive_retrieval():
    item = PostgresProfileRecallRetriever._entry(
        row({"value": "Bob Marley", "cardinality": "set",
             "domain": "music", "facet": "reggae", "project_id": "playlist"}),
        query(),
    )
    assert item.metadata.custom["cardinality"] == "set"
    assert item.metadata.custom["semantic_scope"] == {
        "domain": "music", "facet": "reggae", "project_id": "playlist",
    }
    assert item.content == "favorite_artist: Bob Marley"


def test_legacy_profile_value_is_explicitly_singleton():
    item = PostgresProfileRecallRetriever._entry(
        row({"value": "black"}), query()
    )
    assert item.metadata.custom["cardinality"] == "singleton"
    assert item.metadata.custom["semantic_scope"] == {}


def test_plain_legacy_row_remains_compatible():
    item = PostgresProfileRecallRetriever._entry(row("black"), query())
    assert item.metadata.custom["cardinality"] == "singleton"
    assert item.content == "favorite_artist: black"

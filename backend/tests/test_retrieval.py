from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services import retrieval


class FakeEmbedding:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class FakeModel:
    def __init__(self, values):
        self.values = values
        self.queries = []

    def encode(self, query):
        self.queries.append(query)
        return FakeEmbedding(self.values)


def row(*, similarity, chunk_index=0):
    return SimpleNamespace(
        _mapping={
            "id": uuid4(),
            "episode_id": "ada-chen-rekhi",
            "episode_title": "Ada Chen-Rekhi",
            "source_url": "https://example.test/transcript.md",
            "chunk_index": chunk_index,
            "content": f"Chunk {chunk_index}",
            "similarity": similarity,
        }
    )


def test_retrieve_orders_results_and_preserves_source_metadata(monkeypatch):
    model = FakeModel([0.1] * 384)
    monkeypatch.setattr(retrieval, "get_embedding_model", lambda: model)
    monkeypatch.setattr(retrieval.settings, "retrieval_min_similarity", 0.25)
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [
        row(similarity=0.95, chunk_index=4),
        row(similarity=0.72, chunk_index=2),
    ]

    results = retrieval.retrieve(db, "How do I find product-market fit?", top_k=2)

    assert model.queries == ["How do I find product-market fit?"]
    assert [result.similarity for result in results] == [0.95, 0.72]
    assert results[0].chunk_index == 4
    assert results[0].episode_title == "Ada Chen-Rekhi"
    assert results[0].source_url == "https://example.test/transcript.md"
    params = db.execute.call_args.args[1]
    assert params["top_k"] == 2
    assert len(params["query_embedding"].strip("[]").split(",")) == 384


def test_retrieve_applies_similarity_threshold(monkeypatch):
    monkeypatch.setattr(retrieval, "get_embedding_model", lambda: FakeModel([0.1] * 384))
    monkeypatch.setattr(retrieval.settings, "retrieval_min_similarity", 0.8)
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = [
        row(similarity=0.79),
        row(similarity=0.81),
    ]

    results = retrieval.retrieve(db, "pricing strategy")

    assert [result.similarity for result in results] == [0.81]


def test_retrieve_returns_empty_for_blank_query_without_dependencies(monkeypatch):
    model = MagicMock()
    monkeypatch.setattr(retrieval, "get_embedding_model", lambda: model)
    db = MagicMock()

    assert retrieval.retrieve(db, "   ") == []
    model.encode.assert_not_called()
    db.execute.assert_not_called()


def test_retrieve_wraps_database_failure(monkeypatch):
    monkeypatch.setattr(retrieval, "get_embedding_model", lambda: FakeModel([0.1] * 384))
    db = MagicMock()
    db.execute.side_effect = RuntimeError("database offline")

    with pytest.raises(retrieval.RetrievalUnavailableError, match="retrieval is unavailable"):
        retrieval.retrieve(db, "growth loops")
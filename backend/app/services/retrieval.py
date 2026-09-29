"""Retrieval over transcript_chunks using pgvector cosine similarity.

Uses the same local embedding model as ingest.py so query and document
vectors live in the same space.
"""

import logging
from dataclasses import dataclass
from typing import Any

from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.config import get_settings

log = logging.getLogger("retrieval")
settings = get_settings()

_embedding_model: SentenceTransformer | None = None
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384


class RetrievalUnavailableError(Exception):
    """Raised when transcript retrieval cannot be completed."""


def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: Any
    episode_id: str
    episode_title: str | None
    source_url: str | None
    chunk_index: int
    content: str
    similarity: float


def retrieve(db: DBSession, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    """Embed the query, run a cosine-similarity search, and filter by the
    minimum-similarity threshold. Returns an empty list if nothing clears the
    bar — callers use this to trigger the 'insufficient evidence' response."""
    normalized_query = query.strip()
    if not normalized_query:
        return []

    requested_top_k = settings.retrieval_top_k if top_k is None else top_k
    if requested_top_k <= 0:
        return []

    try:
        model = get_embedding_model()
        query_embedding = model.encode(normalized_query)
        query_embedding = query_embedding.tolist()
        if len(query_embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Expected {EMBEDDING_DIMENSIONS}-dimensional query embedding, "
                f"got {len(query_embedding)}"
            )
    except Exception as exc:  # noqa: BLE001 - normalize model failures for the API
        log.exception("Query embedding failed")
        raise RetrievalUnavailableError("Transcript query embedding is unavailable.") from exc

    try:
        rows = db.execute(
            text(
                """
                SELECT id, episode_id, episode_title, source_url, chunk_index, content,
                       1 - (embedding <=> CAST(:query_embedding AS vector)) AS similarity
                FROM transcript_chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT :top_k
                """
            ),
            {"query_embedding": str(query_embedding), "top_k": requested_top_k},
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 - normalize database failures for the API
        log.exception("Transcript retrieval query failed")
        raise RetrievalUnavailableError("Transcript retrieval is unavailable.") from exc

    results = []
    for row in rows:
        try:
            mapping = row._mapping
            similarity = float(mapping["similarity"])
            if similarity < settings.retrieval_min_similarity:
                continue
            results.append(
                RetrievedChunk(
                    chunk_id=mapping["id"],
                    episode_id=str(mapping["episode_id"]),
                    episode_title=mapping["episode_title"],
                    source_url=mapping["source_url"],
                    chunk_index=int(mapping["chunk_index"]),
                    content=str(mapping["content"]),
                    similarity=similarity,
                )
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed transcript retrieval row: %s", exc)

    log.info("Retrieved %d/%d chunks above similarity threshold for query", len(results), len(rows))
    return results

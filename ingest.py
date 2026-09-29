"""
Ingestion script for The Lenny Growth Assistant.

Clones/updates the Lenny's Podcast transcript repository, chunks each
transcript into retrieval-sized pieces, embeds them locally, and upserts
them into Postgres (pgvector) as defined in architecture.md.

Repo structure this script targets (ChatPRD/lennys-podcast-transcripts):

    episodes/
        {guest-name}/
            transcript.md      # YAML frontmatter (guest, title, ...) + body
    index/
        README.md, product-management.md, ...   # topic indexes (not ingested directly)

Usage:
    python ingest.py --repo-dir ./data/lennys-podcast-transcripts --limit 50
    python ingest.py --repo-dir ./data/lennys-podcast-transcripts   # full corpus

Re-running is safe: each episode is replaced transactionally and chunks are keyed
by (episode_id, chunk_index), so no duplicates or stale shortened-transcript chunks accumulate.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg2
import psycopg2.extras
import yaml
from sentence_transformers import SentenceTransformer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s ingest %(message)s",
)
log = logging.getLogger("ingest")

REPO_URL = "https://github.com/ChatPRD/lennys-podcast-transcripts.git"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim, small & local — matches architecture.md schema
CHUNK_TARGET_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 50


@dataclass
class Chunk:
    episode_id: str
    episode_title: str
    source_url: str
    chunk_index: int
    content: str


def clone_or_update_repo(repo_dir: Path) -> None:
    """Clone the transcript repo if missing, otherwise pull its Git checkout."""
    if repo_dir.exists():
        if not (repo_dir / ".git").exists():
            raise RuntimeError(
                f"{repo_dir} exists but is not a Git checkout; remove it or pass --skip-clone "
                "when using a manually prepared transcript directory."
            )
        log.info("Repo already present at %s — pulling latest", repo_dir)
        subprocess.run(["git", "-C", str(repo_dir), "pull", "--ff-only"], check=True)
    else:
        log.info("Cloning %s into %s", REPO_URL, repo_dir)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(repo_dir)], check=True)


def parse_transcript_file(path: Path) -> tuple[dict, str]:
    """Split YAML frontmatter from transcript body. Falls back gracefully
    if a file has no frontmatter (treat whole file as body)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    parts = raw.split("---")
    if len(parts) >= 3 and parts[0].strip() == "":
        try:
            frontmatter = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            log.warning("Could not parse frontmatter in %s — using filename as title", path)
            frontmatter = {}
        body = "---".join(parts[2:]).strip()
        return frontmatter, body
    return {}, raw.strip()


def chunk_text(text: str, target_tokens: int = CHUNK_TARGET_TOKENS, overlap_tokens: int = CHUNK_OVERLAP_TOKENS) -> list[str]:
    """Chunk on paragraph boundaries, packing paragraphs up to ~target_tokens
    (approximated as whitespace-separated words) with a small overlap between
    consecutive chunks so context isn't lost at a boundary."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def word_count(s: str) -> int:
        return len(s.split())

    for para in paragraphs:
        para_len = word_count(para)
        if current and current_len + para_len > target_tokens:
            chunks.append(" ".join(current))
            # carry the tail of the previous chunk forward for overlap
            overlap_words = " ".join(current).split()[-overlap_tokens:]
            current = [" ".join(overlap_words)] if overlap_words else []
            current_len = len(overlap_words)
        current.append(para)
        current_len += para_len

    if current:
        chunks.append(" ".join(current))

    return [c for c in chunks if c.strip()]


def build_chunks_for_episode(transcript_path: Path, repo_root: Path) -> list[Chunk]:
    frontmatter, body = parse_transcript_file(transcript_path)
    guest_dir = transcript_path.parent.name
    episode_id = frontmatter.get("guest", guest_dir) or guest_dir
    episode_title = frontmatter.get("title", guest_dir.replace("-", " ").title())
    rel_path = transcript_path.relative_to(repo_root)
    source_url = f"{REPO_URL.removesuffix('.git')}/blob/main/{rel_path.as_posix()}"

    if not body:
        log.warning("Empty transcript body for %s — skipping", transcript_path)
        return []

    text_chunks = chunk_text(body)
    return [
        Chunk(
            episode_id=stable_episode_id(guest_dir),
            episode_title=episode_title,
            source_url=source_url,
            chunk_index=i,
            content=chunk,
        )
        for i, chunk in enumerate(text_chunks)
    ]


def stable_episode_id(guest_dir: str) -> str:
    """Deterministic, filesystem-independent id for the (episode_id, chunk_index)
    upsert key, so re-running ingestion never creates duplicate rows."""
    return guest_dir


def get_db_connection():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        log.error("DATABASE_URL is not set — see .env.example")
        sys.exit(1)
    return psycopg2.connect(dsn)


def ensure_schema(conn) -> None:
    """Idempotent: creates the extension/table/index if not already present.
    Full schema also lives in architecture.md / migrations — this is a safety net
    so the script is runnable standalone."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transcript_chunks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                episode_id TEXT NOT NULL,
                episode_title TEXT,
                source_url TEXT,
                chunk_index INT NOT NULL,
                content TEXT NOT NULL,
                embedding VECTOR(384),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (episode_id, chunk_index)
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunks_embedding
            ON transcript_chunks USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
            """
        )
    conn.commit()


def replace_episode_chunks(conn, episode_id: str, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    """Replace one episode atomically so shortened transcripts do not leave stale chunks."""
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM transcript_chunks WHERE episode_id = %s", (episode_id,))
        upsert_chunks(conn, chunks, embeddings)


def upsert_chunks(conn, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    rows = [
        (
            str(uuid.uuid4()),
            c.episode_id,
            c.episode_title,
            c.source_url,
            c.chunk_index,
            c.content,
            embeddings[i],
        )
        for i, c in enumerate(chunks)
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO transcript_chunks
                (id, episode_id, episode_title, source_url, chunk_index, content, embedding)
            VALUES %s
            ON CONFLICT (episode_id, chunk_index)
            DO UPDATE SET
                episode_title = EXCLUDED.episode_title,
                source_url    = EXCLUDED.source_url,
                content       = EXCLUDED.content,
                embedding     = EXCLUDED.embedding,
                created_at    = now();
            """,
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s)",
        )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", type=Path, default=Path("./data/lennys-podcast-transcripts"))
    parser.add_argument("--limit", type=int, default=None, help="Ingest only the first N episodes (for demo/dev runs).")
    parser.add_argument("--skip-clone", action="store_true", help="Use an already-present local copy of the repo.")
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size.")
    args = parser.parse_args()

    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be zero or greater")
    if args.batch_size < 1:
        parser.error("--batch-size must be greater than zero")

    if not args.skip_clone:
        clone_or_update_repo(args.repo_dir)

    episodes_dir = args.repo_dir / "episodes"
    if not episodes_dir.exists():
        log.error("Expected episodes/ directory not found at %s", episodes_dir)
        sys.exit(1)

    transcript_paths = sorted(episodes_dir.glob("*/transcript.md"))
    if args.limit is not None:
        transcript_paths = transcript_paths[: args.limit]
    log.info("Found %d transcript files to process", len(transcript_paths))

    log.info("Loading embedding model %s (local, no API key needed)", EMBEDDING_MODEL_NAME)
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    conn = get_db_connection()
    ensure_schema(conn)

    total_chunks = 0
    for i, transcript_path in enumerate(transcript_paths, start=1):
        chunks = build_chunks_for_episode(transcript_path, args.repo_dir)
        if not chunks:
            continue

        texts = [c.content for c in chunks]
        embeddings = model.encode(
            texts, batch_size=args.batch_size, show_progress_bar=False
        ).tolist()

        replace_episode_chunks(conn, chunks[0].episode_id, chunks, embeddings)
        total_chunks += len(chunks)
        log.info(
            "[%d/%d] %s — %d chunks upserted (running total: %d)",
            i, len(transcript_paths), chunks[0].episode_id, len(chunks), total_chunks,
        )

    conn.close()
    log.info("Done. Ingested %d chunks from %d episodes.", total_chunks, len(transcript_paths))


if __name__ == "__main__":
    main()

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parents[1]))

from ingest import Chunk, upsert_chunks


def test_upsert_chunks_supplies_uuid_and_preserves_conflict_key():
    conn = MagicMock()
    chunks = [
        Chunk(
            episode_id="ada-chen-rekhi",
            episode_title="Ada Chen-Rekhi",
            source_url="https://example.test/transcript.md",
            chunk_index=0,
            content="A transcript chunk.",
        )
    ]

    with patch("ingest.psycopg2.extras.execute_values") as execute_values:
        upsert_chunks(conn, chunks, [[0.1] * 384])

    _, query, rows = execute_values.call_args.args
    template = execute_values.call_args.kwargs["template"]
    assert len(rows[0]) == 7
    assert isinstance(rows[0][0], str)
    UUID(rows[0][0])
    assert rows[0][1:] == (
        "ada-chen-rekhi",
        "Ada Chen-Rekhi",
        "https://example.test/transcript.md",
        0,
        "A transcript chunk.",
        [0.1] * 384,
    )
    assert "(id, episode_id, episode_title, source_url, chunk_index, content, embedding)" in query
    assert template == "(%s, %s, %s, %s, %s, %s, %s)"
    assert "ON CONFLICT (episode_id, chunk_index)" in query
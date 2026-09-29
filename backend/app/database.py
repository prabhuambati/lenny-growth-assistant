"""Database engine/session setup (SQLAlchemy, sync engine — simplest for a
take-home scope; swap to async engine + asyncpg if throughput ever matters)."""

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

log = logging.getLogger("database")

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Enable pgvector and create architecture.md tables if they do not exist.

    Safe to call on every startup. Does not crash the process if Postgres is
    unreachable — /health reports that as degraded instead.
    """
    # Register ORM tables on Base.metadata before create_all.
    from app.models import db_models  # noqa: F401

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_messages_session "
                    "ON messages (session_id, created_at)"
                )
            )
            # ivfflat needs enough rows to be useful; skip quietly on empty DBs.
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON transcript_chunks "
                        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
                    )
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("pgvector ivfflat index not created yet: %s", exc)
        log.info("Database schema initialized")
    except Exception as exc:  # noqa: BLE001
        log.error("Database schema initialization failed: %s", exc)

import asyncio
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.config import get_settings
from app.database import get_db
from app.models.schemas import HealthResponse, ok
from app.services.llm_client import OllamaClient

log = logging.getLogger("health")
router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: DBSession = Depends(get_db)):
    settings = get_settings()

    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        log.error("DB health check failed: %s", exc)
        db_ok = False

    ollama = OllamaClient(settings.ollama_host, settings.ollama_model)
    try:
        ollama_ok = await asyncio.wait_for(ollama.is_reachable(), timeout=1.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("Ollama health check failed or timed out: %s", exc)
        ollama_ok = False

    status = "ok" if (db_ok and ollama_ok) else "degraded"
    payload = HealthResponse(
        status=status,
        database=db_ok,
        ollama=ollama_ok,
        active_provider=settings.model_provider,
    )
    return ok(payload.model_dump())

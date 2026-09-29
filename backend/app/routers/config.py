import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.models.schemas import ModelConfigResponse, SetModelConfigRequest, err, ok
from app.services.llm_client import build_client

log = logging.getLogger("config")
router = APIRouter(prefix="/config", tags=["config"])

_AVAILABLE = ["ollama", "anthropic", "openai", "gemini"]


@router.get("/model")
def get_model_config():
    settings = get_settings()
    payload = ModelConfigResponse(
        active_provider=settings.model_provider,
        available_providers=_AVAILABLE,
    )
    return ok(payload.model_dump())


@router.put("/model")
async def set_model_config(body: SetModelConfigRequest):
    settings = get_settings()
    client = build_client(body.provider, settings)

    if not await client.is_reachable():
        return JSONResponse(
            status_code=422,
            content=err(
                "PROVIDER_UNAVAILABLE",
                f"{body.provider} is not reachable/configured — check credentials or that Ollama is running.",
            ),
        )

    settings.model_provider = body.provider  # NOTE: process-lifetime only; persist via MODEL_PROVIDER env
    payload = ModelConfigResponse(
        active_provider=settings.model_provider,
        available_providers=_AVAILABLE,
    )
    return ok(payload.model_dump())

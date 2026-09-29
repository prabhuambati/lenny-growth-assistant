"""Centralized configuration. All values come from environment variables so
the deployment (Docker Compose / .env) fully controls behavior with no code
changes — see .env.example for the full list and safe defaults."""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/lenny_assistant"
    )

    model_provider: str = os.environ.get("MODEL_PROVIDER", "ollama")  # ollama | anthropic | openai | gemini

    ollama_host: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY") or None
    anthropic_model: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY") or None
    openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY") or None
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    retrieval_top_k: int = int(os.environ.get("RETRIEVAL_TOP_K", "5"))
    retrieval_min_similarity: float = float(os.environ.get("RETRIEVAL_MIN_SIMILARITY", "0.25"))
    ship30_generation_timeout_seconds: float = float(
        os.environ.get("SHIP30_GENERATION_TIMEOUT_SECONDS", "600")
    )
    normal_chat_generation_timeout_seconds: float = float(
        os.environ.get("NORMAL_CHAT_GENERATION_TIMEOUT_SECONDS", "300")
    )

    cors_origins: list[str] = [
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    ]

    log_level: str = os.environ.get("LOG_LEVEL", "INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()

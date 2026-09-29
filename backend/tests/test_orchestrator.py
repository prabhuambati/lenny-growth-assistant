from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agent import orchestrator
from app.agent.skills.ship30 import Ship30Result, Ship30Validation, Ship30Citation
from app.config import Settings


@pytest.mark.asyncio
async def test_chat_turn_sends_retrieved_context_and_citations():
    chunk = SimpleNamespace(
        chunk_id=uuid4(),
        episode_id="ada-chen-rekhi",
        episode_title="Ada Chen-Rekhi",
        source_url="https://example.test/transcript.md",
        content="A grounded transcript excerpt.",
    )
    generated = AsyncMock(return_value=("Grounded answer", "ollama"))

    with patch.object(orchestrator.retrieval, "retrieve", return_value=[chunk]), patch.object(
        orchestrator, "generate_with_fallback", generated
    ):
        answer, citations, provider = await orchestrator.handle_chat_turn(
            MagicMock(), uuid4(), [], "What did Ada recommend?", "ollama", Settings()
        )

    assert answer == "Grounded answer"
    assert provider == "ollama"
    assert citations[0]["episode_title"] == "Ada Chen-Rekhi"
    assert citations[0]["source_url"] == "https://example.test/transcript.md"
    system_message = generated.call_args.args[1][0]
    assert "A grounded transcript excerpt." in system_message["content"]
    assert "https://example.test/transcript.md" in system_message["content"]


@pytest.mark.asyncio
async def test_normal_chat_limits_retrieval_and_context_size():
    chunk = SimpleNamespace(
        chunk_id=uuid4(),
        episode_id="pricing-episode",
        episode_title="Pricing episode",
        source_url="https://example.test/pricing.md",
        content="x" * (orchestrator.NORMAL_CHAT_CHUNK_MAX_CHARS + 500),
    )
    generated = AsyncMock(return_value=("Grounded answer", "ollama"))

    with patch.object(orchestrator.retrieval, "retrieve", return_value=[chunk]) as retrieve, patch.object(
        orchestrator, "generate_with_fallback", generated
    ):
        await orchestrator.handle_chat_turn(
            MagicMock(), uuid4(), [], "What is a pricing lesson?", "ollama", Settings()
        )

    assert retrieve.call_args.kwargs["top_k"] == 3
    system_content = generated.call_args.args[1][0]["content"]
    assert "[Pricing episode] (source: https://example.test/pricing.md)" in system_content
    assert "x" * (orchestrator.NORMAL_CHAT_CHUNK_MAX_CHARS + 1) not in system_content


@pytest.mark.asyncio
async def test_chat_turn_does_not_call_llm_without_evidence():
    generated = AsyncMock()

    with patch.object(orchestrator.retrieval, "retrieve", return_value=[]), patch.object(
        orchestrator, "generate_with_fallback", generated
    ):
        answer, citations, _ = await orchestrator.handle_chat_turn(
            MagicMock(), uuid4(), [], "An unrelated question", "ollama", Settings()
        )

    assert answer == orchestrator.INSUFFICIENT_EVIDENCE_REPLY
    assert citations == []
    generated.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_turn_omits_citations_for_insufficient_grounded_answer():
    chunk = SimpleNamespace(
        chunk_id=uuid4(),
        episode_id="pricing-episode",
        episode_title="Pricing episode",
        source_url="https://example.test/pricing.md",
        content="A semantically related pricing excerpt.",
    )
    generated = AsyncMock(return_value=(orchestrator.INSUFFICIENT_EVIDENCE_REPLY, "ollama"))

    with patch.object(orchestrator.retrieval, "retrieve", return_value=[chunk]), patch.object(
        orchestrator, "generate_with_fallback", generated
    ):
        answer, citations, provider = await orchestrator.handle_chat_turn(
            MagicMock(), uuid4(), [], "How should a startup think about pricing?", "ollama", Settings()
        )

    assert answer == orchestrator.INSUFFICIENT_EVIDENCE_REPLY
    assert citations == []
    assert provider == "ollama"


@pytest.mark.asyncio
async def test_ship30_chat_normalizes_writing_request_and_returns_citations():
    chunk = SimpleNamespace(
        chunk_id=uuid4(),
        episode_id="pricing-episode",
        episode_title="Pricing episode",
        source_url="https://example.test/pricing.md",
        content="Pricing transcript evidence.",
    )
    result = Ship30Result(
        essay="# Pricing\n\nGrounded essay.",
        citations=(Ship30Citation(str(chunk.chunk_id), chunk.episode_id, chunk.episode_title, chunk.source_url),),
        validation=Ship30Validation(3, ()),
        provider_used="ollama",
    )

    with patch.object(orchestrator.retrieval, "retrieve", return_value=[chunk]) as retrieve, patch.object(
        orchestrator, "generate_ship30", AsyncMock(return_value=result)
    ):
        answer, citations, provider = await orchestrator.handle_chat_turn(
            MagicMock(), uuid4(), [], "Write a Ship 30/30 article about pricing strategy", "ollama", Settings()
        )

    assert answer == result.essay
    assert provider == "ollama"
    assert citations[0]["source_url"] == "https://example.test/pricing.md"
    assert retrieve.call_args.kwargs["top_k"] == 5
    assert retrieve.call_args.args[1] == "pricing strategy"


@pytest.mark.asyncio
async def test_normal_ollama_chat_passes_local_generation_limits():
    chunk = SimpleNamespace(
        chunk_id=uuid4(),
        episode_id="pricing-episode",
        episode_title="Pricing episode",
        source_url="https://example.test/pricing.md",
        content="Pricing transcript evidence.",
    )
    generated = AsyncMock(return_value=("Grounded answer", "ollama"))
    settings = Settings()
    settings.normal_chat_generation_timeout_seconds = 123

    with patch.object(orchestrator.retrieval, "retrieve", return_value=[chunk]), patch.object(
        orchestrator, "generate_with_fallback", generated
    ):
        answer, citations, provider = await orchestrator.handle_chat_turn(
            MagicMock(), uuid4(), [], "What is a pricing lesson?", "ollama", settings
        )

    assert answer == "Grounded answer"
    assert provider == "ollama"
    assert citations[0]["source_url"] == "https://example.test/pricing.md"
    assert generated.call_args.kwargs["timeout"] == 123
    assert generated.call_args.kwargs["options"] == {"num_ctx": 4096, "num_predict": 256}
    assert generated.call_args.kwargs["keep_alive"] == "10m"


@pytest.mark.asyncio
async def test_cloud_normal_chat_does_not_receive_ollama_options():
    generated = AsyncMock(return_value=("Cloud answer", "openai"))
    chunk = SimpleNamespace(
        chunk_id=uuid4(), episode_id="pricing", episode_title="Pricing", source_url="https://example.test/p.md", content="Evidence."
    )

    with patch.object(orchestrator.retrieval, "retrieve", return_value=[chunk]), patch.object(
        orchestrator, "generate_with_fallback", generated
    ):
        await orchestrator.handle_chat_turn(
            MagicMock(), uuid4(), [], "What is a pricing lesson?", "openai", Settings()
        )

    assert "timeout" not in generated.call_args.kwargs
    assert "options" not in generated.call_args.kwargs
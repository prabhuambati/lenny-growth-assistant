from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agent.skills import ship30
from app.config import Settings


def make_chunk():
    return SimpleNamespace(
        chunk_id=uuid4(),
        episode_id="ada-chen-rekhi",
        episode_title="Ada Chen-Rekhi on product growth",
        source_url="https://example.test/ada-transcript.md",
        content="Teams should learn from user behavior before choosing a growth lever.",
    )


def valid_draft():
    body = " ".join(["Grounded insight"] * 500)
    return (
        "A pricing decision can quietly determine which users a product is built to serve [Source 1].\n\n"
        "## Start with the customer problem\n\n"
        f"{body}\n\n"
        "- Test the decision against observed behavior.\n"
        "- **Make the next step concrete.**\n\n"
        "## What to do now\n\n"
        "The practical takeaway is to choose one measurable next step and learn from it."
    )


@pytest.mark.asyncio
async def test_ship30_generates_grounded_markdown_and_preserves_sources():
    generated = AsyncMock(return_value=(valid_draft(), "ollama"))
    settings = Settings()
    settings.ship30_generation_timeout_seconds = 456

    with patch.object(ship30, "generate_with_fallback", generated):
        result = await ship30.generate_ship30(
            "pricing strategy", [make_chunk()], "ollama", settings, "Earlier pricing discussion"
        )

    assert result.essay
    assert result.validation.valid
    assert 1050 <= result.validation.word_count <= 1450
    assert result.citations[0].episode_title == "Ada Chen-Rekhi on product growth"
    assert result.citations[0].source_url == "https://example.test/ada-transcript.md"
    assert "https://example.test/ada-transcript.md" in result.essay
    assert "[Source 1]" in result.essay
    assert generated.call_args.kwargs["timeout"] == 456
    assert generated.call_args.kwargs["options"] == {"num_ctx": 8192, "num_predict": 2200}
    prompt = generated.call_args.args[1][0]["content"]
    assert "Earlier pricing discussion" in prompt
    assert "Ada Chen-Rekhi on product growth" in prompt


@pytest.mark.asyncio
async def test_ship30_returns_insufficient_evidence_without_calling_provider():
    generated = AsyncMock()

    with patch.object(ship30, "generate_with_fallback", generated):
        result = await ship30.generate_ship30("Jupiter chemistry", [], "ollama", Settings())

    assert result.insufficient_evidence
    assert result.essay is None
    assert result.citations == ()
    assert "insufficient_evidence" in result.validation.issues
    generated.assert_not_awaited()


@pytest.mark.asyncio
async def test_ship30_allows_one_controlled_revision_for_invalid_draft():
    generated = AsyncMock(side_effect=[("Too short.", "ollama"), (valid_draft(), "ollama")])

    with patch.object(ship30, "generate_with_fallback", generated):
        result = await ship30.generate_ship30("pricing strategy", [make_chunk()], "ollama", Settings())

    assert result.validation.valid
    assert generated.await_count == 2
    assert "word_count" in generated.call_args_list[1].args[1][0]["content"]


def test_ship30_deterministic_structure_validation():
    validation = ship30.validate_draft("Small draft.", [ship30.Ship30Citation("id", "episode", "Title", "https://example.test")])

    assert validation.word_count == 2
    assert set(validation.issues) == {
        "empty_or_placeholder",
        "word_count",
        "opening_hook",
        "meaningful_headings",
        "useful_markdown_formatting",
        "practical_takeaway",
        "source_citations",
    }
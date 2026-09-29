"""Reusable Ship 30 for 30 writing skill.

The skill receives already-retrieved transcript evidence and never queries the
knowledge base itself. It owns the writing prompt, deterministic draft checks,
and source-list rendering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from app.config import Settings
from app.services.llm_client import Message, generate_with_fallback
from app.services.retrieval import RetrievedChunk

MIN_WORDS = 1_050
MAX_WORDS = 1_450
SHIP30_CONTEXT_TOKENS = 8_192
SHIP30_MAX_OUTPUT_TOKENS = 2_200


@dataclass(frozen=True)
class Ship30Citation:
    chunk_id: str
    episode_id: str
    episode_title: str | None
    source_url: str | None


@dataclass(frozen=True)
class Ship30Validation:
    word_count: int
    issues: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class Ship30Result:
    essay: str | None
    citations: tuple[Ship30Citation, ...]
    validation: Ship30Validation
    provider_used: str | None
    insufficient_evidence: bool = False


SHIP30_SYSTEM_PROMPT = """You are the Ship 30 for 30 writing skill for the Lenny Growth Assistant.
Write a useful, coherent Markdown essay about the requested topic using ONLY the supplied Lenny transcript excerpts.
Do not use outside knowledge, invented facts, invented quotes, invented episode details, or invented URLs.
When making a transcript-grounded claim, name the relevant guest or episode and cite it with [Source N], where N matches the supplied evidence.
If the evidence does not support a claim, omit it or state that the transcripts do not establish it.

Writing requirements:
- Write at least 1,050 words and target approximately 1,250 words; do not stop early.
- Open with a strong, specific hook rather than throat-clearing.
- Use meaningful Markdown headings, short paragraphs, bullets where useful, and selective **bold** emphasis.
- Move naturally from problem to insight to practical application.
- End with a concrete takeaway a product or growth team can act on.
- Include at least two meaningful `##` headings and inline [Source N] markers for transcript-grounded claims.
- Use this approximate shape: hook (80-120 words), 3-4 sections (200-260 words each), and a 100-150 word conclusion/takeaway.
- Do not conclude until the essay is at least 1,050 words.
- Return only the essay Markdown, without a preamble or code fence.

Topic: {topic}

Relevant conversation context:
{conversation_context}

Grounded transcript evidence:
{evidence}
"""


REVISION_PROMPT = """Revise the Markdown essay below so it satisfies every listed deterministic check while remaining faithful ONLY to the supplied transcript evidence.
Do not add unsupported facts, quotes, episode details, or URLs. Return only the revised essay Markdown.

Checks to repair: {issues}
The draft is incomplete if it is under 1,050 words. Expand it with supported reasoning and practical application,
using a hook, 3-4 meaningful `##` sections, and a concrete 100-150 word takeaway conclusion.
The revised essay must be at least 1,050 words, include inline [Source N] markers, and end with that takeaway.

Essay:
{essay}

Evidence:
{evidence}
"""


def _citation(chunk: RetrievedChunk) -> Ship30Citation:
    return Ship30Citation(
        chunk_id=str(chunk.chunk_id),
        episode_id=chunk.episode_id,
        episode_title=chunk.episode_title,
        source_url=chunk.source_url,
    )


def _evidence_block(chunks: Sequence[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"[Source {index}] {chunk.episode_title or chunk.episode_id}\n"
        f"URL: {chunk.source_url or 'unavailable'}\n{chunk.content}"
        for index, chunk in enumerate(chunks, start=1)
    )


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w][\w'-]*\b", text))


def validate_draft(essay: str, citations: Sequence[Ship30Citation]) -> Ship30Validation:
    text = essay.strip()
    words = _word_count(text)
    issues: list[str] = []
    headings = re.findall(r"^#{2,3}\s+\S.+$", text, re.MULTILINE)
    first_section = re.split(r"^#{2,3}\s+", text, maxsplit=1, flags=re.MULTILINE)[0]
    lower_text = text.lower()

    if not text or words < 20:
        issues.append("empty_or_placeholder")
    if words < MIN_WORDS or words > MAX_WORDS:
        issues.append("word_count")
    if len(re.findall(r"\b\w+\b", first_section)) < 12:
        issues.append("opening_hook")
    if len(headings) < 2:
        issues.append("meaningful_headings")
    if not re.search(r"^\s*[-*]\s+\S", text, re.MULTILINE) and "**" not in text:
        issues.append("useful_markdown_formatting")
    if not any(term in lower_text for term in ("takeaway", "next step", "what to do now", "action")):
        issues.append("practical_takeaway")
    urls = [citation.source_url for citation in citations if citation.source_url]
    if citations and not re.search(r"\[Source\s+\d+\]", text):
        issues.append("source_citations")
    if urls and not all(url in text for url in urls):
        issues.append("source_citations")
    if citations and not urls:
        issues.append("source_citations")

    return Ship30Validation(words, tuple(dict.fromkeys(issues)))


def _append_sources(essay: str, citations: Sequence[Ship30Citation]) -> str:
    sources = [
        f"- [Source {index}] [{citation.episode_title or citation.episode_id}]({citation.source_url})"
        for index, citation in enumerate(citations, start=1)
        if citation.source_url
    ]
    if not sources:
        return essay.strip()
    return f"{essay.strip()}\n\n## Sources\n\n" + "\n".join(sources)


async def generate_ship30(
    topic: str,
    chunks: Sequence[RetrievedChunk],
    provider: str,
    settings: Settings,
    conversation_context: str = "",
) -> Ship30Result:
    citations = tuple(_citation(chunk) for chunk in chunks)
    if not chunks:
        return Ship30Result(
            essay=None,
            citations=(),
            validation=Ship30Validation(0, ("insufficient_evidence",)),
            provider_used=None,
            insufficient_evidence=True,
        )

    evidence = _evidence_block(chunks)
    messages = [
        Message(
            role="system",
            content=SHIP30_SYSTEM_PROMPT.format(
                topic=topic,
                conversation_context=conversation_context or "None",
                evidence=evidence,
            ),
        ),
        Message(role="user", content=topic),
    ]
    essay, provider_used = await generate_with_fallback(
        provider,
        messages,
        settings,
        timeout=settings.ship30_generation_timeout_seconds,
        max_tokens=SHIP30_MAX_OUTPUT_TOKENS,
        options={"num_ctx": SHIP30_CONTEXT_TOKENS, "num_predict": SHIP30_MAX_OUTPUT_TOKENS},
    )
    essay = _append_sources(essay, citations)
    validation = validate_draft(essay, citations)

    if not validation.valid:
        revision_messages = [
            Message(
                role="system",
                content=REVISION_PROMPT.format(
                    issues=", ".join(validation.issues),
                    essay=essay,
                    evidence=evidence,
                ),
            ),
            Message(role="user", content="Return the corrected essay only."),
        ]
        revised, revision_provider = await generate_with_fallback(
            provider,
            revision_messages,
            settings,
            timeout=settings.ship30_generation_timeout_seconds,
            max_tokens=SHIP30_MAX_OUTPUT_TOKENS,
            options={"num_ctx": SHIP30_CONTEXT_TOKENS, "num_predict": SHIP30_MAX_OUTPUT_TOKENS},
        )
        essay = _append_sources(revised, citations)
        validation = validate_draft(essay, citations)
        provider_used = revision_provider

    return Ship30Result(
        essay=essay,
        citations=citations,
        validation=validation,
        provider_used=provider_used,
    )

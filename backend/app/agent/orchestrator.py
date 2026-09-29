"""Agent orchestration layer. In production this wraps the Claude Agent SDK
(see architecture.md §5); this module defines the tool boundaries and routing
logic that SDK agent is configured to use, kept explicit here so the routing
behavior is easy to test independent of the SDK wiring.
"""

import logging
import re

from sqlalchemy.orm import Session as DBSession

from app.agent.skills.ship30 import Ship30Result, generate_ship30
from app.config import Settings
from app.services import retrieval
from app.services.llm_client import Message, generate_with_fallback

log = logging.getLogger("agent")

INSUFFICIENT_EVIDENCE_REPLY = (
    "I couldn't find anything in Lenny's Podcast transcripts that directly "
    "addresses this. I don't want to guess — could you rephrase, or ask about "
    "a related topic that's more likely to be covered in the episodes?"
)
SHIP30_VALIDATION_FAILED_REPLY = (
    "I found relevant transcript evidence, but the generated Ship 30/30 draft "
    "did not pass its structure and grounding checks. I won't present it as a "
    "finished essay. Please try the request again with a narrower topic."
)

GROUNDED_SYSTEM_PROMPT = (
    "You are the Lenny Growth Assistant. Answer ONLY using the provided "
    "transcript excerpts below. Do not use outside knowledge. If the excerpts "
    "don't contain a real answer, say so plainly instead of guessing. "
    "When you use an excerpt, mention which guest/episode it came from."
)
NORMAL_CHAT_CHUNK_MAX_CHARS = 3_000


def _is_insufficient_evidence_reply(reply_text: str) -> bool:
    marker = "I couldn't find anything in Lenny's Podcast transcripts that directly addresses this."
    return reply_text.strip().casefold().startswith(marker.casefold())


def is_ship30_request(user_message: str) -> bool:
    return "ship 30" in user_message.lower() or "ship30" in user_message.lower()


def _ship30_topic(user_message: str) -> str:
    topic = re.sub(
        r"^\s*(?:please\s+)?(?:write|create|turn\s+this\s+into)\s+"
        r"(?:a\s+)?ship\s*30(?:\s*/\s*30|\s+for\s+30)?(?:\s+(?:article|essay))?\s*",
        "",
        user_message,
        flags=re.IGNORECASE,
    )
    topic = re.sub(r"^\s*(?:about|on|for)\s+", "", topic, flags=re.IGNORECASE)
    return topic.strip() or user_message


def _normal_chat_context(chunks) -> str:
    return "\n\n".join(
        f"[{chunk.episode_title or chunk.episode_id}] (source: {chunk.source_url or 'unavailable'}) "
        f"{chunk.content[:NORMAL_CHAT_CHUNK_MAX_CHARS]}"
        for chunk in chunks
    )

async def handle_chat_turn(db: DBSession, session_id, history: list[Message], user_message: str, provider: str, settings: Settings):
    """Routes a normal chat turn: retrieve -> ground -> generate -> cite."""
    if provider == "anthropic":
        result = await handle_anthropic_agent(db, user_message, history, settings)
        if not result.chunks or not result.text.strip():
            return INSUFFICIENT_EVIDENCE_REPLY, [], provider
        return result.text, [_citation_dict(chunk) for chunk in result.chunks], provider

    is_ship30 = is_ship30_request(user_message)
    retrieval_query = user_message
    if is_ship30:
        retrieval_query = _ship30_topic(user_message)
    chunks = retrieval.retrieve(db, retrieval_query, top_k=5 if is_ship30 else 3)

    if not chunks:
        return INSUFFICIENT_EVIDENCE_REPLY, [], provider

    if is_ship30:
        result = await generate_ship30(
            topic=user_message,
            chunks=chunks,
            provider=provider,
            settings=settings,
            conversation_context="\n".join(message["content"] for message in history[-4:]),
        )
        if result.insufficient_evidence or not result.essay:
            return INSUFFICIENT_EVIDENCE_REPLY, [], provider
        if not result.validation.valid:
            return SHIP30_VALIDATION_FAILED_REPLY, [], result.provider_used or provider
        citations = [_citation_dict(citation) for citation in result.citations]
        return result.essay, citations, result.provider_used or provider

    context_block = _normal_chat_context(chunks)
    messages: list[Message] = [
        Message(role="system", content=f"{GROUNDED_SYSTEM_PROMPT}\n\nTranscript excerpts:\n{context_block}"),
        *history,
        Message(role="user", content=user_message),
    ]

    if provider == "ollama":
        reply_text, provider_used = await generate_with_fallback(
            provider,
            messages,
            settings,
            timeout=settings.normal_chat_generation_timeout_seconds,
            options={"num_ctx": 4096, "num_predict": 256},
            keep_alive="10m",
        )
    else:
        reply_text, provider_used = await generate_with_fallback(provider, messages, settings)

    if _is_insufficient_evidence_reply(reply_text):
        return reply_text, [], provider_used

    citations = [_citation_dict(c) for c in chunks]
    return reply_text, citations, provider_used


def _citation_dict(citation) -> dict:
    return {
        "chunk_id": citation.chunk_id if isinstance(citation.chunk_id, str) else str(citation.chunk_id),
        "episode_id": citation.episode_id,
        "episode_title": citation.episode_title,
        "source_url": citation.source_url,
    }


async def handle_ship30_essay(
    db: DBSession,
    topic: str,
    provider: str,
    settings: Settings,
    conversation_context: str = "",
) -> Ship30Result:
    """Retrieve evidence and invoke the reusable Ship 30 writing skill."""
    chunks = retrieval.retrieve(db, topic, top_k=5)
    return await generate_ship30(topic, chunks, provider, settings, conversation_context)


async def handle_anthropic_agent(
    db: DBSession, prompt: str, history: list[Message], settings: Settings, mode: str = "chat"
):
    """Run the genuine Anthropic Claude Agent SDK runtime when selected."""
    from app.agent.anthropic_runtime import run_anthropic_agent

    return await run_anthropic_agent(db, prompt, history, settings, mode)


ARTIFACT_SYSTEM_PROMPT = (
    "Produce a single self-contained {kind} artifact based only on the grounded "
    "conversation and transcript evidence below. Do not add unsupported facts, "
    "quotes, or URLs. Return ONLY the {kind} content, no commentary, no code fences."
)


async def handle_artifact_generation(db: DBSession, kind: str, context: str, provider: str, settings: Settings) -> str:
    """kind is 'markdown' or 'html'. HTML output is treated as untrusted by the
    frontend regardless of what's generated here — see architecture.md §7."""
    messages: list[Message] = [
        Message(role="system", content=ARTIFACT_SYSTEM_PROMPT.format(kind=kind)),
        Message(role="user", content=context),
    ]
    content, _ = await generate_with_fallback(provider, messages, settings)
    return content

"""Anthropic Claude Agent SDK runtime.

This module is imported lazily by the orchestrator only when Anthropic is the
selected provider. Local Ollama/OpenAI execution does not require an API key or
an SDK process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.agent.skills.ship30 import validate_draft
from app.services import retrieval
from app.services.retrieval import RetrievedChunk


@dataclass(frozen=True)
class AgentRuntimeResult:
    text: str
    chunks: tuple[RetrievedChunk, ...]


def _chunk_payload(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": str(chunk.chunk_id),
            "episode_id": chunk.episode_id,
            "episode_title": chunk.episode_title,
            "source_url": chunk.source_url,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "similarity": chunk.similarity,
        }
        for chunk in chunks
    ]


async def run_anthropic_agent(
    db: DBSession,
    prompt: str,
    history: list[dict[str, str]],
    settings,
    mode: str = "chat",
) -> AgentRuntimeResult:
    """Run Claude Agent SDK with in-process application tools.

    No call is made until this function is invoked for an Anthropic session.
    The SDK owns the agent loop; application tools own retrieval and deterministic
    Ship 30 validation, preserving the existing metadata contract.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        TextBlock,
        create_sdk_mcp_server,
        tool,
    )

    retrieved: list[RetrievedChunk] = []

    @tool(
        "retrieve_transcripts",
        "Retrieve grounded Lenny transcript chunks for the user's request.",
        {"query": str},
    )
    async def retrieve_transcripts(args: dict[str, Any]) -> dict[str, Any]:
        nonlocal retrieved
        retrieved = retrieval.retrieve(db, args["query"])
        return {"content": [{"type": "text", "text": json.dumps(_chunk_payload(retrieved))}]}

    @tool(
        "generate_ship30",
        "Validate a Ship 30/30 Markdown draft against grounded evidence and writing requirements.",
        {"topic": str, "draft": str},
    )
    async def generate_ship30_tool(args: dict[str, Any]) -> dict[str, Any]:
        citations = [
            type("Citation", (), {"source_url": chunk.source_url}) for chunk in retrieved
        ]
        validation = validate_draft(args["draft"], citations)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"valid": validation.valid, "word_count": validation.word_count, "issues": validation.issues}),
                }
            ]
        }

    @tool(
        "generate_artifact",
        "Validate and prepare a grounded Markdown or HTML artifact draft.",
        {"kind": str, "draft": str},
    )
    async def generate_artifact_tool(args: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": args["draft"]}]}

    server = create_sdk_mcp_server(
        name="lenny-growth-assistant",
        version="1.0.0",
        tools=[retrieve_transcripts, generate_ship30_tool, generate_artifact_tool],
    )
    system_prompt = (
        "You are the Lenny Growth Assistant. Use retrieve_transcripts before answering. "
        "Use only retrieved transcript evidence. Preserve source metadata and never invent URLs. "
        "For Ship 30/30 requests, write Markdown of 1,050-1,450 words with a hook, headings, "
        "useful formatting, [Source N] markers, and a concrete takeaway; then call generate_ship30 "
        "to validate your draft and revise once if needed. Return only the final answer."
    )
    if mode == "artifact":
        system_prompt += " For artifact requests, call generate_artifact after grounding the content."

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={"lenny": server},
        allowed_tools=[
            "mcp__lenny__retrieve_transcripts",
            "mcp__lenny__generate_ship30",
            "mcp__lenny__generate_artifact",
        ],
        max_turns=6,
        model=settings.anthropic_model,
    )
    conversation = "\n".join(f"{message['role']}: {message['content']}" for message in history)
    request = f"Conversation:\n{conversation}\n\nUser request:\n{prompt}" if conversation else prompt

    text_parts: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(request)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                text_parts.extend(block.text for block in message.content if isinstance(block, TextBlock))

    return AgentRuntimeResult("\n".join(text_parts).strip(), tuple(retrieved))

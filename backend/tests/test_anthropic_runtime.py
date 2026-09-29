from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agent import anthropic_runtime
from app.config import Settings


@pytest.mark.asyncio
async def test_anthropic_runtime_registers_application_tools_without_calling_cloud():
    chunk = SimpleNamespace(
        chunk_id=uuid4(),
        episode_id="ada-chen-rekhi",
        episode_title="Ada Chen-Rekhi",
        source_url="https://example.test/ada.md",
        chunk_index=1,
        content="Grounded excerpt.",
        similarity=0.8,
    )
    registered = []
    registered_tools = {}

    def fake_tool(name, description, schema):
        def decorate(function):
            registered.append(name)
            registered_tools[name] = function
            return function

        return decorate

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.query = AsyncMock()

    async def receive_response():
        if False:
            yield None

    fake_client.receive_response = receive_response
    fake_options = MagicMock()
    fake_server = MagicMock()

    with patch("claude_agent_sdk.tool", side_effect=fake_tool), patch(
        "claude_agent_sdk.create_sdk_mcp_server", return_value=fake_server
    ) as create_server, patch(
        "claude_agent_sdk.ClaudeAgentOptions", return_value=fake_options
    ) as options, patch(
        "claude_agent_sdk.ClaudeSDKClient", return_value=fake_client
    ), patch.object(anthropic_runtime.retrieval, "retrieve", return_value=[chunk]):
        result = await anthropic_runtime.run_anthropic_agent(
            MagicMock(), "What did Ada recommend?", [], Settings()
        )
        retrieval_result = await registered_tools["retrieve_transcripts"]({"query": "Ada recommendation"})

    assert registered == ["retrieve_transcripts", "generate_ship30", "generate_artifact"]
    create_server.assert_called_once()
    assert len(create_server.call_args.kwargs["tools"]) == 3
    options.assert_called_once()
    assert options.call_args.kwargs["mcp_servers"] == {"lenny": fake_server}
    fake_client.query.assert_awaited_once_with("What did Ada recommend?")
    assert result.text == ""
    assert "https://example.test/ada.md" in retrieval_result["content"][0]["text"]
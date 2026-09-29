from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_client import GeminiClient, ProviderUnavailableError


@pytest.mark.asyncio
async def test_gemini_without_key_returns_clear_error():
    client = GeminiClient(None, "gemini-2.5-flash")

    assert await client.is_reachable() is False
    with pytest.raises(ProviderUnavailableError, match="GEMINI_API_KEY"):
        await client.generate([], timeout=1)


@pytest.mark.asyncio
async def test_gemini_maps_messages_without_calling_real_api():
    response = MagicMock()
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "Grounded answer"}]}}]
    }
    response.raise_for_status.return_value = None
    client = GeminiClient("test-key", "gemini-2.5-flash")
    fake_http = MagicMock()
    fake_http.post = AsyncMock(return_value=response)
    fake_context = MagicMock()
    fake_context.__aenter__ = AsyncMock(return_value=fake_http)
    fake_context.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.llm_client.httpx.AsyncClient", return_value=fake_context):
        result = await client.generate(
            [{"role": "system", "content": "Use evidence."}, {"role": "user", "content": "Question"}],
            timeout=1,
        )

    assert result == "Grounded answer"
    payload = fake_http.post.call_args.kwargs["json"]
    assert payload["systemInstruction"]["parts"][0]["text"] == "Use evidence."
    assert payload["contents"] == [{"role": "user", "parts": [{"text": "Question"}]}]
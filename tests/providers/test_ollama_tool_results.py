"""Ollama OpenAI-compatible message normalization tests."""

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


def test_ollama_serializes_structured_tool_results_as_json_text() -> None:
    provider = OpenAICompatProvider(
        api_key="ollama-test-key",
        default_model="gemma4:31b",
        spec=find_by_name("ollama"),
    )

    messages = provider._sanitize_messages(
        [
            {"role": "user", "content": "Look this up."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"key":"value"}',
                    },
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "name": "lookup",
                "content": {"value": 42},
            },
        ],
        "gemma4:31b",
    )

    assert messages[-1]["content"] == '{"value": 42}'
    assert messages[1]["content"] is None

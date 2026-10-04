"""The Simo request guard blocks both retry-managed provider call paths."""

import pytest

from nanobot.providers.base import LLMProvider, LLMResponse
from simo.egress import EgressGuard, ProtectedIdentity
from simo.provider_guard import install_provider_guard


class _RecordingProvider(LLMProvider):
    _CHAT_RETRY_DELAYS = ()

    def __init__(self) -> None:
        super().__init__(provider_name="test")
        self.sent = 0

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(self, **kwargs) -> LLMResponse:
        self.sent += 1
        return LLMResponse(content="{}", finish_reason="stop")

    async def chat_stream(self, **kwargs) -> LLMResponse:
        self.sent += 1
        return LLMResponse(content="{}", finish_reason="stop")


@pytest.mark.parametrize("stream", [False, True])
async def test_guard_prevents_retry_managed_model_send(stream: bool) -> None:
    provider = _RecordingProvider()
    guard = EgressGuard()
    guard.replace_roster([ProtectedIdentity("student-1", "Amara Patel")])
    install_provider_guard(provider, guard)
    messages = [{"role": "user", "content": "Grade Amara Patel's response"}]

    if stream:
        result = await provider.chat_stream_with_retry(messages=messages, model="test-model")
    else:
        result = await provider.chat_with_retry(messages=messages, model="test-model")

    assert result.finish_reason == "error"
    assert "model request blocked by roster egress guard" in (result.content or "")
    assert provider.sent == 0

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from simo.config import LLMConfig
from simo.egress import EgressBlocked, EgressGuard, ProtectedIdentity
from simo.llm import LLMClient, LLMError, TokenBudgetExceeded, parse_json_object


def make_config(tmp_path: Path, **kwargs: object) -> LLMConfig:
    defaults: dict[str, object] = {
        "base_url": "https://api.example.test/v1",
        "api_key": "test-key",
        "model": "test-model",
        "mode": "live",
        "cassette_dir": tmp_path / "cassettes",
        "max_retries": 0,
        "max_run_tokens": 100,
        "request_timeout": 1,
    }
    defaults.update(kwargs)
    return LLMConfig(**defaults)  # type: ignore[arg-type]


def test_live_request_checks_egress_before_transport(tmp_path: Path) -> None:
    calls: list[bytes] = []

    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        calls.append(body)
        return b"{}"

    guard = EgressGuard()
    guard.replace_roster([ProtectedIdentity("student-1", "Amara Patel")])
    client = LLMClient(make_config(tmp_path), guard, transport=transport)
    with pytest.raises(EgressBlocked):
        client.complete_json([{"role": "user", "content": "Grade Amara Patel's answer"}])
    assert calls == []


def test_record_and_replay_do_not_store_request_text(tmp_path: Path) -> None:
    response = {
        "choices": [{"message": {"content": '{"level_id":"L1",}', "role": "assistant"}}],
        "usage": {"total_tokens": 7},
    }
    calls: list[bytes] = []

    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        calls.append(body)
        return json.dumps(response).encode()

    request_text = "synthetic answer Alpha Beta"
    record = LLMClient(
        make_config(tmp_path, mode="record", cassette_allow_text=True),
        EgressGuard(),
        transport=transport,
    )
    result = record.complete_json([{"role": "user", "content": request_text}])
    cassette = next((tmp_path / "cassettes").glob("*.json"))
    assert request_text.encode() not in cassette.read_bytes()
    assert result.value == {"level_id": "L1"}
    assert len(calls) == 1

    replay = LLMClient(make_config(tmp_path, mode="replay", api_key=None), EgressGuard())
    replayed = replay.complete_json([{"role": "user", "content": request_text}])
    assert replayed.value == result.value
    assert replayed.cassette_key == result.cassette_key


def test_record_requires_explicit_text_storage_opt_in(tmp_path: Path) -> None:
    client = LLMClient(make_config(tmp_path, mode="record"), EgressGuard(), transport=lambda *args: b"{}")
    with pytest.raises(LLMError, match="CASSETTE_ALLOW_TEXT"):
        client.complete_json([{"role": "user", "content": "synthetic"}])


def test_token_budget_stops_before_second_request(tmp_path: Path) -> None:
    calls = 0

    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        return json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 15}}).encode()

    client = LLMClient(make_config(tmp_path, max_run_tokens=20), EgressGuard(), transport=transport)
    client.complete_json([{"role": "user", "content": "first"}], max_tokens=10)
    with pytest.raises(TokenBudgetExceeded):
        client.complete_json([{"role": "user", "content": "second"}], max_tokens=1)
    assert calls == 1


def test_retry_transient_http_errors_with_bounded_delay(tmp_path: Path) -> None:
    calls = 0
    waits: list[float] = []

    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(url, 503, "unavailable", {}, None)
        return json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 1}}).encode()

    client = LLMClient(
        make_config(tmp_path, max_retries=1), EgressGuard(), transport=transport, sleeper=waits.append
    )
    client.complete_json([{"role": "user", "content": "synthetic"}])
    assert calls == 2
    assert waits == [1]


def test_json_parser_repairs_trailing_comma_and_rejects_non_object() -> None:
    assert parse_json_object("```json\n{\"level\": \"L0\",}\n```") == {"level": "L0"}
    with pytest.raises(LLMError, match="JSON object"):
        parse_json_object("[1, 2]")

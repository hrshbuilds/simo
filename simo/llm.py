"""OpenAI-compatible model client with guarded live, record, and replay modes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simo.config import LLMConfig
from simo.egress import EgressGuard


class LLMError(RuntimeError):
    """A safe, user-facing model request failure."""


class TokenBudgetExceeded(LLMError):
    """The current run cannot spend more model tokens."""


Transport = Callable[[str, dict[str, str], bytes, float], bytes]
Sleeper = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class LLMResult:
    value: dict[str, Any]
    content: str
    model: str
    tokens_used: int
    cassette_key: str


class LLMClient:
    """One checked boundary for each outbound OpenAI-compatible request."""

    def __init__(
        self,
        config: LLMConfig,
        egress_guard: EgressGuard,
        *,
        transport: Transport | None = None,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self.config = config
        self.egress_guard = egress_guard
        self._transport = transport or _http_post
        self._sleep = sleeper
        self._tokens_used = 0
        if config.mode in {"live", "record"} and not config.api_key:
            raise ValueError("LLM_API_KEY is required for live and record modes")
        if not config.model and config.mode in {"live", "record"}:
            raise ValueError("LLM_MODEL is required for live and record modes")

    @property
    def tokens_used(self) -> int:
        return self._tokens_used

    def reset_budget(self) -> None:
        """Start a new run budget. Call once at the start of each workflow run."""
        self._tokens_used = 0

    def restore_budget(self, tokens_used: int) -> None:
        """Restore the consumed portion of a persisted workflow run."""
        if tokens_used < 0 or tokens_used > self.config.max_run_tokens:
            raise ValueError("persisted token usage is outside the configured run budget")
        self._tokens_used = tokens_used

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        selected_model = model or self.config.model
        if not selected_model:
            raise ValueError("a model must be configured or provided")
        request: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        input_estimate = max(1, _estimate_tokens(_canonical_json(messages)))
        available = self.config.max_run_tokens - self._tokens_used - input_estimate
        if available < 1:
            raise TokenBudgetExceeded("run token budget is exhausted before this request")
        request_limit = min(available, max_tokens) if max_tokens is not None else available
        if request_limit < 1:
            raise TokenBudgetExceeded("no output tokens remain in the run budget")
        request["max_tokens"] = request_limit
        key = hashlib.sha256(_canonical_json(request).encode("utf-8")).hexdigest()

        if self.config.mode == "replay":
            raw_response = self._read_cassette(key)
        else:
            if self.config.mode == "record" and not self.config.cassette_allow_text:
                raise LLMError("record mode requires CASSETTE_ALLOW_TEXT=true; cassettes may contain student quotes")
            response_payload = self._request(request)
            raw_response = _canonical_json(response_payload).encode("utf-8")
            if self.config.mode == "record":
                self._write_cassette(key, raw_response)

        try:
            response = json.loads(raw_response)
            content = response["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("model response did not match the chat-completions response shape") from exc
        value = parse_json_object(content)
        usage = response.get("usage")
        usage_value = usage.get("total_tokens") if isinstance(usage, dict) else None
        token_count = (
            usage_value
            if isinstance(usage_value, int) and usage_value >= 0
            else input_estimate + _estimate_tokens(content)
        )
        if self._tokens_used + token_count > self.config.max_run_tokens:
            self._tokens_used = self.config.max_run_tokens
            raise TokenBudgetExceeded("model response exceeded the remaining run token budget")
        self._tokens_used += token_count
        return LLMResult(value, content, selected_model, token_count, key)

    async def acomplete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        """Run the blocking standard-library transport without blocking the event loop."""
        return await asyncio.to_thread(
            self.complete_json,
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Run the guard on the exact structured body immediately before every send.
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.config.api_key}"}
        self.egress_guard.assert_safe(payload)
        for attempt in range(self.config.max_retries + 1):
            try:
                response_bytes = self._transport(
                    f"{self.config.base_url}/chat/completions",
                    headers,
                    body,
                    self.config.request_timeout,
                )
                response = json.loads(response_bytes)
                if not isinstance(response, dict):
                    raise LLMError("model returned an invalid response")
                return response
            except urllib.error.HTTPError as exc:
                retryable = exc.code in {408, 409, 429} or 500 <= exc.code <= 599
                if not retryable or attempt >= self.config.max_retries:
                    raise LLMError(f"model request failed with HTTP {exc.code}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt >= self.config.max_retries:
                    raise LLMError(f"model request failed ({type(exc).__name__})") from None
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                if attempt >= self.config.max_retries:
                    raise LLMError("model returned invalid JSON") from exc
            self._sleep(min(2**attempt, 8))
        raise LLMError("model request failed")

    def _read_cassette(self, key: str) -> bytes:
        path = self.config.cassette_dir / f"{key}.json"
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise LLMError(f"no replay cassette for request {key[:12]}") from None

    def _write_cassette(self, key: str, response: bytes) -> None:
        directory = self.config.cassette_dir
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{key}.json"
        temporary = directory / f".{key}.json.tmp"
        temporary.write_bytes(response)
        temporary.replace(destination)


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse JSON, repairing common formatting slips without another model call."""
    candidate = content.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        # A narrow repair: tolerate trailing commas before a closing bracket.
        repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            value = json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise LLMError("model response was not valid JSON") from exc
    if not isinstance(value, dict):
        raise LLMError("model response must be a JSON object")
    return value


def _http_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)

"""Environment-backed configuration for Simo's model boundary."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LLMConfig:
    base_url: str
    api_key: str | None
    model: str | None
    mode: str
    cassette_dir: Path
    max_retries: int
    max_run_tokens: int
    request_timeout: float
    cassette_allow_text: bool = False

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Build settings from the documented environment variables."""
        mode = os.getenv("LLM_MODE", "live").strip().lower()
        if mode not in {"live", "record", "replay"}:
            raise ValueError("LLM_MODE must be live, record, or replay")
        retries = _int_env("MAX_RETRIES", 2, minimum=0)
        budget = _int_env("MAX_RUN_TOKENS", 20_000, minimum=1)
        timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
        if timeout <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be positive")
        return cls(
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            api_key=os.getenv("LLM_API_KEY") or None,
            model=os.getenv("LLM_MODEL") or None,
            mode=mode,
            cassette_dir=Path(os.getenv("CASSETTE_DIR", "./eval/cassettes")),
            max_retries=retries,
            max_run_tokens=budget,
            request_timeout=timeout,
            cassette_allow_text=os.getenv("CASSETTE_ALLOW_TEXT", "false").lower() == "true",
        )


def _int_env(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value

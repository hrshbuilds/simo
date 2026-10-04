"""Attach Simo's fail-closed roster check to nanobot model providers."""

from __future__ import annotations

from simo.egress import EgressGuard
from nanobot.providers.base import LLMProvider


def install_provider_guard(provider: LLMProvider, guard: EgressGuard) -> None:
    """Install the egress guard on one nanobot ``LLMProvider`` instance.

    Fail loudly if the provider does not expose the supported guard hook; a
    missing boundary must never silently degrade to an observer-only check.
    """
    provider.set_llm_request_guard(guard.assert_safe)

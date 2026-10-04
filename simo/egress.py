"""Fail-closed checks for sensitive roster identifiers in model requests."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


class EgressBlocked(RuntimeError):
    """Raised before a model request if it contains a protected identifier."""


@dataclass(frozen=True, slots=True)
class ProtectedIdentity:
    student_id: str
    real_name: str
    variants: tuple[str, ...] = ()


class EgressGuard:
    """Reject outbound payloads containing registered real identities."""

    def __init__(self) -> None:
        self._identities: dict[str, ProtectedIdentity] = {}

    def replace_roster(self, identities: list[ProtectedIdentity]) -> None:
        self._identities = {item.student_id: item for item in identities}

    def assert_safe(self, payload: Any) -> None:
        text = payload if isinstance(payload, str) else _stringify(payload)
        for student_id, identity in self._identities.items():
            candidates = (student_id, identity.real_name, *identity.variants)
            for candidate in sorted((x.strip() for x in candidates if x.strip()), key=len, reverse=True):
                if _contains_identifier(text, candidate):
                    # Deliberately do not include the matched value in the exception or logs.
                    raise EgressBlocked("model request blocked by roster egress guard")


def _stringify(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join([*(_stringify(key) for key in value), *(_stringify(item) for item in value.values())])
    if isinstance(value, (list, tuple, set)):
        return " ".join(_stringify(item) for item in value)
    return str(value)


def _contains_identifier(text: str, identifier: str) -> bool:
    # Unicode-aware case folding while retaining word boundaries for names such as
    # "Ann Lee"; punctuation and spacing inside the identifier remain significant.
    folded_text = unicodedata.normalize("NFKC", text).casefold()
    folded_identifier = unicodedata.normalize("NFKC", identifier).casefold()
    pattern = rf"(?<!\w){re.escape(folded_identifier)}(?!\w)"
    return re.search(pattern, folded_text, flags=re.UNICODE) is not None

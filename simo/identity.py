"""Teacher-side identity vault and pseudonymization helpers."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from simo.egress import EgressGuard, ProtectedIdentity


@dataclass(frozen=True, slots=True)
class StudentIdentity:
    student_id: str
    pseudonym: str
    real_name: str
    variants: tuple[str, ...] = ()


class IdentityVault:
    """In-memory name map. Keep this object outside model-facing code paths."""

    def __init__(self, *, egress_guard: EgressGuard | None = None) -> None:
        self._by_id: dict[str, StudentIdentity] = {}
        self._by_pseudonym: dict[str, StudentIdentity] = {}
        self._guard = egress_guard

    def add(self, student_id: str, real_name: str, variants: list[str] | tuple[str, ...] = ()) -> StudentIdentity:
        student_id, real_name = student_id.strip(), real_name.strip()
        if not student_id or not real_name:
            raise ValueError("student_id and real_name are required")
        aliases = tuple(dict.fromkeys(alias.strip() for alias in variants if alias.strip()))
        existing = self._by_id.get(student_id)
        pseudonym = existing.pseudonym if existing else self._new_pseudonym()
        identity = StudentIdentity(student_id, pseudonym, real_name, aliases)
        if existing:
            self._by_pseudonym.pop(existing.pseudonym, None)
        self._by_id[student_id] = identity
        self._by_pseudonym[pseudonym] = identity
        self._refresh_guard()
        return identity

    def pseudonymize(self, text: str) -> str:
        result = text
        identities = sorted(self._by_id.values(), key=lambda item: max(map(len, (item.real_name, *item.variants))), reverse=True)
        for item in identities:
            for name in sorted((item.student_id, item.real_name, *item.variants), key=len, reverse=True):
                result = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", item.pseudonym, result, flags=re.IGNORECASE)
        return result

    def reidentify(self, text: str) -> str:
        result = text
        for pseudonym, identity in sorted(self._by_pseudonym.items(), key=lambda pair: len(pair[0]), reverse=True):
            result = re.sub(rf"(?<!\w){re.escape(pseudonym)}(?!\w)", identity.real_name, result)
        return result

    def model_identities(self) -> tuple[tuple[str, str], ...]:
        """Return only stable IDs and pseudonyms; never return names or aliases."""
        return tuple((item.student_id, item.pseudonym) for item in self._by_id.values())

    def _new_pseudonym(self) -> str:
        while True:
            value = f"S-{secrets.token_hex(2).upper()}"
            if value not in self._by_pseudonym:
                return value

    def _refresh_guard(self) -> None:
        if self._guard is not None:
            self._guard.replace_roster([
                ProtectedIdentity(item.student_id, item.real_name, item.variants)
                for item in self._by_id.values()
            ])

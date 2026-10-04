from __future__ import annotations

import pytest

from simo.egress import EgressBlocked, EgressGuard
from simo.identity import IdentityVault


def test_identity_mapping_scrubs_names_and_reidentifies_only_pseudonyms() -> None:
    guard = EgressGuard()
    vault = IdentityVault(egress_guard=guard)
    identity = vault.add("internal-17", "Aarav Rao", ["Aarav"])

    clean = vault.pseudonymize("Aarav Rao scored 4; Aarav needs another example.")

    assert identity.pseudonym in clean
    assert "Aarav" not in clean
    assert vault.reidentify(clean).count("Aarav Rao") == 2
    assert "Aarav" in vault.reidentify(clean)
    assert vault.pseudonymize("Submission internal-17: answer") == f"Submission {identity.pseudonym}: answer"


def test_egress_guard_blocks_name_variant_and_internal_id_without_echoing_match() -> None:
    guard = EgressGuard()
    guard.replace_roster([])
    vault = IdentityVault(egress_guard=guard)
    vault.add("internal-17", "Aarav Rao", ["Aarav"])

    for request in ({"messages": [{"content": "Dear AARAV, try again"}]}, {"metadata": "internal-17"}):
        with pytest.raises(EgressBlocked) as err:
            guard.assert_safe(request)
        assert "Aarav" not in str(err.value)
        assert "internal-17" not in str(err.value)


def test_egress_guard_uses_word_boundaries() -> None:
    guard = EgressGuard()
    guard.replace_roster([])
    vault = IdentityVault(egress_guard=guard)
    vault.add("id-1", "Ann Lee")

    guard.assert_safe("The annual report includes this analysis.")
    with pytest.raises(EgressBlocked):
        guard.assert_safe("Feedback for Ann Lee is ready.")

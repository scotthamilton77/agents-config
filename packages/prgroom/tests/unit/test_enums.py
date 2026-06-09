"""Enum-member enumeration tests (§7.6 exhaustiveness leg).

Python has no compile-time exhaustiveness check over a StrEnum. The §7.6 safety
triple is: a closed ``match`` with ``case _:``, ``mypy --strict``, and a
member-enumeration test. This file is that third leg for the foundation's
serialization-bearing enums: every member must survive ``Enum(member.value)``
reconstruction, so a member whose value is mistyped (a wire-contract break)
fails here loudly.
"""

from __future__ import annotations

import pytest

from prgroom.prsession.enums import (
    DispositionKind,
    ItemKind,
    PRPhase,
    ReviewerKind,
    ReviewerStatus,
)

_ALL_ENUMS = [PRPhase, ItemKind, DispositionKind, ReviewerKind, ReviewerStatus]


@pytest.mark.parametrize("enum_cls", _ALL_ENUMS)
def test_every_member_reconstructs_from_its_wire_value(enum_cls: type) -> None:
    for member in enum_cls:
        assert enum_cls(member.value) is member


def test_pr_phase_has_the_six_canonical_phases() -> None:
    # The phase set is a closed lifecycle contract (§2); a 7th member or a
    # dropped one is a breaking change that must be caught deliberately.
    assert {p.value for p in PRPhase} == {
        "idle",
        "awaiting-review",
        "fixes-pending",
        "quiesced",
        "human-gated",
        "merged",
    }


def test_disposition_has_the_seven_outcomes() -> None:
    assert {d.value for d in DispositionKind} == {
        "fixed",
        "already_addressed",
        "skipped",
        "deferred",
        "wont_fix",
        "escalated",
        "failed",
    }

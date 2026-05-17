"""Unit tests for installer.core.model.

Each test pins a design decision recorded in the A.2 design doc
(docs/specs/2026-05-17-w1qls.1.2-model-design.md §5). Tests that would
only verify Python language semantics (enum membership, dict get/set,
int increment) are deliberately absent — see §5.1 of the design doc.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import assert_never

import pytest

from installer.core.model import (
    AllRulesInclude,
    Counters,
    FileInclude,
    FileKind,
    IncludeDirective,
    Orphan,
    Provenance,
    StagedItem,
)


# ───────────────────────────── helpers ─────────────────────────────


def _provenance() -> Provenance:
    return Provenance(kind="tool", name="claude")


def _staged_item(**overrides: object) -> StagedItem:
    base: dict[str, object] = {
        "source_path": Path("/abs/src/file.md"),
        "dest_relpath": Path("rules/file.md"),
        "kind": FileKind.NAMESPACED_MD,
        "namespace": "rules",
        "provenance": _provenance(),
        "content": b"hello",
    }
    base.update(overrides)
    return StagedItem(**base)  # type: ignore[arg-type]


def _orphan(**overrides: object) -> Orphan:
    base: dict[str, object] = {
        "tool": "claude",
        "namespace": "commands",
        "path": Path("/abs/dest/commands/old-thing"),
        "kind": "file",
    }
    base.update(overrides)
    return Orphan(**base)  # type: ignore[arg-type]


# ─────────────── 1. test_provenance_equality ───────────────


def test_provenance_equality() -> None:
    a = Provenance(kind="tool", name="claude")
    b = Provenance(kind="tool", name="claude")
    assert a == b
    assert a != Provenance(kind="tool", name="codex")
    assert a != Provenance(kind="plugin", name="claude")


# ─────────────── 2. test_provenance_is_frozen ───────────────


def test_provenance_is_frozen() -> None:
    p = Provenance(kind="tool", name="claude")
    with pytest.raises(FrozenInstanceError):
        p.name = "codex"  # type: ignore[misc]


# ─────────────── 3. test_file_include_construction_and_equality ───────────────


def test_file_include_construction_and_equality() -> None:
    a = FileInclude(path=Path("a"))
    b = FileInclude(path=Path("a"))
    c = FileInclude(path=Path("b"))
    assert a == b
    assert a != c


# ─────────────── 4. test_all_rules_include_is_singleton_by_value ───────────────


def test_all_rules_include_is_singleton_by_value() -> None:
    assert AllRulesInclude() == AllRulesInclude()


# ─────────────── 5. test_staged_item_equality_and_frozen ───────────────


def test_staged_item_equality_and_frozen() -> None:
    a = _staged_item()
    b = _staged_item()
    c = _staged_item(content=b"different")
    assert a == b
    assert a != c
    with pytest.raises(FrozenInstanceError):
        a.content = b"mutated"  # type: ignore[misc]


def test_staged_item_executable_defaults_false_and_round_trips() -> None:
    """Pins the executable=False default and that True overrides cleanly."""
    item = _staged_item()
    assert item.executable is False
    promoted = _staged_item(executable=True)
    assert promoted.executable is True
    assert item != promoted


# ─────────────── 6. test_orphan_equality_and_frozen ───────────────


def test_orphan_equality_and_frozen() -> None:
    a = _orphan()
    b = _orphan()
    c = _orphan(kind="dir")
    assert a == b
    assert a != c
    with pytest.raises(FrozenInstanceError):
        a.namespace = "skills"  # type: ignore[misc]


# ─────────────── 7. test_include_directive_match_dispatches_to_both_arms ───────────────


def test_include_directive_match_dispatches_to_both_arms() -> None:
    """Runtime match over IncludeDirective reaches each arm exactly once.

    Static exhaustiveness (mypy assert_never at consumer sites) is a
    separate guarantee — this test only confirms the union admits both
    variants today.
    """

    def describe(d: IncludeDirective) -> str:
        match d:
            case FileInclude(path=p):
                return f"file:{p}"
            case AllRulesInclude():
                return "all-rules"
            case _:  # pragma: no cover  — defensive; mypy will flag if reachable
                assert_never(d)

    assert describe(FileInclude(path=Path("x.md"))) == "file:x.md"
    assert describe(AllRulesInclude()) == "all-rules"


# ─────────────── 8. test_counters_default_to_zero ───────────────


def test_counters_default_to_zero() -> None:
    c = Counters()
    assert c.staged == 0
    assert c.created == 0
    assert c.updated == 0
    assert c.skipped == 0
    assert c.pruned == 0
    assert c.backed_up == 0


# ─────────────── 9. test_frozen_items_are_hashable ───────────────


def test_frozen_items_are_hashable() -> None:
    items: set[object] = {_staged_item(), _orphan(), _provenance()}
    assert len(items) == 3
    assert _staged_item() in items
    assert _orphan() in items
    assert _provenance() in items

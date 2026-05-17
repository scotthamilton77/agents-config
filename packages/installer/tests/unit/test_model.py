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
    return StagedItem(**base)


def _orphan(**overrides: object) -> Orphan:
    base: dict[str, object] = {
        "tool": "claude",
        "namespace": "commands",
        "path": Path("/abs/dest/commands/old-thing"),
        "kind": "file",
    }
    base.update(overrides)
    return Orphan(**base)


# ───────────────────────── Provenance ─────────────────────────


def test_provenance_equality() -> None:
    a = Provenance(kind="tool", name="claude")
    b = Provenance(kind="tool", name="claude")
    assert a == b
    assert a != Provenance(kind="tool", name="codex")
    assert a != Provenance(kind="plugin", name="claude")


def test_provenance_is_frozen() -> None:
    p = Provenance(kind="tool", name="claude")
    with pytest.raises(FrozenInstanceError):
        p.name = "codex"


# ───────────────────────── IncludeDirective variants ─────────────────────────


def test_file_include_construction_and_equality() -> None:
    a = FileInclude(path=Path("a"))
    b = FileInclude(path=Path("a"))
    c = FileInclude(path=Path("b"))
    assert a == b
    assert a != c


def test_file_include_is_frozen() -> None:
    fi = FileInclude(path=Path("a"))
    with pytest.raises(FrozenInstanceError):
        fi.path = Path("b")


def test_all_rules_include_is_singleton_by_value() -> None:
    assert AllRulesInclude() == AllRulesInclude()


def test_all_rules_include_is_frozen() -> None:
    """AllRulesInclude is an empty `@dataclass(frozen=True, slots=True)`
    marker. Asserting via `pytest.raises(FrozenInstanceError)` does NOT
    work here because of a CPython interaction: `slots=True` synthesises
    a new class to install `__slots__`, and the frozen-generated
    `__setattr__` ends up referencing a stale `__class__` for its
    `super()` call. The observable error on `ar.x = "v"` is
    `TypeError: super(type, obj): obj ... is not an instance or subtype of
    type` — confusing for a test reader and not the contract we care
    about. Instead, assert the contract directly via the dataclass
    parameters: if a future change drops `frozen=True`, this fails AND
    `__hash__` becomes `None`, which the hashability test also catches."""
    assert AllRulesInclude.__dataclass_params__.frozen is True


# ───────────────────────── StagedItem ─────────────────────────


def test_staged_item_equality_and_frozen() -> None:
    a = _staged_item()
    b = _staged_item()
    c = _staged_item(content=b"different")
    assert a == b
    assert a != c
    with pytest.raises(FrozenInstanceError):
        a.content = b"mutated"


def test_staged_item_executable_defaults_false_and_round_trips() -> None:
    """Pins the executable=False default and that True overrides cleanly."""
    item = _staged_item()
    assert item.executable is False
    promoted = _staged_item(executable=True)
    assert promoted.executable is True
    assert item != promoted


def test_staged_item_accepts_dir_kind_with_no_content() -> None:
    """Pins the FileKind.DIR / content=None contract: top-level skill or
    agent directories stage as a single StagedItem with content omitted.
    The sync engine reads the source tree at copy time."""
    dir_item = StagedItem(
        source_path=Path("/abs/src/skills/my-skill"),
        dest_relpath=Path("skills/my-skill"),
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
    )
    assert dir_item.content is None
    assert dir_item.kind is FileKind.DIR


# ───────────────────────── Orphan ─────────────────────────


def test_orphan_equality_and_frozen() -> None:
    a = _orphan()
    b = _orphan()
    c = _orphan(kind="dir")
    assert a == b
    assert a != c
    with pytest.raises(FrozenInstanceError):
        a.namespace = "skills"


# ───────────────────────── Discriminated union dispatch ─────────────────────────


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


# ───────────────────────── Counters ─────────────────────────


def test_counters_default_to_zero() -> None:
    c = Counters()
    assert c.staged == 0
    assert c.created == 0
    assert c.updated == 0
    assert c.skipped == 0
    assert c.pruned == 0
    assert c.backed_up == 0


# ───────────────────────── Hashability ─────────────────────────


def test_frozen_items_are_hashable() -> None:
    items: set[object] = {
        _staged_item(),
        _orphan(),
        _provenance(),
        FileInclude(path=Path("x.md")),
        AllRulesInclude(),
    }
    assert len(items) == 5
    assert _staged_item() in items
    assert _orphan() in items
    assert _provenance() in items
    assert FileInclude(path=Path("x.md")) in items
    assert AllRulesInclude() in items

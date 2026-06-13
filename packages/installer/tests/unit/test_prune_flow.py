"""Unit tests for installer.core.prune_flow (G.4 — interactive prune flow).

Each test pins a coded decision in ``run_prune``, the port of the bash
``prune_orphans`` (``scripts/install.sh:1602-1687``). The engine is driven
through ``ScriptedIO`` and asserted against real filesystem end-state plus the
returned ``Counters`` — never against which IOPort method was called.

Covered decisions:
- three-way "all" -> every orphan backed up then deleted,
- three-way "one-by-one" -> per-item y deletes, n/default skips, q stops the rest,
- three-way "cancel" -> nothing deleted,
- non-interactive + prune_only + not auto_yes + not dry_run -> hard fail,
- non-interactive + plain prune (not prune_only) -> warn + skip, no deletes,
- auto_yes -> delete all without prompting,
- dry_run -> display only, no deletes,
- empty orphan list -> no prompt, no deletes,
- backup precedes delete (a sibling <namespace>-backup/ copy survives the rm),
- directory orphans are backed up recursively,
- a malformed timestamp under a deleting path (auto_yes) raises before any delete,
- a malformed timestamp under dry_run does NOT raise (no timestamp is resolved),
- a symlink-to-directory orphan is unlinked (not rmtree'd): the link is removed,
  its target directory survives, and the flow completes without raising.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.io_port import PerItemResult, ScriptedIO
from installer.core.model import Orphan
from installer.core.prune_flow import PruneAbortedError, run_prune

_TS = "20250101-120000"


def _file_orphan(home: Path, tool: str, namespace: str, name: str, body: str = "x") -> Orphan:
    d = home / f".{tool}" / namespace
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    path.write_text(body)
    return Orphan(tool=tool, namespace=namespace, path=path, kind="file")


def _dir_orphan(home: Path, tool: str, namespace: str, name: str) -> Orphan:
    d = home / f".{tool}" / namespace / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "inner.md").write_text("inner")
    return Orphan(tool=tool, namespace=namespace, path=d, kind="dir")


def test_three_way_all_deletes_every_orphan(tmp_path: Path) -> None:
    """
    Given two orphans and an interactive answer of "all"
    When run_prune executes
    Then both paths are gone and pruned == 2.
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "a")
    o2 = _file_orphan(tmp_path, "claude", "skills", "b")
    io = ScriptedIO(three_ways=["a"])

    counters = run_prune([o1, o2], io=io, timestamp=_TS)

    assert not o1.path.exists()
    assert not o2.path.exists()
    assert counters.pruned == 2


def test_three_way_one_by_one_respects_per_item_choices(tmp_path: Path) -> None:
    """
    Given two orphans, "one-by-one", and per-item decisions keep-a / drop-b
    When run_prune executes
    Then only b is deleted and pruned == 1.
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "a")
    o2 = _file_orphan(tmp_path, "claude", "skills", "b")
    io = ScriptedIO(
        three_ways=["o"],
        per_items=[PerItemResult(decisions={str(o1.path): False, str(o2.path): True}, quit=False)],
    )

    counters = run_prune([o1, o2], io=io, timestamp=_TS)

    assert o1.path.exists()
    assert not o2.path.exists()
    assert counters.pruned == 1


def test_three_way_one_by_one_quit_leaves_remaining(tmp_path: Path) -> None:
    """
    Given two orphans, "one-by-one", and a quit after answering only the first
    When run_prune executes
    Then the un-answered orphan is left in place (quit stops the loop).
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "a")
    o2 = _file_orphan(tmp_path, "claude", "skills", "b")
    io = ScriptedIO(
        three_ways=["o"],
        per_items=[PerItemResult(decisions={str(o1.path): True}, quit=True)],
    )

    counters = run_prune([o1, o2], io=io, timestamp=_TS)

    assert not o1.path.exists()
    assert o2.path.exists()
    assert counters.pruned == 1


def test_three_way_cancel_deletes_nothing(tmp_path: Path) -> None:
    """
    Given an orphan and an interactive answer of "cancel"
    When run_prune executes
    Then nothing is deleted and pruned == 0.
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "a")
    io = ScriptedIO(three_ways=["c"])

    counters = run_prune([o1], io=io, timestamp=_TS)

    assert o1.path.exists()
    assert counters.pruned == 0


def test_non_interactive_prune_only_without_auth_raises(tmp_path: Path) -> None:
    """
    Given a non-interactive session, prune_only, no auto_yes, no dry_run
    When run_prune executes
    Then it raises PruneAbortedError (intent unfulfilled: action with no auth).
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "a")
    io = ScriptedIO(interactive=False)

    with pytest.raises(PruneAbortedError):
        run_prune([o1], io=io, prune_only=True, timestamp=_TS)

    assert o1.path.exists()


def test_non_interactive_plain_prune_skips_without_deleting(tmp_path: Path) -> None:
    """
    Given a non-interactive session and plain prune (not prune_only), no auth
    When run_prune executes
    Then it returns having deleted nothing (warn + skip, not a hard fail).
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "a")
    io = ScriptedIO(interactive=False)

    counters = run_prune([o1], io=io, prune_only=False, timestamp=_TS)

    assert o1.path.exists()
    assert counters.pruned == 0


def test_auto_yes_deletes_all_without_prompting(tmp_path: Path) -> None:
    """
    Given auto_yes and an empty prompt queue
    When run_prune executes
    Then all orphans are deleted with no prompt popped (ScriptedIO not drained).
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "a")
    o2 = _file_orphan(tmp_path, "claude", "skills", "b")
    io = ScriptedIO(interactive=False)

    counters = run_prune([o1, o2], io=io, auto_yes=True, timestamp=_TS)

    assert not o1.path.exists()
    assert not o2.path.exists()
    assert counters.pruned == 2


def test_dry_run_displays_without_deleting(tmp_path: Path) -> None:
    """
    Given dry_run
    When run_prune executes
    Then nothing is deleted and pruned == 0 (no prompt is consulted).
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "a")
    io = ScriptedIO(interactive=False)

    counters = run_prune([o1], io=io, dry_run=True, timestamp=_TS)

    assert o1.path.exists()
    assert counters.pruned == 0


def test_empty_orphan_list_is_noop() -> None:
    """
    Given no orphans and a passing guard (interactive session)
    When run_prune executes
    Then it returns pruned == 0 without consulting any prompt.

    Note: the empty fast-path sits AFTER the non-interactive guard (bash
    ordering, scripts/install.sh:1603-1620), so this exercises the empty path
    only once the guard has been cleared — see
    test_non_interactive_prune_only_without_auth_raises for the guard-first case.
    """
    io = ScriptedIO(interactive=True)

    counters = run_prune([], io=io, prune_only=True, timestamp=_TS)

    assert counters.pruned == 0


def test_backup_precedes_delete_into_sibling_namespace_dir(tmp_path: Path) -> None:
    """
    Given a skills/ file orphan deleted under auto_yes
    When run_prune executes
    Then a recoverable copy survives in the sibling skills-backup/ directory
    and backed_up == 1.

    Pins the path-aware routing reuse: a scoped-namespace orphan's backup lands
    in <grandparent>/<namespace>-backup/, not in-place (scripts/install.sh:369).
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "retired", body="precious")
    io = ScriptedIO(interactive=False)

    counters = run_prune([o1], io=io, auto_yes=True, timestamp=_TS)

    backup = tmp_path / ".claude" / "skills-backup" / f"retired.backup-{_TS}"
    assert backup.read_text() == "precious"
    assert counters.backed_up == 1


def test_directory_orphan_backed_up_recursively(tmp_path: Path) -> None:
    """
    Given a skills/ directory orphan deleted under auto_yes
    When run_prune executes
    Then the backup is a recursive copy (inner file present) and the dir is gone.
    """
    o1 = _dir_orphan(tmp_path, "claude", "skills", "retired-dir")
    io = ScriptedIO(interactive=False)

    run_prune([o1], io=io, auto_yes=True, timestamp=_TS)

    backup_inner = tmp_path / ".claude" / "skills-backup" / f"retired-dir.backup-{_TS}" / "inner.md"
    assert backup_inner.read_text() == "inner"
    assert not o1.path.exists()


def test_malformed_timestamp_under_auto_yes_rejected_before_any_delete(tmp_path: Path) -> None:
    """
    Given a non-empty orphan list, auto_yes, and a timestamp that escapes the format
    When run_prune executes
    Then it raises ValueError and the orphan is untouched.

    Pins the guardrail on a *deleting* path: the timestamp is interpolated raw
    into the backup path, so a path-separator-bearing value must be rejected
    before any I/O. The raise now originates at the ``back_up`` boundary
    (safe-by-default), not from an explicit check in ``run_prune``.
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "a")
    io = ScriptedIO(interactive=False)

    with pytest.raises(ValueError, match="YYYYMMDD-HHMMSS"):
        run_prune([o1], io=io, auto_yes=True, timestamp="../evil")

    assert o1.path.exists()


def test_malformed_timestamp_under_dry_run_does_not_raise(tmp_path: Path) -> None:
    """
    Given a non-empty orphan list, dry_run, and a timestamp that escapes the format
    When run_prune executes
    Then it lists the orphan, returns empty Counters, and does NOT raise.

    Pins the dry-run skip: a dry-run performs no backup, so it must never resolve
    or validate a timestamp it will not use. A malformed value is irrelevant on
    this path (mirrors sync.py, which validates only on the actual-write path).
    """
    o1 = _file_orphan(tmp_path, "claude", "skills", "a")
    io = ScriptedIO(interactive=False)

    counters = run_prune([o1], io=io, dry_run=True, timestamp="../evil")

    assert o1.path.exists()
    assert counters.pruned == 0
    assert counters.backed_up == 0


def test_symlink_to_directory_orphan_unlinked_not_rmtree(tmp_path: Path) -> None:
    """
    Given a skills/ orphan that is a symlink pointing at a real directory
    When run_prune deletes it under auto_yes
    Then the link is removed via unlink, its target directory survives, and the
    flow completes without raising.

    Pins the symlink branch in ``_back_up_and_delete``: ``Path.is_dir()`` follows
    symlinks, so a dir-symlink would reach ``shutil.rmtree`` — which refuses a
    symlink and raises OSError. The ``is_symlink()`` guard routes it to
    ``unlink`` (deletes the link, not the target), matching the bash ``rm -rf``.
    """
    target_dir = tmp_path / "real-target"
    target_dir.mkdir()
    (target_dir / "keep.md").write_text("survives")

    ns_dir = tmp_path / ".claude" / "skills"
    ns_dir.mkdir(parents=True)
    link = ns_dir / "linked"
    link.symlink_to(target_dir, target_is_directory=True)
    orphan = Orphan(tool="claude", namespace="skills", path=link, kind="dir")

    io = ScriptedIO(interactive=False)

    counters = run_prune([orphan], io=io, auto_yes=True, timestamp=_TS)

    assert not link.exists()  # the symlink itself is gone
    assert not link.is_symlink()
    assert target_dir.is_dir()  # the link target is untouched
    assert (target_dir / "keep.md").read_text() == "survives"
    assert counters.pruned == 1

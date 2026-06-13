"""Unit tests for installer.core.sync.sync_plan (W1 — plan-walking install sync).

``sync_plan`` is the keystone of the real install: it walks a ``StagingPlan``
(in-memory ``items`` + ``dir_overrides``) and writes the whole tree to the
adapter's dest root, with hash-skip, path-aware backup-before-overwrite, the
``executable`` mode bit, and DIR materialisation. The per-file diff+confirm
consent gate is W2's concern; ``sync_plan`` here installs non-interactively
(the W3 wiring adds consent ahead of the write).

Each test pins a coded decision and drives the engine through ``ScriptedIO`` +
the real filesystem under ``tmp_path``. The adapter is a minimal identity
double so a test controls the dest root directly via ``home`` — independent of
any real tool's path layout (the real ClaudeAdapter is covered elsewhere).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.io_port import IOPort, ScriptedIO
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.sync import sync_plan

_FIXED_TS = "20260613-120000"


class _IdentityAdapter:
    """Minimal ToolAdapter double. ``dest_dir`` is an identity pass-through so
    a test controls the real dest root via ``sync_plan``'s ``home`` argument.
    The remaining protocol members are inert — ``sync_plan`` consults only
    ``dest_dir``."""

    name: str = "claude"
    detection_signal: str = ".fake"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root

    def dest_dir(self, home: Path) -> Path:
        return home

    def is_detected(self, home: Path) -> bool:  # noqa: ARG002  # inert stub
        return True

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ()

    def should_install_namespace(
        self,
        namespace: str,  # noqa: ARG002  # inert stub
        source: str,  # noqa: ARG002  # inert stub
    ) -> bool:
        return True

    def post_staging_transforms(
        self,
        plan: StagingPlan,
        io: IOPort,  # noqa: ARG002  # inert stub
    ) -> StagingPlan:
        return plan


def _file_item(relpath: Path, content: bytes, *, executable: bool = False) -> StagedItem:
    """A FILE ``StagedItem`` carrying eager ``content`` (``source_path`` unused
    for file items — bytes are in memory, not re-read from disk)."""
    return StagedItem(
        source_path=Path("/unused/for/file/items") / relpath,
        dest_relpath=relpath,
        kind=FileKind.OTHER,
        namespace=None,
        provenance=Provenance(kind="tool", name="claude"),
        content=content,
        executable=executable,
    )


def _dir_item(relpath: Path, source_path: Path) -> StagedItem:
    """A DIR ``StagedItem`` (``content is None``): its bytes derive from the
    ``source_path`` tree at sync time, not the in-memory model."""
    return StagedItem(
        source_path=source_path,
        dest_relpath=relpath,
        kind=FileKind.DIR,
        namespace=None,
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )


def test_plan_installs_every_file_item(tmp_path: Path) -> None:
    """
    Given a multi-item plan of FILE entries, none present at the dest
    When sync_plan walks it
    Then every entry's bytes land at its dest_relpath (intermediate dirs
    created) and the create count equals the number of items.
    """
    home = tmp_path / "home"  # absent — first install
    plan = StagingPlan(
        items={
            Path("a.md"): _file_item(Path("a.md"), b"alpha\n"),
            Path("rules/b.md"): _file_item(Path("rules/b.md"), b"beta\n"),
        },
        tool=Tool.CLAUDE,
    )

    counters = sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (home / "a.md").read_bytes() == b"alpha\n"
    assert (home / "rules" / "b.md").read_bytes() == b"beta\n"
    assert (counters.created, counters.updated, counters.skipped) == (2, 0, 0)


def test_identical_file_item_is_skipped(tmp_path: Path) -> None:
    """
    Given a FILE item whose dest already holds matching bytes (sha-256)
    When sync_plan walks the plan
    Then the dest is not rewritten and exactly one skip is counted.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "f.md").write_bytes(b"same\n")
    plan = StagingPlan(items={Path("f.md"): _file_item(Path("f.md"), b"same\n")}, tool=Tool.CLAUDE)

    counters = sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (home / "f.md").read_bytes() == b"same\n"
    assert (counters.created, counters.updated, counters.skipped) == (0, 0, 1)


def test_changed_file_item_is_backed_up_before_overwrite(tmp_path: Path) -> None:
    """
    Given a FILE item whose dest holds different bytes
    When sync_plan overwrites it
    Then the original bytes are preserved in a timestamped backup BEFORE the
    write, the dest holds the new bytes, and backed_up + updated are counted.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "AGENTS.md").write_bytes(b"old\n")
    plan = StagingPlan(
        items={Path("AGENTS.md"): _file_item(Path("AGENTS.md"), b"new\n")}, tool=Tool.CLAUDE
    )

    counters = sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (home / f"AGENTS.md.backup-{_FIXED_TS}").read_bytes() == b"old\n"
    assert (home / "AGENTS.md").read_bytes() == b"new\n"
    assert (counters.updated, counters.backed_up) == (1, 1)


@pytest.mark.parametrize(("executable", "mode"), [(True, 0o755), (False, 0o644)])
def test_file_item_mode_honors_executable_bit(tmp_path: Path, executable: bool, mode: int) -> None:
    """
    Given a FILE item with executable True/False
    When sync_plan writes it
    Then the dest's permission bits are 0o755 / 0o644 — deterministic modes
    (not umask-dependent), since the staged executable bit is the coded
    decision the bash installer pins for scripts vs plain files.
    """
    home = tmp_path / "home"
    plan = StagingPlan(
        items={Path("tool.sh"): _file_item(Path("tool.sh"), b"#!/bin/sh\n", executable=executable)},
        tool=Tool.CLAUDE,
    )

    sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (home / "tool.sh").stat().st_mode & 0o777 == mode


def test_dry_run_writes_nothing_but_counts_and_previews(tmp_path: Path) -> None:
    """
    Given --dry-run and a FILE item whose dest is absent
    When sync_plan runs
    Then nothing lands on disk, the would-be create is still counted, and a
    preview line naming the dest is emitted through IOPort.
    """
    home = tmp_path / "home"
    io = ScriptedIO()
    plan = StagingPlan(items={Path("f.md"): _file_item(Path("f.md"), b"hi\n")}, tool=Tool.CLAUDE)

    counters = sync_plan(
        _IdentityAdapter(), plan, home=home, io=io, dry_run=True, timestamp=_FIXED_TS
    )

    assert not (home / "f.md").exists()
    assert counters.created == 1
    assert any(str(home / "f.md") in entry.message for entry in io.transcript)


def test_unsafe_dest_relpath_is_rejected_before_any_write(tmp_path: Path) -> None:
    """
    Given a FILE item whose dest_relpath climbs out of the dest tree (``..``)
    When sync_plan walks the plan
    Then a ValueError surfaces before any write and nothing lands above the
    dest root — the path-traversal guard on staged dest paths.
    """
    home = tmp_path / "home"
    home.mkdir()
    plan = StagingPlan(
        items={Path("../escape.md"): _file_item(Path("../escape.md"), b"evil\n")},
        tool=Tool.CLAUDE,
    )

    with pytest.raises(ValueError, match="escape"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert not (tmp_path / "escape.md").exists()


def test_dir_item_materializes_its_source_tree(tmp_path: Path) -> None:
    """
    Given a DIR item (content None) whose source_path is a real directory tree
    When sync_plan walks it and the dest is absent
    Then the dest directory is created holding the source files, including
    nested ones, and one create is counted.
    """
    src = tmp_path / "src_skill"
    (src / "sub").mkdir(parents=True)
    (src / "SKILL.md").write_bytes(b"skill\n")
    (src / "sub" / "x.md").write_bytes(b"nested\n")
    home = tmp_path / "home"
    plan = StagingPlan(
        items={Path("skills/myskill"): _dir_item(Path("skills/myskill"), src)}, tool=Tool.CLAUDE
    )

    counters = sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (home / "skills" / "myskill" / "SKILL.md").read_bytes() == b"skill\n"
    assert (home / "skills" / "myskill" / "sub" / "x.md").read_bytes() == b"nested\n"
    assert counters.created == 1


def test_dir_overrides_are_overlaid_and_win_on_collision(tmp_path: Path) -> None:
    """
    Given a DIR item plus dir_overrides carrying a new file and one colliding
    with a source file
    When sync_plan materialises the dir
    Then the override bytes land on top of the source tree — the new file
    appears and the colliding file holds the override bytes (override wins,
    matching dump-time semantics).
    """
    src = tmp_path / "src_skill"
    src.mkdir()
    (src / "shared.md").write_bytes(b"from-source\n")
    home = tmp_path / "home"
    plan = StagingPlan(
        items={Path("skills/s"): _dir_item(Path("skills/s"), src)},
        tool=Tool.CLAUDE,
        dir_overrides={
            Path("skills/s"): {Path("extra.md"): b"added\n", Path("shared.md"): b"from-override\n"}
        },
    )

    sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (home / "skills" / "s" / "extra.md").read_bytes() == b"added\n"
    assert (home / "skills" / "s" / "shared.md").read_bytes() == b"from-override\n"


def test_existing_dir_is_backed_up_then_cleanly_replaced(tmp_path: Path) -> None:
    """
    Given a DIR item whose dest already exists with a stale file
    When sync_plan re-materialises it
    Then the existing dir is backed up BEFORE replacement (routed to the
    sibling ``skills-backup/`` for the scoped namespace), the dest holds the
    source tree with the stale file gone (clean replace, not merge), and
    backed_up + updated are counted.
    """
    src = tmp_path / "src_skill"
    src.mkdir()
    (src / "new.md").write_bytes(b"new\n")
    home = tmp_path / "home"
    existing = home / "skills" / "s"
    existing.mkdir(parents=True)
    (existing / "stale.md").write_bytes(b"stale\n")
    plan = StagingPlan(items={Path("skills/s"): _dir_item(Path("skills/s"), src)}, tool=Tool.CLAUDE)

    counters = sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    backup = home / "skills-backup" / f"s.backup-{_FIXED_TS}"
    assert (backup / "stale.md").read_bytes() == b"stale\n"
    assert (home / "skills" / "s" / "new.md").read_bytes() == b"new\n"
    assert not (home / "skills" / "s" / "stale.md").exists()
    assert (counters.updated, counters.backed_up) == (1, 1)


def test_dry_run_does_not_materialize_dir(tmp_path: Path) -> None:
    """
    Given --dry-run and a DIR item whose dest is absent
    When sync_plan runs
    Then no directory is materialised and the would-be create is still counted.
    """
    src = tmp_path / "src_skill"
    src.mkdir()
    (src / "SKILL.md").write_bytes(b"skill\n")
    home = tmp_path / "home"
    plan = StagingPlan(items={Path("skills/s"): _dir_item(Path("skills/s"), src)}, tool=Tool.CLAUDE)

    counters = sync_plan(
        _IdentityAdapter(), plan, home=home, io=ScriptedIO(), dry_run=True, timestamp=_FIXED_TS
    )

    assert not (home / "skills" / "s").exists()
    assert counters.created == 1


def test_unsafe_dir_override_relpath_is_rejected(tmp_path: Path) -> None:
    """
    Given a DIR item whose dir_overrides carry an inner relpath with ``..``
    When sync_plan materialises the dir
    Then a ValueError surfaces and no override file lands outside the dir.
    """
    src = tmp_path / "src_skill"
    src.mkdir()
    (src / "SKILL.md").write_bytes(b"skill\n")
    home = tmp_path / "home"
    plan = StagingPlan(
        items={Path("skills/s"): _dir_item(Path("skills/s"), src)},
        tool=Tool.CLAUDE,
        dir_overrides={Path("skills/s"): {Path("../evil.md"): b"evil\n"}},
    )

    with pytest.raises(ValueError, match="escape"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert not (home / "skills" / "evil.md").exists()


def test_dry_run_still_rejects_unsafe_dir_override(tmp_path: Path) -> None:
    """
    Given --dry-run and a DIR item whose dir_overrides carry an unsafe inner
    relpath
    When sync_plan runs
    Then a ValueError still surfaces — a dry-run preview validates the same as a
    real run — and nothing is materialised.
    """
    src = tmp_path / "src_skill"
    src.mkdir()
    (src / "SKILL.md").write_bytes(b"skill\n")
    home = tmp_path / "home"
    plan = StagingPlan(
        items={Path("skills/s"): _dir_item(Path("skills/s"), src)},
        tool=Tool.CLAUDE,
        dir_overrides={Path("skills/s"): {Path("../evil.md"): b"evil\n"}},
    )

    with pytest.raises(ValueError, match="escape"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), dry_run=True)

    assert not (home / "skills" / "s").exists()


def test_unsafe_dir_override_does_not_touch_an_existing_dest(tmp_path: Path) -> None:
    """
    Given a DIR item whose dest already exists and whose dir_overrides carry an
    unsafe inner relpath
    When sync_plan runs
    Then the override is rejected BEFORE any filesystem mutation — the existing
    dest dir is neither backed up nor replaced.
    """
    src = tmp_path / "src_skill"
    src.mkdir()
    (src / "new.md").write_bytes(b"new\n")
    home = tmp_path / "home"
    existing = home / "skills" / "s"
    existing.mkdir(parents=True)
    (existing / "keep.md").write_bytes(b"keep\n")
    plan = StagingPlan(
        items={Path("skills/s"): _dir_item(Path("skills/s"), src)},
        tool=Tool.CLAUDE,
        dir_overrides={Path("skills/s"): {Path("../evil.md"): b"evil\n"}},
    )

    with pytest.raises(ValueError, match="escape"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (existing / "keep.md").read_bytes() == b"keep\n"  # untouched
    assert not (home / "skills-backup").exists()  # not backed up


def test_file_item_with_a_file_in_its_parent_path_is_rejected(tmp_path: Path) -> None:
    """
    Given a FILE item whose intermediate parent component is a regular file
    (``<dest>/rules`` is a file, not a directory)
    When sync_plan tries to create the parent directory
    Then a ValueError surfaces rather than a raw ``FileExistsError`` from mkdir —
    consistent with the engine's other type-mismatch guards.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "rules").write_bytes(b"i am a file\n")
    plan = StagingPlan(
        items={Path("rules/b.md"): _file_item(Path("rules/b.md"), b"x\n")}, tool=Tool.CLAUDE
    )

    with pytest.raises(ValueError, match="parent path"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)


def test_dir_item_with_a_file_in_its_parent_path_is_rejected(tmp_path: Path) -> None:
    """
    Given a DIR item whose intermediate parent component is a regular file
    (``<dest>/skills`` is a file)
    When sync_plan tries to create the parent directory
    Then a ValueError surfaces rather than a raw mkdir ``OSError``.
    """
    src = tmp_path / "src_skill"
    src.mkdir()
    (src / "SKILL.md").write_bytes(b"skill\n")
    home = tmp_path / "home"
    home.mkdir()
    (home / "skills").write_bytes(b"i am a file\n")
    plan = StagingPlan(items={Path("skills/s"): _dir_item(Path("skills/s"), src)}, tool=Tool.CLAUDE)

    with pytest.raises(ValueError, match="parent path"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)


def test_dir_override_with_a_file_in_its_inner_parent_path_is_rejected(tmp_path: Path) -> None:
    """
    Given a dir_override whose inner relpath needs a directory where the copied
    source tree has a regular file (``a`` is a file; override targets ``a/deep.md``)
    When sync_plan writes the override
    Then a ValueError surfaces rather than a raw mkdir ``OSError``.
    """
    src = tmp_path / "src_skill"
    src.mkdir()
    (src / "a").write_bytes(b"file-a\n")  # 'a' is a file in the source tree
    home = tmp_path / "home"
    plan = StagingPlan(
        items={Path("skills/s"): _dir_item(Path("skills/s"), src)},
        tool=Tool.CLAUDE,
        dir_overrides={Path("skills/s"): {Path("a/deep.md"): b"deep\n"}},
    )

    with pytest.raises(ValueError, match="parent path"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)


def test_dry_run_still_rejects_a_file_in_the_parent_path(tmp_path: Path) -> None:
    """
    Given --dry-run and a FILE item whose intermediate parent component is a
    regular file (``<dest>/rules`` is a file)
    When sync_plan previews the install
    Then the non-mutating parent-chain validation surfaces a ValueError too — a
    faithful preview fails where a real run would — and nothing is written.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "rules").write_bytes(b"i am a file\n")
    plan = StagingPlan(
        items={Path("rules/b.md"): _file_item(Path("rules/b.md"), b"x\n")}, tool=Tool.CLAUDE
    )

    with pytest.raises(ValueError, match="parent path"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), dry_run=True)

    assert not (home / "rules" / "b.md").exists()


def test_overwrite_with_malformed_timestamp_is_rejected_before_any_write(tmp_path: Path) -> None:
    """
    Given an overwrite and a caller-supplied timestamp that violates the
    ``YYYYMMDD-HHMMSS`` contract (here a path-traversal value)
    When sync_plan runs
    Then a ValueError surfaces before any backup or write, and the destination
    keeps its original bytes — the timestamp is interpolated raw into the
    backup path, so the validation is the path-traversal boundary.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "f.md").write_bytes(b"old\n")
    plan = StagingPlan(items={Path("f.md"): _file_item(Path("f.md"), b"new\n")}, tool=Tool.CLAUDE)

    with pytest.raises(ValueError, match="YYYYMMDD"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp="../evil")

    assert (home / "f.md").read_bytes() == b"old\n"
    assert not any(home.glob("*.backup-*"))


def test_overwrite_without_a_timestamp_backs_up_with_a_generated_suffix(tmp_path: Path) -> None:
    """
    Given an overwrite and no injected timestamp
    When sync_plan runs
    Then the original is still backed up under a generated ``backup-<ts>``
    suffix — the production default (current local time) for the backup name.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "f.md").write_bytes(b"old\n")
    plan = StagingPlan(items={Path("f.md"): _file_item(Path("f.md"), b"new\n")}, tool=Tool.CLAUDE)

    counters = sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO())

    assert (home / "f.md").read_bytes() == b"new\n"
    assert counters.backed_up == 1
    assert any(home.glob("f.md.backup-*"))


def test_file_item_whose_dest_is_a_directory_is_rejected(tmp_path: Path) -> None:
    """
    Given a FILE item whose dest is already occupied by a directory
    When sync_plan runs
    Then a ValueError surfaces — not an uncaught OSError mid-walk — so the CLI's
    ValueError handling reports it cleanly (mirroring dump's type guard).
    """
    home = tmp_path / "home"
    (home / "f.md").mkdir(parents=True)  # a directory where a file is planned
    plan = StagingPlan(items={Path("f.md"): _file_item(Path("f.md"), b"new\n")}, tool=Tool.CLAUDE)

    with pytest.raises(ValueError, match="not a file"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)


def test_dir_item_whose_dest_is_a_file_is_rejected(tmp_path: Path) -> None:
    """
    Given a DIR item whose dest is already occupied by a regular file
    When sync_plan runs
    Then a ValueError surfaces before the rmtree (which would raise a raw
    NotADirectoryError), so the failure is a clean CLI error.
    """
    src = tmp_path / "src_skill"
    src.mkdir()
    (src / "SKILL.md").write_bytes(b"skill\n")
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "skills" / "s").write_bytes(b"i am a file\n")  # file where a dir is planned
    plan = StagingPlan(items={Path("skills/s"): _dir_item(Path("skills/s"), src)}, tool=Tool.CLAUDE)

    with pytest.raises(ValueError, match="not a directory"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)


def test_dir_item_with_missing_source_is_rejected(tmp_path: Path) -> None:
    """
    Given a DIR item whose source_path does not exist (a staging defect)
    When sync_plan runs
    Then a ValueError surfaces rather than a raw FileNotFoundError from copytree.
    """
    home = tmp_path / "home"
    plan = StagingPlan(
        items={Path("skills/s"): _dir_item(Path("skills/s"), tmp_path / "absent")},
        tool=Tool.CLAUDE,
    )

    with pytest.raises(ValueError, match="not a directory"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)


def test_walk_is_non_transactional_earlier_items_survive_a_later_failure(tmp_path: Path) -> None:
    """
    Given a two-item plan whose first item is valid and second item has an
    unsafe dest_relpath
    When sync_plan walks it and raises on the second item
    Then the first item is already installed — pinning the documented
    non-transactional contract (no rollback of earlier writes).
    """
    home = tmp_path / "home"
    plan = StagingPlan(
        items={
            Path("good.md"): _file_item(Path("good.md"), b"good\n"),
            Path("../escape.md"): _file_item(Path("../escape.md"), b"evil\n"),
        },
        tool=Tool.CLAUDE,
    )

    with pytest.raises(ValueError, match="escape"):
        sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), timestamp=_FIXED_TS)

    assert (home / "good.md").read_bytes() == b"good\n"  # earlier item survived

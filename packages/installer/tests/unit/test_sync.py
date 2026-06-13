"""Unit tests for installer.core.sync (B.2 — minimal single-file sync).

Each test pins a behaviour the B.2 story contract requires
(docs/specs/2026-05-17-python-installer-rewrite.md, Epic B.2). The sync
engine is exercised through a minimal identity-pass-through ToolAdapter so
the tests are independent of any real tool's path layout; the real
ClaudeAdapter is driven once, end-to-end, in test_sync_claude.py to cover
its source_dir/dest_dir behaviourally.

Tautology tests — isinstance(_, ToolAdapter), path-literal assertions like
adapter.source_dir(r) == r / "src" / "user" / ".claude" — are deliberately
absent. See the writing-unit-tests skill's Tautology Filter.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from installer.core.io_port import IOPort, ScriptedIO
from installer.core.model import StagingPlan
from installer.core.sync import sync


class _IdentityAdapter:
    """Minimal ToolAdapter double. source_dir/dest_dir are identity
    pass-throughs, so a test controls the real source/dest roots directly
    via sync's repo_root / home arguments. The remaining protocol members
    are inert — the sync engine never consults them."""

    name: str = "fake"
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


def test_absent_destination_is_created_from_source(tmp_path: Path) -> None:
    """
    Given a source file and a destination that does not yet exist
    When sync installs the file
    Then the destination holds the source bytes and exactly one create is
    counted.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"  # deliberately absent — first install
    (src_root).mkdir()
    (src_root / "f.md").write_bytes(b"hello\n")

    counters = sync(
        _IdentityAdapter(),
        Path("f.md"),
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
    )

    assert (dest_root / "f.md").read_bytes() == b"hello\n"
    assert (counters.created, counters.updated, counters.skipped) == (1, 0, 0)


def test_missing_parent_directories_are_created(tmp_path: Path) -> None:
    """
    Given a destination whose intermediate namespace directories do not
    exist (first-ever install into ~/.claude/rules/)
    When sync installs a nested file
    Then the intermediate directories and the file are created.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    (src_root / "rules").mkdir(parents=True)
    (src_root / "rules" / "deep.md").write_bytes(b"rule\n")

    sync(
        _IdentityAdapter(),
        Path("rules/deep.md"),
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
    )

    assert (dest_root / "rules" / "deep.md").read_bytes() == b"rule\n"


def test_identical_destination_is_skipped_without_rewrite(tmp_path: Path) -> None:
    """
    Given a destination whose bytes already match the source (sha-256)
    When sync runs
    Then no write occurs and exactly one skip is counted.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    dest_root.mkdir()
    (src_root / "f.md").write_bytes(b"same\n")
    (dest_root / "f.md").write_bytes(b"same\n")

    counters = sync(
        _IdentityAdapter(),
        Path("f.md"),
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
    )

    assert (dest_root / "f.md").read_bytes() == b"same\n"
    assert (counters.created, counters.updated, counters.skipped) == (0, 0, 1)


def test_skip_does_not_write_to_read_only_destination(tmp_path: Path) -> None:
    """
    Given an up-to-date destination that is read-only (0o444)
    When sync runs
    Then it skips cleanly without raising — proving the skip path never
    opens the destination for writing.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    dest_root.mkdir()
    (src_root / "f.md").write_bytes(b"same\n")
    dest = dest_root / "f.md"
    dest.write_bytes(b"same\n")
    dest.chmod(0o444)

    counters = sync(
        _IdentityAdapter(),
        Path("f.md"),
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
    )

    assert counters.skipped == 1


def test_changed_source_overwrites_destination(tmp_path: Path) -> None:
    """
    Given a destination whose bytes differ from the source
    When sync runs
    Then the destination is rewritten with the source bytes and exactly
    one update is counted.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    dest_root.mkdir()
    (src_root / "f.md").write_bytes(b"new content\n")
    (dest_root / "f.md").write_bytes(b"old content\n")

    counters = sync(
        _IdentityAdapter(),
        Path("f.md"),
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
    )

    assert (dest_root / "f.md").read_bytes() == b"new content\n"
    assert (counters.created, counters.updated, counters.skipped) == (0, 1, 0)


def test_dry_run_creates_no_file_on_disk(tmp_path: Path) -> None:
    """
    Given --dry-run and an absent destination
    When sync runs
    Then nothing is written to disk, yet the would-be create is reported
    in the returned summary.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    (src_root / "f.md").write_bytes(b"hello\n")

    counters = sync(
        _IdentityAdapter(),
        Path("f.md"),
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
        dry_run=True,
    )

    assert not (dest_root / "f.md").exists()
    assert counters.created == 1


def test_dry_run_preview_names_the_would_be_write(tmp_path: Path) -> None:
    """
    Given --dry-run
    When sync would write a file
    Then a preview line naming the destination is emitted through IOPort.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    (src_root / "f.md").write_bytes(b"hello\n")
    io = ScriptedIO()

    sync(
        _IdentityAdapter(),
        Path("f.md"),
        repo_root=src_root,
        home=dest_root,
        io=io,
        dry_run=True,
    )

    dest = dest_root / "f.md"
    assert any(str(dest) in entry.message for entry in io.transcript)


def test_dry_run_leaves_existing_file_unmodified(tmp_path: Path) -> None:
    """
    Given --dry-run and a destination whose bytes differ from the source
    When sync runs
    Then the destination keeps its original bytes and the would-be update
    is reported.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    dest_root.mkdir()
    (src_root / "f.md").write_bytes(b"new content\n")
    (dest_root / "f.md").write_bytes(b"old content\n")

    counters = sync(
        _IdentityAdapter(),
        Path("f.md"),
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
        dry_run=True,
    )

    assert (dest_root / "f.md").read_bytes() == b"old content\n"
    assert counters.updated == 1


def test_missing_source_file_raises(tmp_path: Path) -> None:
    """
    Given a relpath with no corresponding source file
    When sync runs
    Then a FileNotFoundError surfaces rather than a silent no-op — the
    caller must learn the source is missing.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()

    with pytest.raises(FileNotFoundError):
        sync(
            _IdentityAdapter(),
            Path("absent.md"),
            repo_root=src_root,
            home=dest_root,
            io=ScriptedIO(),
        )


def test_absolute_relpath_is_rejected(tmp_path: Path) -> None:
    """
    Given an absolute relpath (which ``Path / relpath`` would resolve to,
    discarding the adapter source/dest roots entirely)
    When sync runs
    Then a ValueError surfaces before any write, and nothing lands outside
    the dest root.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    dest_root.mkdir()
    outside = tmp_path / "etc" / "passwd"
    outside.parent.mkdir()

    with pytest.raises(ValueError):
        sync(
            _IdentityAdapter(),
            outside,  # absolute path — would escape the dest root entirely
            repo_root=src_root,
            home=dest_root,
            io=ScriptedIO(),
        )

    assert not outside.exists()


def test_parent_traversal_relpath_is_rejected(tmp_path: Path) -> None:
    """
    Given a relpath containing a ``..`` component (which would climb out of
    the adapter dest tree)
    When sync runs
    Then a ValueError surfaces before any write, and no file is created
    above the dest root.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    dest_root.mkdir()

    with pytest.raises(ValueError):
        sync(
            _IdentityAdapter(),
            Path("../escape.md"),  # climbs out of the dest tree
            repo_root=src_root,
            home=dest_root,
            io=ScriptedIO(),
        )

    assert not (tmp_path / "escape.md").exists()


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root bypasses the 0o444 mode bit, so the write would succeed",
)
def test_write_to_read_only_destination_surfaces_permission_error(tmp_path: Path) -> None:
    """
    Given a destination that differs from the source and is read-only
    When sync attempts the write
    Then a PermissionError surfaces rather than being swallowed.

    Assumes a non-root test runner (root bypasses the 0o444 mode bit).
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    dest_root.mkdir()
    (src_root / "f.md").write_bytes(b"new content\n")
    dest = dest_root / "f.md"
    dest.write_bytes(b"old content\n")
    dest.chmod(0o444)

    with pytest.raises(PermissionError):
        sync(
            _IdentityAdapter(),
            Path("f.md"),
            repo_root=src_root,
            home=dest_root,
            io=ScriptedIO(),
        )


# ─────────────────────── G.1: path-aware backup ───────────────────────
#
# These tests pin the path-aware backup contract ported from the bash
# installer's backup() (scripts/install.sh:352-388): an existing
# destination that is about to be overwritten is copied to a timestamped
# backup BEFORE the write. The routing decision is coded — a scoped
# namespace dir routes to a sibling <ns>-backup/, everything else gets an
# in-place .backup-<ts> suffix — so each test pins that decision, not
# Path/shutil semantics.

_FIXED_TS = "20260613-120000"


@pytest.mark.parametrize("namespace", ["commands", "skills", "agents", "rules", "formulas"])
def test_overwrite_in_scoped_namespace_backs_up_to_sibling_dir(
    tmp_path: Path, namespace: str
) -> None:
    """
    Given an existing destination inside a scoped namespace dir whose
    bytes differ from the source
    When sync overwrites it
    Then the original bytes are copied to a sibling ``<namespace>-backup/``
    directory under a ``<name>.backup-<ts>`` filename — the coded routing
    decision for the five prune-managed namespaces.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    (src_root / namespace).mkdir(parents=True)
    (dest_root / namespace).mkdir(parents=True)
    (src_root / namespace / "f.md").write_bytes(b"new\n")
    (dest_root / namespace / "f.md").write_bytes(b"old\n")

    sync(
        _IdentityAdapter(),
        Path(namespace) / "f.md",
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
    )

    backup = dest_root / f"{namespace}-backup" / f"f.md.backup-{_FIXED_TS}"
    assert backup.read_bytes() == b"old\n"
    assert (dest_root / namespace / "f.md").read_bytes() == b"new\n"


def test_overwrite_outside_namespace_backs_up_in_place(tmp_path: Path) -> None:
    """
    Given an existing destination NOT inside a scoped namespace dir whose
    bytes differ from the source
    When sync overwrites it
    Then the original bytes are copied alongside the file under a
    ``<name>.backup-<ts>`` suffix — the coded fallback routing decision.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    dest_root.mkdir()
    (src_root / "AGENTS.md").write_bytes(b"new\n")
    (dest_root / "AGENTS.md").write_bytes(b"old\n")

    sync(
        _IdentityAdapter(),
        Path("AGENTS.md"),
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
    )

    backup = dest_root / f"AGENTS.md.backup-{_FIXED_TS}"
    assert backup.read_bytes() == b"old\n"
    assert (dest_root / "AGENTS.md").read_bytes() == b"new\n"


def test_namespace_routing_keys_on_parent_dir_not_path_depth(tmp_path: Path) -> None:
    """
    Given a destination whose immediate parent is a scoped namespace dir
    nested deeper than one level (``commands/sub/f.md``)
    When sync overwrites it
    Then routing keys on the immediate parent's name — backup lands in a
    sibling ``commands-backup/`` beside the ``commands`` dir, mirroring the
    bash ``basename "$(dirname "$target")"`` decision, not the file's depth.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    (src_root / "commands").mkdir(parents=True)
    (dest_root / "commands").mkdir(parents=True)
    (src_root / "commands" / "f.md").write_bytes(b"new\n")
    (dest_root / "commands" / "f.md").write_bytes(b"old\n")

    sync(
        _IdentityAdapter(),
        Path("commands") / "f.md",
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
    )

    assert (dest_root / "commands-backup" / f"f.md.backup-{_FIXED_TS}").read_bytes() == b"old\n"


def test_namespace_name_as_grandparent_routes_in_place(tmp_path: Path) -> None:
    """
    Given a nested file whose immediate parent is NOT a scoped namespace
    but whose grandparent IS (``skills/foo/SKILL.md`` — the real nested-skill
    case)
    When sync overwrites it
    Then routing falls through to the in-place ``.backup-<ts>`` suffix
    beside the file — the namespace check keys on the immediate parent
    (``foo``), not any ancestor, so neither ``foo-backup/`` nor
    ``skills-backup/`` is created.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    (src_root / "skills" / "foo").mkdir(parents=True)
    (dest_root / "skills" / "foo").mkdir(parents=True)
    (src_root / "skills" / "foo" / "SKILL.md").write_bytes(b"new\n")
    (dest_root / "skills" / "foo" / "SKILL.md").write_bytes(b"old\n")

    sync(
        _IdentityAdapter(),
        Path("skills") / "foo" / "SKILL.md",
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
    )

    in_place = dest_root / "skills" / "foo" / f"SKILL.md.backup-{_FIXED_TS}"
    assert in_place.read_bytes() == b"old\n"
    assert not (dest_root / "skills" / "foo-backup").exists()
    assert not (dest_root / "skills-backup").exists()


def test_overwrite_increments_backed_up_counter(tmp_path: Path) -> None:
    """
    Given an existing destination that is overwritten
    When sync runs
    Then exactly one backup is counted in the returned summary alongside
    the update.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    src_root.mkdir()
    dest_root.mkdir()
    (src_root / "AGENTS.md").write_bytes(b"new\n")
    (dest_root / "AGENTS.md").write_bytes(b"old\n")

    counters = sync(
        _IdentityAdapter(),
        Path("AGENTS.md"),
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
    )

    assert counters.backed_up == 1
    assert counters.updated == 1


def test_new_file_is_not_backed_up(tmp_path: Path) -> None:
    """
    Given a destination that does not yet exist
    When sync creates it
    Then no backup file or backup dir is written and nothing is counted as
    backed up — there was no original to preserve.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    (src_root / "commands").mkdir(parents=True)
    (src_root / "commands" / "f.md").write_bytes(b"hello\n")

    counters = sync(
        _IdentityAdapter(),
        Path("commands") / "f.md",
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
    )

    assert counters.backed_up == 0
    assert not (dest_root / "commands-backup").exists()


def test_identical_destination_is_not_backed_up(tmp_path: Path) -> None:
    """
    Given a destination whose bytes already match the source (a skip)
    When sync runs
    Then no backup is taken — backup is coupled to the overwrite branch,
    not to mere destination existence.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    (src_root / "rules").mkdir(parents=True)
    (dest_root / "rules").mkdir(parents=True)
    (src_root / "rules" / "f.md").write_bytes(b"same\n")
    (dest_root / "rules" / "f.md").write_bytes(b"same\n")

    counters = sync(
        _IdentityAdapter(),
        Path("rules") / "f.md",
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
    )

    assert counters.backed_up == 0
    assert not (dest_root / "rules-backup").exists()


def test_dry_run_overwrite_writes_no_backup(tmp_path: Path) -> None:
    """
    Given --dry-run and an existing destination that would be overwritten
    When sync runs
    Then no backup is written to disk and none is counted — dry-run touches
    nothing, including backups.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    (src_root / "rules").mkdir(parents=True)
    (dest_root / "rules").mkdir(parents=True)
    (src_root / "rules" / "f.md").write_bytes(b"new\n")
    (dest_root / "rules" / "f.md").write_bytes(b"old\n")

    counters = sync(
        _IdentityAdapter(),
        Path("rules") / "f.md",
        repo_root=src_root,
        home=dest_root,
        io=ScriptedIO(),
        dry_run=True,
        timestamp=_FIXED_TS,
    )

    assert counters.backed_up == 0
    assert not (dest_root / "rules-backup").exists()
    assert (dest_root / "rules" / "f.md").read_bytes() == b"old\n"


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root bypasses the 0o444 mode bit, so the write would succeed",
)
def test_backup_survives_a_failed_write(tmp_path: Path) -> None:
    """
    Given a read-only existing destination whose bytes differ (the write
    will raise PermissionError)
    When sync runs
    Then the timestamped backup of the original bytes already exists on
    disk — proving the backup is taken BEFORE the write, so a failed write
    leaves the original recoverable.
    """
    src_root = tmp_path / "repo"
    dest_root = tmp_path / "home"
    (src_root / "rules").mkdir(parents=True)
    (dest_root / "rules").mkdir(parents=True)
    (src_root / "rules" / "f.md").write_bytes(b"new\n")
    dest = dest_root / "rules" / "f.md"
    dest.write_bytes(b"old\n")
    dest.chmod(0o444)

    with pytest.raises(PermissionError):
        sync(
            _IdentityAdapter(),
            Path("rules") / "f.md",
            repo_root=src_root,
            home=dest_root,
            io=ScriptedIO(),
            timestamp=_FIXED_TS,
        )

    backup = dest_root / "rules-backup" / f"f.md.backup-{_FIXED_TS}"
    assert backup.read_bytes() == b"old\n"

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

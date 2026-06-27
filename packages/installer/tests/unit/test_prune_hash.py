import hashlib
from pathlib import Path

import pytest

from installer.core.model import Orphan
from installer.core.prune_hash import partition_file_orphans


def test_file_orphan_matching_sha_is_pruned(tmp_path: Path) -> None:
    f = tmp_path / ".beads" / "formulas" / "x.toml"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"hi")
    sha = hashlib.sha256(b"hi").hexdigest()
    o = Orphan(tool="beads", namespace="formulas", path=f, kind="file")
    to_prune, relinquished = partition_file_orphans(
        [o], home=tmp_path, recorded_sha_by_path={Path(".beads/formulas/x.toml"): sha}
    )
    assert to_prune == [o]
    assert relinquished == set()


def test_file_orphan_mismatched_sha_is_relinquished(tmp_path: Path) -> None:
    f = tmp_path / ".beads" / "formulas" / "x.toml"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"user-modified")
    o = Orphan(tool="beads", namespace="formulas", path=f, kind="file")
    to_prune, relinquished = partition_file_orphans(
        [o], home=tmp_path, recorded_sha_by_path={Path(".beads/formulas/x.toml"): "stale-sha"}
    )
    assert to_prune == []
    assert relinquished == {Path(".beads/formulas/x.toml")}


def test_file_orphan_absent_on_disk_falls_through_to_prune(tmp_path: Path) -> None:
    """A recorded FILE orphan whose on-disk path was never created lands in
    to_prune via the OSError fallthrough — read_bytes raises FileNotFoundError,
    and a vanished file's delete is a harmless no-op, never a relinquish.

    Pins: the hash-compare's read failure is treated as "prune", not "keep".
    """
    missing = tmp_path / ".beads" / "formulas" / "gone.toml"  # never created
    o = Orphan(tool="beads", namespace="formulas", path=missing, kind="file")
    to_prune, relinquished = partition_file_orphans(
        [o],
        home=tmp_path,
        recorded_sha_by_path={Path(".beads/formulas/gone.toml"): "some-sha"},
    )
    assert to_prune == [o]
    assert relinquished == set()


def test_file_orphan_now_a_directory_is_relinquished(tmp_path: Path) -> None:
    """A recorded FILE orphan whose on-disk path is now a DIRECTORY (the user
    replaced our file with their own dir) is relinquished, never pruned: read_bytes
    raises IsADirectoryError, and the downstream prune would ``rmtree`` the user's
    directory. Pins the fail-closed split — only FileNotFoundError prunes; every
    other OSError keeps the path and drops it from the receipt.
    """
    p = tmp_path / ".beads" / "formulas" / "x.toml"  # recorded as a FILE
    p.mkdir(parents=True)  # but a directory now occupies the path
    (p / "user-file.txt").write_bytes(b"user content")
    o = Orphan(tool="beads", namespace="formulas", path=p, kind="file")
    to_prune, relinquished = partition_file_orphans(
        [o], home=tmp_path, recorded_sha_by_path={Path(".beads/formulas/x.toml"): "some-sha"}
    )
    assert to_prune == []
    assert relinquished == {Path(".beads/formulas/x.toml")}


def test_file_orphan_unreadable_oserror_is_relinquished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded FILE orphan that is present but unreadable (permission / transient
    FS error → a non-FileNotFound OSError) is relinquished, not pruned. We cannot
    confirm the bytes are ours, so we fail closed rather than delete blind. Pins the
    branch as generic-OSError, not narrowly IsADirectoryError.
    """
    f = tmp_path / ".beads" / "formulas" / "x.toml"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"hi")

    def boom(_self: Path) -> bytes:  # matches Path.read_bytes
        raise PermissionError

    monkeypatch.setattr(Path, "read_bytes", boom)
    o = Orphan(tool="beads", namespace="formulas", path=f, kind="file")
    to_prune, relinquished = partition_file_orphans(
        [o], home=tmp_path, recorded_sha_by_path={Path(".beads/formulas/x.toml"): "sha"}
    )
    assert to_prune == []
    assert relinquished == {Path(".beads/formulas/x.toml")}


def test_dir_orphan_still_a_directory_is_pruned(tmp_path: Path) -> None:
    d = tmp_path / ".claude" / "skills" / "foo"
    d.mkdir(parents=True)
    o = Orphan(tool="claude", namespace="skills", path=d, kind="dir")
    to_prune, relinquished = partition_file_orphans([o], home=tmp_path, recorded_sha_by_path={})
    assert to_prune == [o]
    assert relinquished == set()


def test_dir_orphan_now_a_file_is_relinquished(tmp_path: Path) -> None:
    """A recorded DIR orphan whose on-disk path is now a regular FILE (the user
    replaced our directory with their own file) is relinquished, not pruned — the
    delete would unlink the user's file. Cheap type-drift guard; distinct from the
    deferred recursive content-drift case (a path that is still a directory).
    """
    p = tmp_path / ".claude" / "skills" / "foo"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"user replaced our dir with a file")
    o = Orphan(tool="claude", namespace="skills", path=p, kind="dir")
    to_prune, relinquished = partition_file_orphans([o], home=tmp_path, recorded_sha_by_path={})
    assert to_prune == []
    assert relinquished == {Path(".claude/skills/foo")}


def test_dir_orphan_now_a_symlink_is_relinquished(tmp_path: Path) -> None:
    """A recorded DIR orphan whose on-disk path is now a SYMLINK is relinquished:
    the user pointed the path elsewhere; pruning would remove their link. is_symlink
    is tested before is_dir so a dir-symlink never counts as a real directory to
    rmtree.
    """
    target = tmp_path / "elsewhere"
    target.mkdir()
    p = tmp_path / ".claude" / "skills" / "foo"
    p.parent.mkdir(parents=True)
    p.symlink_to(target, target_is_directory=True)
    o = Orphan(tool="claude", namespace="skills", path=p, kind="dir")
    to_prune, relinquished = partition_file_orphans([o], home=tmp_path, recorded_sha_by_path={})
    assert to_prune == []
    assert relinquished == {Path(".claude/skills/foo")}


def test_dir_orphan_matching_digest_is_pruned(tmp_path: Path) -> None:
    """A recorded DIR orphan whose live recursive digest still matches the owned
    state is prunable — it is genuinely our pristine directory."""
    from installer.core.prune_hash import is_safe_to_prune
    from installer.core.receipt import dir_content_digest

    d = tmp_path / ".claude" / "skills" / "foo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("owned")
    digest = dir_content_digest(d)
    o = Orphan(tool="claude", namespace="skills", path=d, kind="dir")
    assert is_safe_to_prune(
        o,
        home=tmp_path,
        recorded_sha_by_path={},
        recorded_digest_by_path={Path(".claude/skills/foo"): digest},
    )


def test_dir_orphan_content_drift_is_relinquished(tmp_path: Path) -> None:
    """A still-real DIR orphan whose inner contents drifted from the recorded digest
    (the user edited a file inside) is relinquished, not pruned — recursive
    content-drift protection beyond the cheap type-check."""
    from installer.core.receipt import dir_content_digest

    d = tmp_path / ".claude" / "skills" / "foo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("owned")
    digest = dir_content_digest(d)
    (d / "SKILL.md").write_text("user edited this")
    o = Orphan(tool="claude", namespace="skills", path=d, kind="dir")
    to_prune, relinquished = partition_file_orphans(
        [o],
        home=tmp_path,
        recorded_sha_by_path={},
        recorded_digest_by_path={Path(".claude/skills/foo"): digest},
    )
    assert to_prune == []
    assert relinquished == {Path(".claude/skills/foo")}


def test_dir_orphan_legacy_no_digest_falls_back_to_type_check(tmp_path: Path) -> None:
    """A legacy DIR entry recorded before digests existed (digest is None) keeps the
    pre-feature behavior: prunable while still a real directory, regardless of
    contents."""
    d = tmp_path / ".claude" / "skills" / "foo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("anything")
    o = Orphan(tool="claude", namespace="skills", path=d, kind="dir")
    to_prune, relinquished = partition_file_orphans(
        [o],
        home=tmp_path,
        recorded_sha_by_path={},
        recorded_digest_by_path={Path(".claude/skills/foo"): None},
    )
    assert to_prune == [o]
    assert relinquished == set()


def test_dir_orphan_unreadable_inner_file_is_relinquished(tmp_path: Path) -> None:
    """An OSError while recomputing the digest (an inner file became unreadable)
    relinquishes — ownership cannot be confirmed, so the directory is left intact."""
    import installer.core.prune_hash as prune_hash

    d = tmp_path / ".claude" / "skills" / "foo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("owned")
    o = Orphan(tool="claude", namespace="skills", path=d, kind="dir")

    def boom(_path: Path) -> str:
        raise OSError

    original = prune_hash.dir_content_digest
    prune_hash.dir_content_digest = boom  # type: ignore[assignment]
    try:
        to_prune, relinquished = partition_file_orphans(
            [o],
            home=tmp_path,
            recorded_sha_by_path={},
            recorded_digest_by_path={Path(".claude/skills/foo"): "sha256:recorded"},
        )
    finally:
        prune_hash.dir_content_digest = original  # type: ignore[assignment]
    assert to_prune == []
    assert relinquished == {Path(".claude/skills/foo")}


def test_dir_orphan_absent_on_disk_falls_through_to_prune(tmp_path: Path) -> None:
    """A recorded DIR orphan whose path has already vanished is prunable: the delete
    is a no-op, and there are no contents to drift from the recorded digest."""
    missing = tmp_path / ".claude" / "skills" / "gone"
    o = Orphan(tool="claude", namespace="skills", path=missing, kind="dir")
    to_prune, relinquished = partition_file_orphans(
        [o],
        home=tmp_path,
        recorded_sha_by_path={},
        recorded_digest_by_path={Path(".claude/skills/gone"): "sha256:recorded"},
    )
    assert to_prune == [o]
    assert relinquished == set()

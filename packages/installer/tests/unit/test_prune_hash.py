import hashlib
from pathlib import Path

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


def test_dir_orphan_always_pruned(tmp_path: Path) -> None:
    d = tmp_path / ".claude" / "skills" / "foo"
    d.mkdir(parents=True)
    o = Orphan(tool="claude", namespace="skills", path=d, kind="dir")
    to_prune, relinquished = partition_file_orphans([o], home=tmp_path, recorded_sha_by_path={})
    assert to_prune == [o]
    assert relinquished == set()

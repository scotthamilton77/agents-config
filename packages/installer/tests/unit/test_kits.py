from pathlib import Path

from installer.core.kits import StagedKitRef, kit_name_of, kit_universe, stage_kits


def _seed(root: Path) -> Path:
    kits = root / "kits"
    (kits / "beads" / ".beads").mkdir(parents=True)
    (kits / "beads" / ".beads" / "PRIME.md").write_bytes(b"beads prime\n")
    return kits


def test_stage_kits_tree_mirror_and_selector_key(tmp_path: Path) -> None:
    kits = _seed(tmp_path)
    staged = stage_kits(kits)
    assert len(staged) == 1
    sk = staged[0]
    assert sk.selector_key == "kits/beads/.beads/PRIME.md"
    assert sk.ref.tool is None
    assert sk.ref.dest_relpath == Path(".beads/PRIME.md")
    universe = kit_universe(staged)
    assert universe["kits/beads/.beads/PRIME.md"] == [sk.ref]


def test_stage_kits_missing_root_is_empty(tmp_path: Path) -> None:
    assert stage_kits(tmp_path / "nope") == []


def test_kit_name_of_is_first_segment_under_kits() -> None:
    assert kit_name_of("kits/beads/.beads/PRIME.md") == "beads"

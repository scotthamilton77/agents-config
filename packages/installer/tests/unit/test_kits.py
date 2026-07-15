from pathlib import Path

from installer.core.kits import (
    kit_adapters,
    kit_name_of,
    kit_routes,
    kit_universe,
    stage_kits,
)
from installer.plugins.base import PluginAdapter


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


def test_kit_routes_grouped_by_dir_and_execbit(tmp_path: Path) -> None:
    kits = _seed(tmp_path)
    project = tmp_path / "proj"
    routes_by_kit = kit_routes(kits, project)
    assert set(routes_by_kit) == {"beads"}
    routes = routes_by_kit["beads"]
    assert len(routes) == 1
    r = routes[0]
    assert r.dest_dir == project / ".beads"
    assert r.source_dir == kits / "beads" / ".beads"
    assert r.executable is False


def test_kit_routes_mixed_exec_bits_one_route_per_file_correct_mode(tmp_path: Path) -> None:
    # A kit dir holding both a non-exec and an exec file in the SAME directory
    # must yield one route per file (glob = exact filename), each carrying its
    # own exec bit. A single glob="*" route per exec group would re-glob the
    # whole dir and install every file once per group — twice, with the wrong
    # mode. This pins the per-file contract that prevents that.
    kits = tmp_path / "kits"
    tooldir = kits / "toolkit" / "bin"
    tooldir.mkdir(parents=True)
    plain = tooldir / "notes.md"
    plain.write_bytes(b"notes\n")
    script = tooldir / "run.sh"
    script.write_bytes(b"#!/bin/sh\n")
    script.chmod(0o755)

    routes = kit_routes(kits, tmp_path / "proj")["toolkit"]
    assert len(routes) == 2  # one per file, NOT one per (dir x exec-bit) group
    by_glob = {r.glob: r for r in routes}
    assert set(by_glob) == {"notes.md", "run.sh"}
    assert by_glob["notes.md"].executable is False
    assert by_glob["run.sh"].executable is True
    # Every route globs exactly its own file, so no route re-matches a sibling
    # of a different exec class.
    for r in routes:
        matched = sorted(p.name for p in r.source_dir.glob(r.glob) if p.is_file())
        assert matched == [r.glob]


def test_stage_kits_and_kit_routes_skip_symlinks(tmp_path: Path) -> None:
    # Symlinks are excluded from both the kit-dir enumeration and the file walk,
    # so a kit can never dereference a link to copy bytes from outside src/kits
    # (matches the repo's overlay.py symlink-skip policy).
    kits = tmp_path / "kits"
    (kits / "beads" / ".beads").mkdir(parents=True)
    (kits / "beads" / ".beads" / "PRIME.md").write_bytes(b"real\n")
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"secret\n")
    (kits / "beads" / ".beads" / "link.md").symlink_to(outside)  # symlinked FILE
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "X.md").write_bytes(b"x\n")
    (kits / "linkkit").symlink_to(elsewhere, target_is_directory=True)  # symlinked DIR

    selectors = {sk.selector_key for sk in stage_kits(kits)}
    assert selectors == {"kits/beads/.beads/PRIME.md"}  # link.md + linkkit excluded

    routes_by_kit = kit_routes(kits, tmp_path / "proj")
    assert set(routes_by_kit) == {"beads"}  # symlinked kit dir excluded
    assert [r.glob for r in routes_by_kit["beads"]] == ["PRIME.md"]  # symlinked file excluded


def test_kit_adapters_conform_to_plugin_adapter(tmp_path: Path) -> None:
    kits = _seed(tmp_path)
    project = tmp_path / "proj"
    adapters = kit_adapters(kits, project, selected={"beads"})
    assert len(adapters) == 1
    a = adapters[0]
    assert isinstance(a, PluginAdapter)  # runtime_checkable Protocol
    assert a.name == "kit:beads"
    assert a.routes(project) == tuple(kit_routes(kits, project)["beads"])

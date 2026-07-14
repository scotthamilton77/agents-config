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


def test_kit_adapters_conform_to_plugin_adapter(tmp_path: Path) -> None:
    kits = _seed(tmp_path)
    project = tmp_path / "proj"
    adapters = kit_adapters(kits, project, selected={"beads"})
    assert len(adapters) == 1
    a = adapters[0]
    assert isinstance(a, PluginAdapter)  # runtime_checkable Protocol
    assert a.name == "kit:beads"
    assert a.routes(project) == tuple(kit_routes(kits, project)["beads"])

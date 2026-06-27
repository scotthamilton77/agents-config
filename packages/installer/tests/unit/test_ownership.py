from pathlib import Path

from installer.core.model import FileKind, Provenance, StagedItem
from installer.core.ownership import PRUNE_NAMESPACES, entry_for, is_prunable, route_entry_for


def _item(relpath: str, kind: FileKind, namespace: str | None) -> StagedItem:
    return StagedItem(
        source_path=Path("/src/x"),
        dest_relpath=Path(relpath),
        kind=kind,
        namespace=namespace,
        provenance=Provenance(kind="tool", name="claude"),
        content=(b"x" if kind != FileKind.DIR else None),
    )


def test_skill_dir_is_prunable() -> None:
    assert is_prunable(_item("skills/foo", FileKind.DIR, "skills"))


def test_rule_file_is_prunable() -> None:
    assert is_prunable(_item("rules/x.md", FileKind.NAMESPACED_MD, "rules"))


def test_settings_json_is_not_prunable() -> None:
    assert not is_prunable(_item("settings.json", FileKind.SETTINGS_JSON, None))


def test_entry_for_a_tool_item_owns_by_tool_with_home_relative_root() -> None:
    item = _item("skills/foo", FileKind.DIR, "skills")
    entry = entry_for(item, tool="claude", dest_root=Path("/home/u/.claude"), home=Path("/home/u"))
    assert entry is not None
    assert entry.owner == "claude"
    assert entry.root == Path(".claude")
    assert entry.path == Path(".claude/skills/foo")
    assert entry.kind == "dir"


def test_prune_namespaces_constant() -> None:
    assert PRUNE_NAMESPACES == ("commands", "skills", "agents", "rules")


def test_route_entry_for_beads_formula() -> None:
    entry = route_entry_for(
        Path("/home/u/.beads/formulas/foo.toml"),
        plugin="beads",
        dest_dir=Path("/home/u/.beads/formulas"),
        home=Path("/home/u"),
        sha256="ab",
    )
    assert entry.owner == "beads"
    assert entry.root == Path(".beads")
    assert entry.path == Path(".beads/formulas/foo.toml")
    assert entry.kind == "file"
    assert entry.sha256 == "ab"

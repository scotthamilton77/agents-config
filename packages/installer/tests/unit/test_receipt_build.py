from pathlib import Path

from installer.core.model import (
    FileKind,
    InstallOutcome,
    Outcome,
    Provenance,
    StagedItem,
    StagingPlan,
    Tool,
)
from installer.core.receipt_build import (
    desired_staged_keys,
    entries_from_outcomes,
    entries_from_plans,
    entries_from_route_outcomes,
)


def _plan(entries: list[tuple[str, FileKind]]) -> StagingPlan:
    items: dict[Path, StagedItem] = {}
    for relpath, kind in entries:
        p = Path(relpath)
        items[p] = StagedItem(
            source_path=Path("/src") / relpath,
            dest_relpath=p,
            kind=kind,
            namespace=p.parts[0],
            provenance=Provenance(kind="tool", name="claude"),
            content=(None if kind == FileKind.DIR else b"x"),
        )
    return StagingPlan(items=items, tool=Tool.CLAUDE)


def test_entries_and_desired_keys_align() -> None:
    plans = {"claude": _plan([("skills/foo", FileKind.DIR)])}
    dest_roots = {"claude": Path("/home/u/.claude")}
    entries = entries_from_plans(plans, dest_roots=dest_roots, home=Path("/home/u"))
    keys = desired_staged_keys(
        plans, dest_roots=dest_roots, home=Path("/home/u"), scope_owners={"claude"}
    )
    assert any(e.path == Path(".claude/skills/foo") for e in entries)
    assert ("claude", Path(".claude/skills/foo")) in keys


def test_out_of_scope_owner_excluded_from_desired_keys() -> None:
    plans = {"claude": _plan([("skills/foo", FileKind.DIR)])}
    dest_roots = {"claude": Path("/home/u/.claude")}
    keys = desired_staged_keys(
        plans, dest_roots=dest_roots, home=Path("/home/u"), scope_owners=set()
    )
    assert keys == set()


def test_entries_from_outcomes_excludes_declined_and_non_prune_ns() -> None:
    outcomes = [
        InstallOutcome(Path("/home/u/.claude/skills/foo"), Outcome.WRITTEN, None),
        InstallOutcome(Path("/home/u/.claude/rules/x.md"), Outcome.WRITTEN, "ab"),
        InstallOutcome(Path("/home/u/.claude/rules/y.md"), Outcome.DECLINED, None),
        InstallOutcome(Path("/home/u/.claude/settings.json"), Outcome.WRITTEN, "cd"),
    ]
    entries = entries_from_outcomes(
        outcomes, tool="claude", dest_root=Path("/home/u/.claude"), home=Path("/home/u")
    )
    by_path = {e.path: e for e in entries}
    assert set(by_path) == {Path(".claude/skills/foo"), Path(".claude/rules/x.md")}
    assert by_path[Path(".claude/rules/x.md")].sha256 == "ab"
    assert by_path[Path(".claude/rules/x.md")].kind == "file"
    assert by_path[Path(".claude/skills/foo")].kind == "dir"


def test_entries_from_route_outcomes_builds_plugin_entries() -> None:
    outcomes = [
        InstallOutcome(Path("/home/u/.beads/formulas/a.toml"), Outcome.WRITTEN, "ab"),
        InstallOutcome(Path("/home/u/.beads/formulas/b.toml"), Outcome.DECLINED, None),
    ]
    entries = entries_from_route_outcomes(outcomes, plugin="beads", home=Path("/home/u"))
    assert [e.path for e in entries] == [Path(".beads/formulas/a.toml")]
    assert entries[0].owner == "beads"
    assert entries[0].root == Path(".beads")
    assert entries[0].sha256 == "ab"

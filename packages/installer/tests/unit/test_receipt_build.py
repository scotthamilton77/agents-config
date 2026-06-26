from pathlib import Path

from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.receipt_build import desired_staged_keys, entries_from_plans


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

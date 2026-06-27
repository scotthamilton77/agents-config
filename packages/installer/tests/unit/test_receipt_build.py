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
from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_build import (
    desired_route_keys,
    desired_staged_keys,
    entries_from_outcomes,
    entries_from_route_outcomes,
    merge_receipt,
)
from installer.plugins.beads import BeadsPlugin


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


def test_desired_keys_include_in_scope_owner() -> None:
    plans = {"claude": _plan([("skills/foo", FileKind.DIR)])}
    dest_roots = {"claude": Path("/home/u/.claude")}
    keys = desired_staged_keys(
        plans, dest_roots=dest_roots, home=Path("/home/u"), scope_owners={"claude"}
    )
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


def test_entries_from_outcomes_excludes_settings_json_under_prune_ns() -> None:
    # A settings.json merge-target that lands under a prune namespace
    # (e.g. commands/settings.json) must NOT be recorded: it holds the user's
    # merged bytes, so recording it would make it eligible for orphan pruning.
    outcomes = [
        InstallOutcome(Path("/home/u/.claude/commands/settings.json"), Outcome.WRITTEN, "cd"),
        InstallOutcome(Path("/home/u/.claude/commands/foo.md"), Outcome.WRITTEN, "ab"),
    ]
    entries = entries_from_outcomes(
        outcomes, tool="claude", dest_root=Path("/home/u/.claude"), home=Path("/home/u")
    )
    paths = {e.path for e in entries}
    assert Path(".claude/commands/settings.json") not in paths
    # The guard is narrow: a normal file under the same namespace is still recorded.
    assert paths == {Path(".claude/commands/foo.md")}


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


def test_merge_receipt_preserves_unpruned_swaps_installed_accumulates_roots() -> None:
    prior = Receipt(
        roots=(Path(".codex"),),
        entries=(
            ReceiptEntry(Path(".claude/skills/old"), "claude", Path(".claude"), "dir", None),
            ReceiptEntry(Path(".codex/skills/keep"), "codex", Path(".codex"), "dir", None),
        ),
    )
    installed = [ReceiptEntry(Path(".claude/skills/new"), "claude", Path(".claude"), "dir", "ab")]
    new = merge_receipt(
        prior,
        installed=installed,
        pruned_paths={Path(".claude/skills/old")},
        relinquished_paths=set(),
        live_roots={Path(".claude")},
    )
    assert {e.path for e in new.entries} == {Path(".codex/skills/keep"), Path(".claude/skills/new")}
    assert set(new.roots) == {Path(".codex"), Path(".claude")}


def test_merge_receipt_relinquished_path_is_dropped() -> None:
    prior = Receipt(
        entries=(ReceiptEntry(Path(".claude/rules/x.md"), "claude", Path(".claude"), "file", "ab"),)
    )
    new = merge_receipt(
        prior,
        installed=[],
        pruned_paths=set(),
        relinquished_paths={Path(".claude/rules/x.md")},
        live_roots=set(),
    )
    assert new.entries == ()


def test_desired_route_keys_includes_shipped_route_files(tmp_path: Path) -> None:
    src = tmp_path / "src" / "beads"
    (src / ".beads" / "formulas").mkdir(parents=True)
    (src / ".beads" / "formulas" / "a.toml").write_text("x")
    home = tmp_path / "home"
    home.mkdir()
    beads = BeadsPlugin(name="beads", source_path=src, which=lambda _c: None)
    keys = desired_route_keys([beads], home=home)
    assert ("beads", Path(".beads/formulas/a.toml")) in keys


def test_entries_from_outcomes_records_dir_digest_for_real_dir(tmp_path: Path) -> None:
    # A dir outcome is recorded with a recursive digest of the installed tree, so a
    # later prune can detect content drift. The digest equals dir_content_digest.
    from installer.core.receipt import dir_content_digest

    home = tmp_path
    skill = home / ".claude" / "skills" / "foo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("owned content")
    outcomes = [InstallOutcome(skill, Outcome.WRITTEN, None)]
    entries = entries_from_outcomes(outcomes, tool="claude", dest_root=home / ".claude", home=home)
    entry = entries[0]
    assert entry.kind == "dir"
    assert entry.sha256 is None
    assert entry.dir_digest == dir_content_digest(skill)

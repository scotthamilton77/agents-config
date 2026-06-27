"""End-to-end tracer for receipt-based pruning via prune_pipeline.

Proves the architecture: a prior receipt plus a staging plan that drops one
entry -> the dropped entry is pruned and the returned PruneOutcome names it.
prune_pipeline is pure prune: it RECEIVES the prior receipt and RETURNS a
PruneOutcome (no receipt read, no receipt write). The receipt is the sole prune
authority (no globs); the caller writes it via record_receipt.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_store import read_receipt
from installer.core.run import prune_pipeline, record_receipt
from installer.tools.registry import get_adapter

_TS = "20250101-120000"


def _receipt_path(home: Path) -> Path:
    return home / ".config" / "agents-config" / "install-receipt.json"


def _claude_home(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    return tmp_path


def _skill_item(name: str) -> StagedItem:
    rel = Path("skills") / name
    return StagedItem(
        source_path=Path("/src") / rel,
        dest_relpath=rel,
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )


def _entry(relpath: str) -> ReceiptEntry:
    return ReceiptEntry(Path(relpath), "claude", Path(".claude"), "dir", None)


def test_dropped_entry_is_pruned_and_outcome_names_it(tmp_path: Path) -> None:
    home = _claude_home(tmp_path)
    keep = home / ".claude" / "skills" / "keep"
    drop = home / ".claude" / "skills" / "drop"
    keep.mkdir(parents=True)
    drop.mkdir(parents=True)
    prior = Receipt(
        roots=(Path(".claude"),),
        entries=(_entry(".claude/skills/keep"), _entry(".claude/skills/drop")),
    )
    plans = {
        Tool.CLAUDE: StagingPlan(items={Path("skills/keep"): _skill_item("keep")}, tool=Tool.CLAUDE)
    }

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert keep.exists()
    assert not drop.exists()
    assert outcome.counters["claude"].pruned == 1
    assert outcome.pruned_paths == {Path(".claude/skills/drop")}


def test_missing_receipt_prunes_nothing(tmp_path: Path) -> None:
    home = _claude_home(tmp_path)
    stray = home / ".claude" / "skills" / "stray"
    stray.mkdir(parents=True)
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        prior=Receipt(),
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert stray.exists()  # empty prior => nothing is an orphan
    assert outcome.counters == {}
    assert outcome.pruned_paths == set()


def test_no_orphans_clean_noop(tmp_path: Path) -> None:
    home = _claude_home(tmp_path)
    keep = home / ".claude" / "skills" / "keep"
    keep.mkdir(parents=True)
    prior = Receipt(roots=(Path(".claude"),), entries=(_entry(".claude/skills/keep"),))
    plans = {
        Tool.CLAUDE: StagingPlan(items={Path("skills/keep"): _skill_item("keep")}, tool=Tool.CLAUDE)
    }

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=True),
        timestamp=_TS,
    )

    assert keep.exists()
    assert outcome.counters == {}
    assert outcome.pruned_paths == set()


def test_targeted_run_preserves_untargeted_tool_entry(tmp_path: Path) -> None:
    """A claude-only prune+record never erases an untargeted codex entry.

    prune_pipeline returns the pruned set; record_receipt then writes the
    mirrors-disk receipt. The untargeted ``.codex/skills/cx`` entry — neither
    in this run's scope nor pruned — survives in the written receipt.
    """
    home = _claude_home(tmp_path)
    (home / ".claude" / "skills" / "keep").mkdir(parents=True)
    prior = Receipt(
        roots=(Path(".claude"), Path(".codex")),
        entries=(
            _entry(".claude/skills/keep"),
            ReceiptEntry(Path(".codex/skills/cx"), "codex", Path(".codex"), "dir", None),
        ),
    )
    plans = {
        Tool.CLAUDE: StagingPlan(items={Path("skills/keep"): _skill_item("keep")}, tool=Tool.CLAUDE)
    }
    adapter = get_adapter(Tool.CLAUDE)
    outcome = prune_pipeline(
        [adapter],
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    receipt_path = _receipt_path(home)
    record_receipt(
        receipt_path,
        prior=prior,
        dest_roots={"claude": adapter.dest_dir(home)},
        home=home,
        tool_outcomes={},
        plugin_outcomes={},
        pruned_paths=outcome.pruned_paths,
        relinquished_paths=outcome.relinquished_paths,
    )

    after = read_receipt(receipt_path).receipt
    assert after is not None
    paths = {e.path for e in after.entries}
    assert Path(".codex/skills/cx") in paths  # untargeted tool preserved (mass-delete trap fixed)
    assert Path(".claude/skills/keep") in paths

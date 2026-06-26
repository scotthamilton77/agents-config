"""End-to-end tracer for receipt-based pruning via prune_pipeline.

Proves the architecture: a prior receipt plus a staging plan that drops one
entry -> the dropped entry is pruned and the rewritten receipt mirrors the plan.
The receipt is the sole prune authority (no globs).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.installer_toml import InstallerToml
from installer.core.io_port import ScriptedIO
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_store import read_receipt, write_receipt
from installer.core.run import prune_pipeline
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


def test_dropped_entry_is_pruned_and_receipt_rewritten(tmp_path: Path) -> None:
    home = _claude_home(tmp_path)
    keep = home / ".claude" / "skills" / "keep"
    drop = home / ".claude" / "skills" / "drop"
    keep.mkdir(parents=True)
    drop.mkdir(parents=True)
    rpath = _receipt_path(home)
    write_receipt(
        rpath,
        Receipt(
            roots=(Path(".claude"),),
            entries=(_entry(".claude/skills/keep"), _entry(".claude/skills/drop")),
        ),
    )
    plans = {
        Tool.CLAUDE: StagingPlan(items={Path("skills/keep"): _skill_item("keep")}, tool=Tool.CLAUDE)
    }

    per_tool = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        home=home,
        config=InstallerToml(),
        receipt_path=rpath,
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert keep.exists()
    assert not drop.exists()
    assert per_tool["claude"].pruned == 1
    after = read_receipt(rpath)
    assert after.receipt is not None
    assert [e.path for e in after.receipt.entries] == [Path(".claude/skills/keep")]


def test_missing_receipt_prunes_nothing(tmp_path: Path) -> None:
    home = _claude_home(tmp_path)
    stray = home / ".claude" / "skills" / "stray"
    stray.mkdir(parents=True)
    rpath = _receipt_path(home)  # absent
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    per_tool = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        home=home,
        config=InstallerToml(),
        receipt_path=rpath,
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert stray.exists()  # no prior receipt => nothing is an orphan
    assert per_tool == {}
    assert read_receipt(rpath).receipt is not None  # a fresh receipt is written


def test_no_orphans_clean_noop(tmp_path: Path) -> None:
    home = _claude_home(tmp_path)
    keep = home / ".claude" / "skills" / "keep"
    keep.mkdir(parents=True)
    rpath = _receipt_path(home)
    write_receipt(
        rpath, Receipt(roots=(Path(".claude"),), entries=(_entry(".claude/skills/keep"),))
    )
    plans = {
        Tool.CLAUDE: StagingPlan(items={Path("skills/keep"): _skill_item("keep")}, tool=Tool.CLAUDE)
    }

    per_tool = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        home=home,
        config=InstallerToml(),
        receipt_path=rpath,
        io=ScriptedIO(interactive=True),
        timestamp=_TS,
    )

    assert keep.exists()
    assert per_tool == {}

"""Unit tests for installer.core.run.install_pipeline (W1 — multi-tool compose).

``install_pipeline`` is the install-side analog of ``prune_pipeline``: for each
active tool's adapter it walks that tool's ``StagingPlan`` to disk via
``sync_plan`` and returns the summed ``Counters``. These tests pin the
composition's end-state — files on disk under each tool's real dest root plus
the aggregate tally — driving real adapters and the filesystem under
``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.model import FileKind, InstallOutcome, Provenance, StagedItem, StagingPlan, Tool
from installer.core.run import install_pipeline
from installer.tools.registry import get_adapter

_FIXED_TS = "20260613-120000"


def _file_item(relpath: Path, content: bytes, *, tool: str = "claude") -> StagedItem:
    return StagedItem(
        source_path=Path("/unused") / relpath,
        dest_relpath=relpath,
        kind=FileKind.OTHER,
        namespace=None,
        provenance=Provenance(kind="tool", name=tool),
        content=content,
    )


def _settings_item(content: bytes, *, tool: str = "claude") -> StagedItem:
    return StagedItem(
        source_path=Path("/unused/settings.json"),
        dest_relpath=Path("settings.json"),
        kind=FileKind.SETTINGS_JSON,
        namespace=None,
        provenance=Provenance(kind="tool", name=tool),
        content=content,
    )


def test_install_pipeline_keeps_per_tool_counters_separate(tmp_path: Path) -> None:
    """
    Given two adapters — one installing a new file (claude), one whose dest file
    already matches its plan (codex, a skip)
    When install_pipeline runs
    Then each tool's dest tree reflects its plan and the returned mapping keeps
    the per-tool results in SEPARATE buckets (claude.created==1, codex.skipped==1)
    rather than summing them into one Counters.

    Pins the 8.18 per-tool plumbing change: the summary renderer needs each
    tool's own tally, so install_pipeline returns a name-keyed mapping, not an
    aggregate. Fails while it sums every sync_plan result into one Counters.
    """
    home = tmp_path / "home"
    claude = get_adapter(Tool.CLAUDE)
    codex = get_adapter(Tool.CODEX)
    # Pre-seed codex's dest with bytes identical to its plan -> a skip.
    codex.dest_dir(home).mkdir(parents=True)
    (codex.dest_dir(home) / "b.md").write_bytes(b"B\n")
    plans = {
        Tool.CLAUDE: StagingPlan(
            items={Path("a.md"): _file_item(Path("a.md"), b"A\n")}, tool=Tool.CLAUDE
        ),
        Tool.CODEX: StagingPlan(
            items={Path("b.md"): _file_item(Path("b.md"), b"B\n", tool="codex")}, tool=Tool.CODEX
        ),
    }

    per_tool = install_pipeline(
        [claude, codex], plans=plans, home=home, io=ScriptedIO(), timestamp=_FIXED_TS
    )

    assert (claude.dest_dir(home) / "a.md").read_bytes() == b"A\n"
    # The create landed in claude's bucket, the skip in codex's — not summed.
    assert per_tool["claude"].created == 1
    assert per_tool["claude"].skipped == 0
    assert per_tool["codex"].created == 0
    assert per_tool["codex"].skipped == 1


def test_install_pipeline_forwards_auto_yes_to_each_sync_plan(tmp_path: Path) -> None:
    """
    Given a tool whose dest already holds different bytes than its plan, and --yes
    When install_pipeline runs with NO queued confirm answers
    Then the overwrite proceeds without prompting — install_pipeline forwards
    auto_yes into each sync_plan call (the default would otherwise trip the W2
    consent gate and raise ScriptExhaustedError on the empty confirm queue).
    """
    home = tmp_path / "home"
    claude = get_adapter(Tool.CLAUDE)
    claude.dest_dir(home).mkdir(parents=True)
    (claude.dest_dir(home) / "a.md").write_bytes(b"old\n")
    plans = {
        Tool.CLAUDE: StagingPlan(
            items={Path("a.md"): _file_item(Path("a.md"), b"new\n")}, tool=Tool.CLAUDE
        ),
    }

    per_tool = install_pipeline(
        [claude], plans=plans, home=home, io=ScriptedIO(), auto_yes=True, timestamp=_FIXED_TS
    )

    assert (claude.dest_dir(home) / "a.md").read_bytes() == b"new\n"
    assert (per_tool["claude"].updated, per_tool["claude"].backed_up) == (1, 1)


def test_install_pipeline_aggregates_merged_counter(tmp_path: Path) -> None:
    """
    Given a tool whose dest already holds a settings.json that a staged
    settings.json union would change (a merge, not a plain update)
    When install_pipeline runs with --yes
    Then the aggregate Counters carry merged=1 (and updated=0).

    Pins: install_pipeline sums each sync_plan's ``merged`` field into the
    returned total — the field the 'Merged' summary line reports. Fails while the
    aggregation drops ``merged`` (sums only created/updated/skipped/backed_up), so
    a real merge never reaches the summary.
    """
    home = tmp_path / "home"
    claude = get_adapter(Tool.CLAUDE)
    claude.dest_dir(home).mkdir(parents=True)
    (claude.dest_dir(home) / "settings.json").write_bytes(b'{"userKey": "keep-me"}\n')
    plans = {
        Tool.CLAUDE: StagingPlan(
            items={Path("settings.json"): _settings_item(b'{"templateKey": 1}')},
            tool=Tool.CLAUDE,
        ),
    }

    per_tool = install_pipeline(
        [claude], plans=plans, home=home, io=ScriptedIO(), auto_yes=True, timestamp=_FIXED_TS
    )

    assert per_tool["claude"].merged == 1
    assert per_tool["claude"].updated == 0


def test_install_pipeline_dry_run_collects_no_outcomes(tmp_path: Path) -> None:
    """
    Given a tool with a file that a real install WOULD write
    When install_pipeline runs with dry_run=True and an outcomes_by_tool dict
    Then the tool's key maps to an EMPTY list — no phantom WRITTEN outcome.

    The outcome channel feeds record_receipt, whose contract is "what happened on
    disk". A dry run writes nothing, so it must contribute nothing to the channel
    even though sync_file still reports the would-be outcome to direct callers.
    Pins the receipt-feeding boundary: the key is present (callers see every
    adapter) but the list is empty. Fails while a live collector is threaded into
    sync_plan on a dry run, capturing a phantom WRITTEN for an unwritten file.
    """
    home = tmp_path / "home"
    claude = get_adapter(Tool.CLAUDE)
    plans = {
        Tool.CLAUDE: StagingPlan(
            items={Path("a.md"): _file_item(Path("a.md"), b"A\n")}, tool=Tool.CLAUDE
        ),
    }
    outcomes_by_tool: dict[str, list[InstallOutcome]] = {}

    install_pipeline(
        [claude],
        plans=plans,
        home=home,
        io=ScriptedIO(),
        dry_run=True,
        timestamp=_FIXED_TS,
        outcomes_by_tool=outcomes_by_tool,
    )

    assert not (claude.dest_dir(home) / "a.md").exists()  # nothing hit disk
    assert outcomes_by_tool == {"claude": []}  # key present, no phantom WRITTEN


def test_install_pipeline_real_install_still_collects_outcomes(tmp_path: Path) -> None:
    """
    Given the same write-bound file
    When install_pipeline runs with dry_run=False and an outcomes_by_tool dict
    Then the tool's key holds the real WRITTEN outcome — the dry-run guard must
    not suppress collection on a real install.

    Regression guard for the dry-run-only fix: ``collect`` must be True when
    not dry_run, so a real install still feeds record_receipt. Fails if the
    guard over-broadly drops the live collector.
    """
    home = tmp_path / "home"
    claude = get_adapter(Tool.CLAUDE)
    plans = {
        Tool.CLAUDE: StagingPlan(
            items={Path("a.md"): _file_item(Path("a.md"), b"A\n")}, tool=Tool.CLAUDE
        ),
    }
    outcomes_by_tool: dict[str, list[InstallOutcome]] = {}

    install_pipeline(
        [claude],
        plans=plans,
        home=home,
        io=ScriptedIO(),
        dry_run=False,
        timestamp=_FIXED_TS,
        outcomes_by_tool=outcomes_by_tool,
    )

    assert (claude.dest_dir(home) / "a.md").read_bytes() == b"A\n"
    assert [o.dest.name for o in outcomes_by_tool["claude"]] == ["a.md"]

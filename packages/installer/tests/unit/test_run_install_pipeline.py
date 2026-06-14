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
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
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


def test_install_pipeline_aggregates_counters_across_tools(tmp_path: Path) -> None:
    """
    Given two adapters — one installing a new file, one whose dest file already
    matches its plan (a skip)
    When install_pipeline runs
    Then each tool's dest tree reflects its plan and the returned Counters sum
    the per-tool results (a create from one tool, a skip from the other).
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

    counters = install_pipeline(
        [claude, codex], plans=plans, home=home, io=ScriptedIO(), timestamp=_FIXED_TS
    )

    assert (claude.dest_dir(home) / "a.md").read_bytes() == b"A\n"
    assert (counters.created, counters.skipped) == (1, 1)


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

    counters = install_pipeline(
        [claude], plans=plans, home=home, io=ScriptedIO(), auto_yes=True, timestamp=_FIXED_TS
    )

    assert (claude.dest_dir(home) / "a.md").read_bytes() == b"new\n"
    assert (counters.updated, counters.backed_up) == (1, 1)

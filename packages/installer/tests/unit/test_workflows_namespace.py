from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.model import InstallOutcome, Outcome
from installer.core.receipt_build import entries_from_outcomes
from installer.core.staging import build_plan
from installer.core.sync import sync
from installer.tools.claude import ClaudeAdapter


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    wf = repo / "src" / "user" / ".claude" / "workflows"
    wf.mkdir(parents=True)
    (wf / "quality-gate.js").write_text("export const meta = { name: 'quality-gate' }\n")
    return repo


def test_workflows_namespace_is_staged(tmp_path, ignore):
    repo = _make_repo(tmp_path)
    plan = build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)
    assert Path("workflows/quality-gate.js") in plan.items


def test_workflows_namespace_is_deployed(tmp_path):
    repo_root = tmp_path / "repo"
    home = tmp_path / "home"
    source = repo_root / "src" / "user" / ".claude" / "workflows" / "quality-gate.js"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"export const meta = { name: 'quality-gate' }\n")

    counters = sync(
        ClaudeAdapter(),
        Path("workflows/quality-gate.js"),
        repo_root=repo_root,
        home=home,
        io=ScriptedIO(),
    )

    assert (home / ".claude" / "workflows" / "quality-gate.js").read_bytes() == (
        b"export const meta = { name: 'quality-gate' }\n"
    )
    assert counters.created == 1


def test_workflow_write_is_receipt_tracked():
    """A written workflows/ file must be receipt-recorded so a later source
    rename/removal can prune it — without this, entries_from_outcomes drops it
    (namespace not in PRUNE_NAMESPACES) and a stale ~/.claude/workflows/*.js
    survives forever with no receipt entry to trigger its deletion."""
    outcomes = [
        InstallOutcome(Path("/home/u/.claude/workflows/quality-gate.js"), Outcome.WRITTEN, "ab")
    ]
    entries = entries_from_outcomes(
        outcomes, tool="claude", dest_root=Path("/home/u/.claude"), home=Path("/home/u")
    )
    assert {e.path for e in entries} == {Path(".claude/workflows/quality-gate.js")}

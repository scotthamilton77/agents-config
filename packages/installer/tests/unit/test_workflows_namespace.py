from pathlib import Path

from installer.core.deploy_gate import run_admission_gate
from installer.core.io_port import ScriptedIO
from installer.core.model import InstallOutcome, Outcome, Tool
from installer.core.receipt_build import entries_from_outcomes
from installer.core.staging import build_plan
from installer.core.sync import sync
from installer.tools.claude import ClaudeAdapter

_BODY = b"export const meta = { name: 'example' }\n"
# The record convention for a JS workflow: a leading fence carrying nothing but
# the admission block, which the gate strips back to plain JavaScript.
_RECORDED = b"---\nadmission:\n  provides: p\n  cost: c\n  remove_when: r\n---\n" + _BODY


def _make_repo(tmp_path: Path, content: bytes = _BODY) -> Path:
    repo = tmp_path / "repo"
    wf = repo / "src" / "user" / ".claude" / "workflows"
    wf.mkdir(parents=True)
    (wf / "example.js").write_bytes(content)
    return repo


def test_workflows_namespace_is_staged(tmp_path, ignore):
    repo = _make_repo(tmp_path)
    plan = build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)
    assert Path("workflows/example.js") in plan.items


def test_record_less_workflow_is_dropped_by_the_gate(tmp_path, ignore):
    """A workflow deploys executable capability into the user's home, so it is
    gated exactly as a skill is: no admission record, no deploy."""
    repo = _make_repo(tmp_path)
    plans = {Tool.CLAUDE: build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)}

    result = run_admission_gate(plans)

    assert result.ok
    assert Path("workflows/example.js") not in result.plans[Tool.CLAUDE].items
    assert "claude:workflows/example.js" in result.skipped


def test_recorded_workflow_deploys_without_its_record(tmp_path, ignore):
    repo = _make_repo(tmp_path, content=_RECORDED)
    plans = {Tool.CLAUDE: build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)}

    result = run_admission_gate(plans)

    assert result.ok
    assert result.skipped == []
    assert result.plans[Tool.CLAUDE].items[Path("workflows/example.js")].content == _BODY


def test_workflows_namespace_is_deployed(tmp_path):
    repo_root = tmp_path / "repo"
    home = tmp_path / "home"
    source = repo_root / "src" / "user" / ".claude" / "workflows" / "example.js"
    source.parent.mkdir(parents=True)
    source.write_bytes(_BODY)

    counters = sync(
        ClaudeAdapter(),
        Path("workflows/example.js"),
        repo_root=repo_root,
        home=home,
        io=ScriptedIO(),
    )

    assert (home / ".claude" / "workflows" / "example.js").read_bytes() == _BODY
    assert counters.created == 1


def test_workflow_write_is_receipt_tracked():
    """A written workflows/ file must be receipt-recorded so a later source
    rename/removal can prune it — without this, entries_from_outcomes drops it
    (namespace not in PRUNE_NAMESPACES) and a stale ~/.claude/workflows/*.js
    survives forever with no receipt entry to trigger its deletion."""
    outcomes = [InstallOutcome(Path("/home/u/.claude/workflows/example.js"), Outcome.WRITTEN, "ab")]
    entries = entries_from_outcomes(
        outcomes, tool="claude", dest_root=Path("/home/u/.claude"), home=Path("/home/u")
    )
    assert {e.path for e in entries} == {Path(".claude/workflows/example.js")}

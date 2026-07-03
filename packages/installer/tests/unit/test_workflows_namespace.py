from pathlib import Path

from installer.core.io_port import ScriptedIO
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

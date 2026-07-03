from pathlib import Path

from installer.core.staging import build_plan
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

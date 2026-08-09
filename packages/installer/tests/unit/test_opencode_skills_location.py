"""Invariant guard: every statement about where OpenCode skills land agrees
with where the installer actually stages them.

Three surfaces make this claim independently — the runtime config template,
and two source-side docs read by contributors — and nothing enforced that a
change to one would keep the others honest. This test reads all three plus
the real ``OpenCodeAdapter`` and requires them to agree.
"""

from __future__ import annotations

import json
from pathlib import Path

from installer.tools.opencode import OpenCodeAdapter

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FAKE_HOME = Path("/home/u")


def _real_skills_dir() -> Path:
    """Where the installer actually stages OpenCode's shared skills/ namespace."""
    return OpenCodeAdapter().dest_dir(_FAKE_HOME) / "skills"


def test_jsonc_template_skills_paths_matches_real_staging_destination() -> None:
    template = _REPO_ROOT / "src" / "user" / ".opencode" / "opencode.jsonc.template"
    config = json.loads(template.read_text(encoding="utf-8"))
    (configured,) = config["skills"]["paths"]

    assert configured.startswith("~/")
    expanded = _FAKE_HOME / configured.removeprefix("~/")
    assert expanded == _real_skills_dir()


def test_opencode_agents_md_names_the_real_skills_destination() -> None:
    text = (_REPO_ROOT / "src" / "user" / ".opencode" / "AGENTS.md").read_text(encoding="utf-8")
    assert "~/.config/opencode/skills/" in text
    # The two prior wrong answers this doc gave, so a regression to either is caught.
    assert "~/.claude/skills" not in text
    assert "~/.agents/skills" not in text


def test_shared_readme_names_the_real_opencode_skills_destination() -> None:
    text = (_REPO_ROOT / "src" / "user" / ".agents" / "README.md").read_text(encoding="utf-8")
    assert "~/.config/opencode/" in text

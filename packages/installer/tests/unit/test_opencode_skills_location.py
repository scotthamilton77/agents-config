"""Invariant guard: every statement about where OpenCode skills land agrees
with where the installer actually stages them.

Two source-side docs make the claim in prose and the runtime config template
makes it by omission, and nothing else enforced that a change to one would keep
the others honest. This test reads all three against the real
``OpenCodeAdapter`` and requires them to agree.
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


def test_jsonc_template_registers_no_extra_skill_paths() -> None:
    """The staging destination is already one of the global roots OpenCode scans
    by default. ``skills.paths`` only adds roots to those defaults, so an entry
    naming this one restates a default while reading as the mechanism that makes
    skills load — and an entry naming anything else points somewhere the
    installer never populates."""
    template = _REPO_ROOT / "src" / "user" / ".opencode" / "opencode.jsonc.template"
    config = json.loads(template.read_text(encoding="utf-8"))

    assert "skills" not in config


def test_opencode_agents_md_names_the_real_skills_destination() -> None:
    text = (_REPO_ROOT / "src" / "user" / ".opencode" / "AGENTS.md").read_text(encoding="utf-8")
    assert f"~/{_real_skills_dir().relative_to(_FAKE_HOME).as_posix()}/" in text
    # The two prior wrong answers this doc gave, so a regression to either is caught.
    assert "~/.claude/skills" not in text
    assert "~/.agents/skills" not in text


def test_shared_readme_names_the_real_opencode_skills_destination() -> None:
    text = (_REPO_ROOT / "src" / "user" / ".agents" / "README.md").read_text(encoding="utf-8")
    assert "~/.config/opencode/" in text

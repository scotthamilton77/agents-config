"""Behavioural coverage for CodexAdapter via the sync engine.

Drives the real CodexAdapter end-to-end through sync so that its
source_dir / dest_dir earn behavioural coverage. The engine's own branch
behaviour is unit-tested in test_sync.py; this file asserts only that sync
wires the real adapter's source and destination roots correctly.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.sync import sync
from installer.tools.codex import CodexAdapter


def test_codex_adapter_installs_file_under_dot_codex(tmp_path: Path) -> None:
    """
    Given a file in the repo's src/user/.codex/ tree
    When sync installs it for the real CodexAdapter
    Then it lands under <home>/.codex/ with the source bytes — exercising
    CodexAdapter.source_dir and dest_dir behaviourally.
    """
    repo_root = tmp_path / "repo"
    home = tmp_path / "home"
    source = repo_root / "src" / "user" / ".codex" / "AGENTS.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# Codex AGENTS\n")

    counters = sync(
        CodexAdapter(),
        Path("AGENTS.md"),
        repo_root=repo_root,
        home=home,
        io=ScriptedIO(),
    )

    assert (home / ".codex" / "AGENTS.md").read_bytes() == b"# Codex AGENTS\n"
    assert counters.created == 1

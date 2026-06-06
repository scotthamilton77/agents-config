"""Behavioural coverage for OpenCodeAdapter via the sync engine.

Drives the real OpenCodeAdapter end-to-end through sync so that its
source_dir / dest_dir earn behavioural coverage. The engine's own branch
behaviour is unit-tested in test_sync.py; this file asserts only that sync
wires the real adapter's source and destination roots correctly — in
particular the XDG destination (~/.config/opencode/, NOT ~/.opencode/).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.sync import sync
from installer.tools.opencode import OpenCodeAdapter


def test_opencode_adapter_installs_file_under_xdg_config_opencode(tmp_path: Path) -> None:
    """
    Given a file in the repo's src/user/.opencode/ tree
    When sync installs it for the real OpenCodeAdapter
    Then it lands under <home>/.config/opencode/ with the source bytes —
    exercising OpenCodeAdapter.source_dir and the XDG dest_dir.

    Pins: the XDG destination divergence — a non-XDG dest (~/.opencode/)
    would fail this test.
    """
    repo_root = tmp_path / "repo"
    home = tmp_path / "home"
    source = repo_root / "src" / "user" / ".opencode" / "AGENTS.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# OpenCode AGENTS\n")

    counters = sync(
        OpenCodeAdapter(),
        Path("AGENTS.md"),
        repo_root=repo_root,
        home=home,
        io=ScriptedIO(),
    )

    assert (home / ".config" / "opencode" / "AGENTS.md").read_bytes() == b"# OpenCode AGENTS\n"
    assert not (home / ".opencode").exists()
    assert counters.created == 1

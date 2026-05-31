"""Behavioural coverage for ClaudeAdapter via the B.2 sync engine.

Drives the *real* ClaudeAdapter end-to-end through sync so that its
source_dir / dest_dir earn behavioural coverage — the ``# pragma: no
cover`` markers those two methods carried (forward-tracked from
w1qls.2.1) come off in this story. The engine's own branch behaviour
(skip / update / dry-run / failure modes) is unit-tested against a fake
adapter in test_sync.py; this file asserts only that sync wires the real
adapter's source and destination roots correctly.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.sync import sync
from installer.tools.claude import ClaudeAdapter


def test_claude_adapter_installs_file_under_dot_claude(tmp_path: Path) -> None:
    """
    Given a file in the repo's src/user/.claude/ tree
    When sync installs it for the real ClaudeAdapter
    Then it lands under <home>/.claude/ with the source bytes — exercising
    ClaudeAdapter.source_dir and dest_dir behaviourally.
    """
    repo_root = tmp_path / "repo"
    home = tmp_path / "home"
    source = repo_root / "src" / "user" / ".claude" / "settings.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b'{"k": 1}\n')

    counters = sync(
        ClaudeAdapter(),
        Path("settings.json"),
        repo_root=repo_root,
        home=home,
        io=ScriptedIO(),
    )

    assert (home / ".claude" / "settings.json").read_bytes() == b'{"k": 1}\n'
    assert counters.created == 1

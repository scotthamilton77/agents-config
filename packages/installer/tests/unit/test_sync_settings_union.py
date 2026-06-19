"""sync_plan unions a staged settings.json with the user's existing dest file.

Ports the bash installer's ``sync_settings_file`` (``scripts/install.sh:1268-1335``):
a settings.json install is not a blind overwrite — the staged template is
union-merged into the user's current file so user values survive. The Python
installer previously overwrote (user keys survived only in the backup); these
tests pin the union semantics.
"""

from __future__ import annotations

import json
from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.sync import sync_plan

_TS = "20260615-120000"


class _IdentityAdapter:
    """Minimal ToolAdapter double — sync_plan only consults dest_dir."""

    name: str = "claude"
    detection_signal: str = ".claude"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root

    def dest_dir(self, home: Path) -> Path:
        return home


def _settings_item(content: bytes) -> StagedItem:
    return StagedItem(
        source_path=Path("/unused/settings.json"),
        dest_relpath=Path("settings.json"),
        kind=FileKind.SETTINGS_JSON,
        namespace=None,
        provenance=Provenance(kind="tool", name="claude"),
        content=content,
    )


def test_sync_unions_settings_with_existing_user_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.json").write_text('{"userKey": "keep-me", "shared": "user-wins"}\n')
    plan = StagingPlan(
        items={
            Path("settings.json"): _settings_item(b'{"templateKey": 1, "shared": "template-loses"}')
        },
        tool=Tool.CLAUDE,
    )

    sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), auto_yes=True, timestamp=_TS)

    result = json.loads((home / "settings.json").read_bytes())
    assert result["userKey"] == "keep-me"  # user-only key preserved
    assert result["templateKey"] == 1  # template-only key added
    assert result["shared"] == "user-wins"  # scalar conflict -> user (existing) wins


def test_sync_settings_backs_up_user_file_before_union(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.json").write_text('{"userKey": "keep-me"}\n')
    plan = StagingPlan(
        items={Path("settings.json"): _settings_item(b'{"templateKey": 1}')},
        tool=Tool.CLAUDE,
    )

    sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), auto_yes=True, timestamp=_TS)

    backups = list(home.glob("settings.json.backup-*"))
    assert backups, "the user's original settings.json must be backed up before the union"
    assert json.loads(backups[0].read_bytes()) == {"userKey": "keep-me"}


def test_sync_preserves_and_skips_invalid_existing_settings(tmp_path: Path) -> None:
    """An existing settings.json that is not valid JSON is left untouched and
    reported as an error, not overwritten — matching bash, which refuses to touch a
    file it cannot parse (``scripts/install.sh:1299-1304``: err + skip + return, the
    file left in place). The earlier Python behaviour clobbered it with the template
    (the user's content survived only in a backup); these assertions pin the
    skip-and-preserve contract."""
    home = tmp_path / "home"
    home.mkdir()
    invalid = "{ not valid json"
    (home / "settings.json").write_text(invalid)
    plan = StagingPlan(
        items={Path("settings.json"): _settings_item(b'{"templateKey": 1}')},
        tool=Tool.CLAUDE,
    )
    io = ScriptedIO()

    counters = sync_plan(_IdentityAdapter(), plan, home=home, io=io, auto_yes=True, timestamp=_TS)

    # the malformed file is preserved verbatim — not overwritten, not backed up
    assert (home / "settings.json").read_text() == invalid
    assert not list(home.glob("settings.json.backup-*"))
    # it is counted as skipped, not updated
    assert counters.skipped == 1
    assert counters.updated == 0
    # an actionable error names the offending file
    errs = [e for e in io.transcript if e.channel == "err"]
    assert errs, "expected an error about the invalid settings.json"
    assert "invalid JSON" in errs[0].message

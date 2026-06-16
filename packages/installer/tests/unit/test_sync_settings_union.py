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


def test_sync_overwrites_when_existing_settings_is_invalid_json(tmp_path: Path) -> None:
    """A malformed existing settings.json cannot be unioned; the installer falls
    back to overwrite (bash warns and replaces) rather than crashing."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "settings.json").write_text("{ not valid json")
    plan = StagingPlan(
        items={Path("settings.json"): _settings_item(b'{"templateKey": 1}')},
        tool=Tool.CLAUDE,
    )

    sync_plan(_IdentityAdapter(), plan, home=home, io=ScriptedIO(), auto_yes=True, timestamp=_TS)

    assert json.loads((home / "settings.json").read_bytes()) == {"templateKey": 1}

"""Phase 6.5 wired through stage_and_transform (core/orchestrator.py).

End-to-end pins for the F.5 extension mechanism in pipeline position: after
the Phase 6 overlay (extensions can target plugin-contributed and
carrier-merged files) and per-tool (scope isolation holds across plans).
The round-trip test is the plan-level analog of phzj.4 AC #9 — the deployed-
file form lands with the Epic E/H plan-walking sync.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.installignore import InstallIgnore
from installer.core.io_port import ScriptedIO
from installer.core.model import Tool
from installer.core.orchestrator import stage_and_transform
from installer.plugins.generic import GenericPluginAdapter


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


SKILL_BASE = "# Demo\n\n## Usage\nbase usage\n\n## Reference\nsee docs\n"
CHEAT_BLOCK = "### Beads cheats\n- bd ready\n- bd show <id>"


def test_extension_round_trip_injects_content_at_logical_position(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """Round-trip equivalence (AC #9 analog): the resolved SKILL.md bytes
    contain the injected block at the targeted position; every other byte of
    the base document is unchanged."""
    repo = tmp_path / "repo"
    _write(repo / "src" / "user" / ".agents" / "skills" / "demo" / "SKILL.md", SKILL_BASE)
    plugin_root = tmp_path / "plugins" / "demo-plugin"
    _write(
        plugin_root / ".agents" / "extensions" / "00-cheats.yaml",
        "target-file: skills/demo/SKILL.md\n"
        "target-section: Usage\n"
        "precision: append\n"
        "content: |\n" + "".join(f"  {line}\n" for line in CHEAT_BLOCK.split("\n")),
    )
    plugin = GenericPluginAdapter(name="demo-plugin", source_path=plugin_root)

    plans = stage_and_transform(
        [Tool.CLAUDE, Tool.CODEX], repo_root=repo, io=ScriptedIO(), ignore=ignore, plugins=[plugin]
    )

    for tool in (Tool.CLAUDE, Tool.CODEX):  # shared scope reaches every tool
        patched = plans[tool].dir_overrides[Path("skills/demo")][Path("SKILL.md")]
        expected = (
            "# Demo\n\n## Usage\nbase usage\n" + CHEAT_BLOCK + "\n\n## Reference\nsee docs\n"
        ).encode()
        assert patched == expected


def test_extension_targets_a_carrier_merged_plugin_file(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """Phase ordering pin: apply_extensions runs AFTER overlay_plugins, so an
    extension can patch a file the plugin itself carrier-merged into a shared
    skill dir in the same run."""
    repo = tmp_path / "repo"
    _write(repo / "src" / "user" / ".agents" / "skills" / "demo" / "SKILL.md", SKILL_BASE)
    plugin_root = tmp_path / "plugins" / "demo-plugin"
    _write(plugin_root / ".agents" / "skills" / "demo" / "cheats.md", "## Cheats\nraw\n")
    _write(
        plugin_root / ".agents" / "extensions" / "00.yaml",
        "target-file: skills/demo/cheats.md\n"
        "target-section: Cheats\n"
        "precision: append\n"
        "content: |\n  appended-after-merge\n",
    )
    plugin = GenericPluginAdapter(name="demo-plugin", source_path=plugin_root)

    plans = stage_and_transform(
        [Tool.CLAUDE], repo_root=repo, io=ScriptedIO(), ignore=ignore, plugins=[plugin]
    )

    patched = plans[Tool.CLAUDE].dir_overrides[Path("skills/demo")][Path("cheats.md")]
    assert patched == b"## Cheats\nraw\nappended-after-merge\n"

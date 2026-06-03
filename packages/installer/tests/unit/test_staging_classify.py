"""Unit tests for installer.core.staging.classify_file — C.1.

Each test pins a row of the bash classify_file() truth table
(scripts/install.sh:486-505) as mirrored onto FileKind.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import FileKind
from installer.core.staging import classify_file


def test_directory_classifies_as_dir(tmp_path: Path) -> None:
    skill = tmp_path / "my-skill"
    skill.mkdir()
    assert classify_file(skill, "skills") == FileKind.DIR


def test_settings_json_template(tmp_path: Path) -> None:
    f = tmp_path / "settings.json.template"
    f.touch()
    assert classify_file(f, None) == FileKind.SETTINGS_JSON


def test_jsonc_template(tmp_path: Path) -> None:
    f = tmp_path / "opencode.jsonc.template"
    f.touch()
    assert classify_file(f, None) == FileKind.JSONC


def test_toml_template_and_bare_toml(tmp_path: Path) -> None:
    tpl = tmp_path / "config.toml.template"
    bare = tmp_path / "config.toml"
    tpl.touch()
    bare.touch()
    assert classify_file(tpl, None) == FileKind.TOML
    assert classify_file(bare, None) == FileKind.TOML


def test_md_with_namespace_is_namespaced_md(tmp_path: Path) -> None:
    f = tmp_path / "do-the-thing.md"
    f.touch()
    assert classify_file(f, "commands") == FileKind.NAMESPACED_MD


def test_md_without_namespace_is_other(tmp_path: Path) -> None:
    f = tmp_path / "AGENTS.md"
    f.touch()
    assert classify_file(f, None) == FileKind.OTHER


def test_unknown_extension_is_other(tmp_path: Path) -> None:
    f = tmp_path / "notes.txt"
    f.touch()
    assert classify_file(f, "skills") == FileKind.OTHER

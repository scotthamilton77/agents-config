# src/user/.agents/skills/gate-triage/gate_triage_test.py
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import gate_triage as gt  # noqa: E402


# --- Task 5: load_config (spec §9 items 18-22) ---


def _write_cfg(tmp_path, body: str) -> Path:
    (tmp_path / "project-config.toml").write_text(body)
    return tmp_path


def test_config_overrides_replace_defaults(tmp_path):  # §9.18
    root = _write_cfg(tmp_path, "[completion-gate]\nheavy_min_files = 5\n")
    assert gt.load_config(root).heavy_min_files == 5


def test_absent_section_yields_defaults(tmp_path):  # §9.18
    root = _write_cfg(tmp_path, "[project]\nname = 'x'\n")
    assert gt.load_config(root) == gt.TriageConfig()


def test_trivial_max_loc_clamped_to_20(tmp_path):  # §9.19
    root = _write_cfg(tmp_path, "[completion-gate]\ntrivial_max_loc = 999\n")
    assert gt.load_config(root).trivial_max_loc == 20


def test_heavy_min_loc_below_trivial_max_rejected(tmp_path):  # §9.20
    root = _write_cfg(tmp_path, "[completion-gate]\nheavy_min_loc = 2\ntrivial_max_loc = 3\n")
    assert gt.load_config(root) == gt.TriageConfig()  # nonsensical ordering → defaults


def test_bad_types_fall_back_to_defaults(tmp_path):  # §9.21
    root = _write_cfg(tmp_path, "[completion-gate]\nheavy_min_files = -4\n")
    assert gt.load_config(root) == gt.TriageConfig()


def test_unknown_key_ignored_known_kept(tmp_path):  # §9.22
    root = _write_cfg(tmp_path, "[completion-gate]\nheavy_min_files = 6\nbogus = 1\n")
    assert gt.load_config(root).heavy_min_files == 6


def test_absent_file_yields_defaults(tmp_path):  # §9.18
    assert gt.load_config(tmp_path) == gt.TriageConfig()


# --- Task 6: classify_file (spec §9 item 10) ---


@pytest.mark.parametrize("path,expected", [
    ("README.md", gt.FileClass.DOCS), ("a.rst", gt.FileClass.DOCS),
    ("cfg.toml", gt.FileClass.CONFIG), ("s.yaml", gt.FileClass.CONFIG),
    (".gitignore", gt.FileClass.CONFIG),  # extensionless dotfile
    ("main.py", gt.FileClass.CODE), ("run.sh", gt.FileClass.CODE),
    ("Makefile", gt.FileClass.CODE),  # unknown/no ext → CODE (fail toward scrutiny)
])
def test_classify_file(path, expected):  # §9.10
    assert gt.classify_file(path) == expected

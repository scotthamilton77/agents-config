# src/user/.agents/skills/gate-triage/gate_triage_test.py
import sys
from pathlib import Path

import pathspec
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


# --- Task 7: critical_hits (spec §9 items 11-16, §9.8-9.9) ---


def _marker(folder: str, *patterns: str) -> gt.CriticalMarker:
    spec = pathspec.PathSpec.from_lines("gitignore", patterns)
    return gt.CriticalMarker(folder=folder, spec=spec)


def _cf(path, status="M", old_path=None, loc=1):
    return gt.ChangedFile(path=path, old_path=old_path, loc_changed=loc, status=status)


def test_subtree_scoping_and_anchoring():  # §9.11
    m = _marker("src/auth", "*.py")
    hits = gt.critical_hits((_cf("src/auth/token.py"), _cf("src/auth/sub/x.py"),
                             _cf("src/other/token.py")), (m,))
    hit_paths = {h.path for h in hits}
    assert hit_paths == {"src/auth/token.py", "src/auth/sub/x.py"}


def test_nested_and_ancestor_markers_union():  # §9.12
    root = _marker("", "src/**")
    nested = _marker("src/auth", "*.py")
    hits = gt.critical_hits((_cf("docs/x.md"), _cf("src/auth/a.py")), (root, nested))
    assert {h.path for h in hits} == {"src/auth/a.py"}  # a.py hit; both markers union, no shadow


def test_negation_within_a_marker():  # §9.13
    m = _marker("src", "**/*.py", "!**/generated.py")
    hits = gt.critical_hits((_cf("src/a.py"), _cf("src/generated.py")), (m,))
    assert {h.path for h in hits} == {"src/a.py"}


def test_hit_carries_provenance():  # §9.14
    m = _marker("src/auth", "*.py")
    (hit,) = gt.critical_hits((_cf("src/auth/token.py"),), (m,))
    assert hit.marker == "src/auth/.critical-paths" and hit.pattern  # non-empty


def test_rename_out_and_into_marked_subtree():  # §9.15
    m = _marker("src/auth", "*.py")
    out = _cf("src/other/token.py", status="R", old_path="src/auth/token.py")
    into = _cf("src/auth/new.py", status="R", old_path="src/other/new.py")
    within = _cf("src/auth/b.py", status="R", old_path="src/auth/a.py")
    hits = gt.critical_hits((out, into, within), (m,))
    assert len(hits) == 3  # out (old_path), into (path), within (one hit, not two)
    assert sum(1 for h in hits if h.path == "src/auth/b.py") == 1


def test_delete_from_marked_subtree():  # §9.16
    m = _marker("src/auth", "*.py")
    (hit,) = gt.critical_hits((_cf("src/auth/gone.py", status="D"),), (m,))
    assert hit.path == "src/auth/gone.py"


def test_policy_input_is_always_a_hit_without_markers():  # §9.8, §9.9
    hits = gt.critical_hits((_cf("project-config.toml"), _cf("src/x/.critical-paths")), ())
    assert {h.path for h in hits} == {"project-config.toml", "src/x/.critical-paths"}


# --- Task 8: compute_tier (spec §9 items 1-9) ---


def _facts(*files, new_deps=False):
    return gt.DiffFacts(files=tuple(files), new_deps=new_deps, base_ref="main")


CFG = gt.TriageConfig()  # files=8, loc=400, subsystems=3, trivial=3


def test_single_trivial_file_is_skip():  # §9.1
    assert gt.compute_tier(_facts(_cf("a.py", loc=3)), (), CFG) == gt.Tier.SKIP
    assert gt.compute_tier(_facts(_cf("a.py", loc=4)), (), CFG) == gt.Tier.SERIAL


def test_critical_hit_beats_skip():  # §9.2, §9.7
    hit = (gt.CriticalHit("a.py", "src/.critical-paths", "*.py"),)
    assert gt.compute_tier(_facts(_cf("a.py", loc=1)), hit, CFG) == gt.Tier.HEAVY


def test_two_trivial_files_not_skip():  # §9.3
    assert gt.compute_tier(_facts(_cf("a.py", loc=1), _cf("b.py", loc=1)), (), CFG) == gt.Tier.SERIAL


def test_mixed_small_multifile_is_serial():  # §9.4
    assert gt.compute_tier(_facts(_cf("a.md", loc=5), _cf("b.py", loc=5)), (), CFG) == gt.Tier.SERIAL


def test_each_quant_threshold_trips_heavy_at_boundary():  # §9.5
    files_min = tuple(_cf(f"d{i}/f.py", loc=1) for i in range(8))  # 8 files, 8 subsystems
    assert gt.compute_tier(_facts(*files_min), (), CFG) == gt.Tier.HEAVY
    loc_min = (_cf("a.py", loc=400),)
    assert gt.compute_tier(_facts(*loc_min), (), CFG) == gt.Tier.HEAVY
    subs_min = tuple(_cf(f"d{i}/f.py", loc=1) for i in range(3))  # 3 subsystems
    assert gt.compute_tier(_facts(*subs_min), (), CFG) == gt.Tier.HEAVY


def test_new_deps_trips_heavy():  # §9.6
    assert gt.compute_tier(_facts(_cf("pyproject.toml", loc=1), new_deps=True), (), CFG) == gt.Tier.HEAVY

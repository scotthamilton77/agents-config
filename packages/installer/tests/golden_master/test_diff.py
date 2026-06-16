"""Unit tests for the golden-master tree differ (``tests.golden_master._diff``).

Fast, pure-function tests — they carry no ``golden_master`` marker and run in the
default suite. The slow subprocess scenarios live in ``test_parity.py``.
"""

from __future__ import annotations

from pathlib import Path

from tests.golden_master._diff import (
    diff_trees,
    json_semantically_equal,
    normalize_relpath,
)


def _write(path: Path, data: bytes, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o755 if executable else 0o644)


def test_json_equal_ignores_key_order() -> None:
    assert json_semantically_equal(b'{"a": 1, "b": 2}', b'{"b": 2, "a": 1}')


def test_json_equal_ignores_whitespace_and_indentation() -> None:
    assert json_semantically_equal(b'{"a":1}', b'{\n  "a": 1\n}\n')


def test_json_unequal_on_value_difference() -> None:
    assert not json_semantically_equal(b'{"a": 1}', b'{"a": 2}')


def test_json_unparseable_input_is_not_equal() -> None:
    assert not json_semantically_equal(b"<<not json>>", b"<<not json>>")


def test_json_array_order_is_ignored() -> None:
    # json_union unions arrays in first-seen order; bash's jq `unique` sorts them.
    # Same elements, different order is an accepted divergence (settings arrays).
    assert json_semantically_equal(b'{"deny": [1, 2, 3]}', b'{"deny": [3, 1, 2]}')


def test_json_array_with_object_elements_order_ignored() -> None:
    a = b'{"hooks": [{"m": "A"}, {"m": "B"}]}'
    b = b'{"hooks": [{"m": "B"}, {"m": "A"}]}'
    assert json_semantically_equal(a, b)


def test_json_array_element_difference_is_still_caught() -> None:
    # Order-insensitive must still catch a real add/drop (ground lost/gained).
    assert not json_semantically_equal(b'{"deny": [1, 2]}', b'{"deny": [1, 3]}')


def test_normalize_collapses_in_place_backup_timestamp() -> None:
    assert normalize_relpath("skills/foo.md.backup-20260615-120000") == "skills/foo.md.backup-<TS>"


def test_normalize_collapses_namespaced_backup_dir_entry() -> None:
    assert (
        normalize_relpath("skills-backup/foo.md.backup-20260615-235959")
        == "skills-backup/foo.md.backup-<TS>"
    )


def test_normalize_leaves_non_backup_path_untouched() -> None:
    assert normalize_relpath("skills/foo.md") == "skills/foo.md"


def test_identical_trees_are_parity(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "x.txt", b"hello")
    _write(b / "x.txt", b"hello")
    result = diff_trees(a, b)
    assert result.is_parity(), result.render()


def test_file_only_in_a_breaks_parity(tmp_path: Path) -> None:
    # The hooks/ case: bash (a) stages a file the Python installer (b) omits.
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "hooks/ruff-postedit.py", b"#!/usr/bin/env python3\n")
    b.mkdir()
    result = diff_trees(a, b)
    assert not result.is_parity()
    assert "hooks/ruff-postedit.py" in result.only_in_a


def test_file_only_in_b_breaks_parity(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    _write(b / "extra.md", b"surprise")
    result = diff_trees(a, b)
    assert "extra.md" in result.only_in_b


def test_json_compared_semantically_not_bytewise(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "settings.json", b'{"a": 1, "b": 2}')
    _write(b / "settings.json", b'{\n  "b": 2,\n  "a": 1\n}\n')
    result = diff_trees(a, b)
    assert result.is_parity(), result.render()


def test_non_json_compared_bytewise(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "note.md", b"alpha")
    _write(b / "note.md", b"beta")
    result = diff_trees(a, b)
    assert "note.md" in result.content_mismatch


def test_backup_timestamp_difference_is_not_a_diff(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "foo.md.backup-20260615-120000", b"old")
    _write(b / "foo.md.backup-20260615-120005", b"old")
    result = diff_trees(a, b)
    assert result.is_parity(), result.render()


def test_executable_bit_mismatch_is_detected(tmp_path: Path) -> None:
    # 8.7 parity: bash chmod +x's hook scripts; the Python installer must too.
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "hooks/h.py", b"x", executable=True)
    _write(b / "hooks/h.py", b"x", executable=False)
    result = diff_trees(a, b)
    assert "hooks/h.py" in result.mode_mismatch


def test_namespace_dead_marker_only_in_a_is_exempt(tmp_path: Path) -> None:
    # Class 2: bash deploys a namespace-level AGENTS.md (source-dir dev docs);
    # the Python installer correctly omits it (DEAD_MARKERS). The harness must
    # not flag bash's known-spurious surplus.
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / ".claude/skills/AGENTS.md", b"dev docs for the skills source dir")
    _write(a / ".claude/skills/real-skill.md", b"x")
    _write(b / ".claude/skills/real-skill.md", b"x")
    result = diff_trees(a, b)
    assert result.is_parity(), result.render()


def test_tool_root_instruction_file_is_not_exempt(tmp_path: Path) -> None:
    # Guard against over-exempting: the real tool-root AGENTS.md still compares.
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / ".claude/AGENTS.md", b"alpha")
    _write(b / ".claude/AGENTS.md", b"beta")
    result = diff_trees(a, b)
    assert ".claude/AGENTS.md" in result.content_mismatch

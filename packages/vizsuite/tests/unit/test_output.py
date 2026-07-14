"""`.viz/` sidecar bootstrap: idempotent dir creation + canonical managed ignore."""

from __future__ import annotations

from pathlib import Path

from vizsuite.output import ensure_viz_dir, ensure_viz_gitignore


def test_creates_out_dir_and_ignores_the_managed_set(tmp_path: Path):
    out = ensure_viz_dir(tmp_path)

    assert out == tmp_path / ".viz" / "out"
    assert out.is_dir()
    # Both managed entries, in canonical (alphabetical) order.
    assert (tmp_path / ".viz" / ".gitignore").read_text(encoding="utf-8").splitlines() == ["lock", "out/"]


def test_idempotent_no_duplicate_ignore_lines(tmp_path: Path):
    ensure_viz_dir(tmp_path)
    first = (tmp_path / ".viz" / ".gitignore").read_text(encoding="utf-8")

    ensure_viz_dir(tmp_path)
    second = (tmp_path / ".viz" / ".gitignore").read_text(encoding="utf-8")

    assert first == second == "lock\nout/\n"


def test_preserves_existing_gitignore_content(tmp_path: Path):
    viz = tmp_path / ".viz"
    viz.mkdir()
    (viz / ".gitignore").write_text("# custom\nscratch/\n", encoding="utf-8")

    ensure_viz_dir(tmp_path)

    lines = (viz / ".gitignore").read_text(encoding="utf-8").splitlines()
    # Existing lines preserved and never reordered; managed entries appended.
    assert lines == ["# custom", "scratch/", "lock", "out/"]


def test_no_op_when_managed_set_already_present(tmp_path: Path):
    viz = tmp_path / ".viz"
    viz.mkdir()
    (viz / ".gitignore").write_text("lock\nout/\n", encoding="utf-8")

    ensure_viz_dir(tmp_path)

    assert (viz / ".gitignore").read_text(encoding="utf-8") == "lock\nout/\n"


def test_appends_only_the_missing_managed_entry(tmp_path: Path):
    viz = tmp_path / ".viz"
    viz.mkdir()
    # A pre-existing partial file (only `out/`): the absent `lock` is appended,
    # existing content is preserved and never reordered.
    (viz / ".gitignore").write_text("out/\n", encoding="utf-8")

    ensure_viz_gitignore(viz)

    assert (viz / ".gitignore").read_text(encoding="utf-8") == "out/\nlock\n"

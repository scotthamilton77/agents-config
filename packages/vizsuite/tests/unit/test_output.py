"""`.viz/` sidecar bootstrap: idempotent dir creation + portable `out/` ignore."""

from __future__ import annotations

from pathlib import Path

from vizsuite.output import ensure_viz_dir


def test_creates_out_dir_and_ignores_it(tmp_path: Path):
    out = ensure_viz_dir(tmp_path)

    assert out == tmp_path / ".viz" / "out"
    assert out.is_dir()
    assert (tmp_path / ".viz" / ".gitignore").read_text().splitlines() == ["out/"]


def test_idempotent_no_duplicate_ignore_line(tmp_path: Path):
    ensure_viz_dir(tmp_path)
    ensure_viz_dir(tmp_path)

    assert (tmp_path / ".viz" / ".gitignore").read_text().count("out/") == 1


def test_preserves_existing_gitignore_content(tmp_path: Path):
    viz = tmp_path / ".viz"
    viz.mkdir()
    (viz / ".gitignore").write_text("# custom\nscratch/\n")

    ensure_viz_dir(tmp_path)

    lines = (viz / ".gitignore").read_text().splitlines()
    assert lines == ["# custom", "scratch/", "out/"]


def test_no_op_when_out_already_ignored(tmp_path: Path):
    viz = tmp_path / ".viz"
    viz.mkdir()
    (viz / ".gitignore").write_text("out/\n")

    ensure_viz_dir(tmp_path)

    assert (viz / ".gitignore").read_text() == "out/\n"

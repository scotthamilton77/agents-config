"""Unit tests for installer.core.templates — B.4 (DYNAMIC-INCLUDE file form).

Each test pins a behaviour the B.4 story contract requires
(docs/specs/2026-05-31-w1qls.2.4-dynamic-include-file-form.md). The behavioural
reference is the bash installer's flatten_agents_md (scripts/install.sh).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.model import AllRulesInclude, FileInclude
from installer.core.templates import flatten_template, parse_directive

# ───────────────────────── parse_directive ─────────────────────────


def test_file_marker_is_recognised() -> None:
    """
    Given a line that is exactly a file-form DYNAMIC-INCLUDE marker
    When parse_directive is called
    Then it returns a FileInclude carrying the marker's path.
    """
    assert parse_directive("<!-- DYNAMIC-INCLUDE: rules/foo.md -->") == FileInclude(
        path=Path("rules/foo.md")
    )


def test_all_rules_marker_is_recognised() -> None:
    """
    Given the ALL-RULES marker line
    When parse_directive is called
    Then it returns AllRulesInclude (recognition seam for story C.2).
    """
    assert parse_directive("<!-- DYNAMIC-INCLUDE-ALL-RULES -->") == AllRulesInclude()


def test_prose_line_is_not_a_directive() -> None:
    """
    Given an ordinary prose line
    When parse_directive is called
    Then it returns None.
    """
    assert parse_directive("This is just a normal sentence.") is None


def test_marker_with_leading_whitespace_is_not_a_directive() -> None:
    """
    Given a marker preceded by whitespace (not anchored to column 0)
    When parse_directive is called
    Then it returns None — the bash patterns anchor on ^...$.
    """
    assert parse_directive("    <!-- DYNAMIC-INCLUDE: rules/foo.md -->") is None


def test_named_rules_form_is_not_recognised() -> None:
    """
    Given the deferred named-RULES form (story C.3, absent from the model)
    When parse_directive is called
    Then it returns None rather than being mistaken for the file form.
    """
    assert parse_directive("<!-- DYNAMIC-INCLUDE-RULES: a, b -->") is None


def test_empty_path_marker_is_not_a_directive() -> None:
    """
    Given a file marker with an empty path
    When parse_directive is called
    Then it returns None — mirrors the bash `-n` non-empty guard.
    """
    assert parse_directive("<!-- DYNAMIC-INCLUDE:  -->") is None


# ───────────────────────── flatten_template ─────────────────────────


def test_single_marker_resolves_to_inlined_content(tmp_path: Path) -> None:
    """
    Given a template whose only line is a file marker
    When flatten_template runs against a base dir containing that file
    Then the output is the referenced file's verbatim content (AC1).
    """
    (tmp_path / "inc.md").write_text("INCLUDED BODY\n", encoding="utf-8")
    io = ScriptedIO()

    result = flatten_template("<!-- DYNAMIC-INCLUDE: inc.md -->\n", base_dir=tmp_path, io=io)

    assert result == "INCLUDED BODY\n"


def test_markers_and_prose_assemble_in_order(tmp_path: Path) -> None:
    """
    Given a template interleaving prose and two file markers
    When flatten_template runs
    Then each marker is replaced in place and prose is preserved in order.
    """
    (tmp_path / "a.md").write_text("AAA\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("BBB\n", encoding="utf-8")
    template = (
        "header\n<!-- DYNAMIC-INCLUDE: a.md -->\nmiddle\n<!-- DYNAMIC-INCLUDE: b.md -->\nfooter\n"
    )

    result = flatten_template(template, base_dir=tmp_path, io=ScriptedIO())

    assert result == "header\nAAA\nmiddle\nBBB\nfooter\n"


def test_missing_file_warns_and_leaves_line_empty(tmp_path: Path) -> None:
    """
    Given a marker whose target file does not exist
    When flatten_template runs
    Then it does not raise, emits a warning, and drops the marker line (AC2).
    """
    io = ScriptedIO()

    result = flatten_template(
        "before\n<!-- DYNAMIC-INCLUDE: missing.md -->\nafter\n",
        base_dir=tmp_path,
        io=io,
    )

    assert result == "before\nafter\n"
    warnings = [e for e in io.transcript if e.channel == "warn"]
    assert len(warnings) == 1
    assert "missing.md" in warnings[0].message


def test_non_directive_lines_pass_through_unchanged(tmp_path: Path) -> None:
    """
    Given a template with no markers
    When flatten_template runs
    Then the content is returned byte-for-byte (AC3).
    """
    template = "line one\nline two\n\nline four\n"

    result = flatten_template(template, base_dir=tmp_path, io=ScriptedIO())

    assert result == template


def test_trailing_newline_is_preserved_when_present(tmp_path: Path) -> None:
    """
    Given a template ending in a newline
    When flatten_template runs
    Then the trailing newline is preserved (AC4).
    """
    result = flatten_template("alpha\nbeta\n", base_dir=tmp_path, io=ScriptedIO())

    assert result == "alpha\nbeta\n"


def test_absent_trailing_newline_is_not_invented(tmp_path: Path) -> None:
    """
    Given a template that does not end in a newline
    When flatten_template runs
    Then no trailing newline is added (AC4, negative case).
    """
    result = flatten_template("alpha\nbeta", base_dir=tmp_path, io=ScriptedIO())

    assert result == "alpha\nbeta"


def test_included_file_without_trailing_newline_glues_to_next_line(
    tmp_path: Path,
) -> None:
    """
    Given an included file with no trailing newline, followed by a prose line
    When flatten_template runs
    Then the included content abuts the next line with no injected separator —
    matching `cat file >> output` (the marker line's own newline is consumed).
    """
    (tmp_path / "frag.md").write_text("FRAGMENT", encoding="utf-8")  # no newline

    result = flatten_template(
        "<!-- DYNAMIC-INCLUDE: frag.md -->\nafter\n",
        base_dir=tmp_path,
        io=ScriptedIO(),
    )

    assert result == "FRAGMENTafter\n"


def test_all_rules_empty_dir_warns_and_expands_blank(tmp_path: Path) -> None:
    """
    Given an empty rules_dir (no *.md files)
    When flatten_template runs with the ALL-RULES marker
    Then it emits a warning and expands to the empty string.
    """
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    io = ScriptedIO()

    result = flatten_template(
        "before\n<!-- DYNAMIC-INCLUDE-ALL-RULES -->\nafter\n",
        base_dir=tmp_path,
        rules_dir=rules_dir,
        io=io,
    )

    assert result == "before\nafter\n"
    warnings = [e for e in io.transcript if e.channel == "warn"]
    assert len(warnings) == 1
    assert "ALL-RULES" in warnings[0].message


def test_all_rules_none_rules_dir_warns_and_expands_blank(tmp_path: Path) -> None:
    """
    Given rules_dir=None (no rules dir provided)
    When flatten_template runs with the ALL-RULES marker
    Then it emits a warning and expands to the empty string.
    """
    io = ScriptedIO()

    result = flatten_template(
        "<!-- DYNAMIC-INCLUDE-ALL-RULES -->\n",
        base_dir=tmp_path,
        rules_dir=None,
        io=io,
    )

    assert result == ""
    warnings = [e for e in io.transcript if e.channel == "warn"]
    assert len(warnings) == 1
    assert "ALL-RULES" in warnings[0].message


def test_all_rules_directory_named_md_is_skipped(tmp_path: Path) -> None:
    """
    Given a rules_dir containing a directory whose name ends in .md
    When flatten_template runs with the ALL-RULES marker
    Then the directory is skipped (not crashed) — mirrors bash `find -type f`.
    """
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "real.md").write_text("REAL RULE\n", encoding="utf-8")
    (rules_dir / "weird.md").mkdir()  # directory named *.md

    result = flatten_template(
        "<!-- DYNAMIC-INCLUDE-ALL-RULES -->\n",
        base_dir=tmp_path,
        rules_dir=rules_dir,
        io=ScriptedIO(),
    )

    assert result == "REAL RULE\n"


def test_all_rules_expands_to_sorted_concatenation(tmp_path: Path) -> None:
    """
    Given two rule files in rules_dir (out of lexicographic order on disk)
    When flatten_template runs with the ALL-RULES marker
    Then both are concatenated in lexicographic filename order, joined by \\n---\\n.
    """
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "b_rule.md").write_text("RULE B\n", encoding="utf-8")
    (rules_dir / "a_rule.md").write_text("RULE A\n", encoding="utf-8")

    result = flatten_template(
        "<!-- DYNAMIC-INCLUDE-ALL-RULES -->\n",
        base_dir=tmp_path,
        rules_dir=rules_dir,
        io=ScriptedIO(),
    )

    assert result == "RULE A\n\n---\nRULE B\n"

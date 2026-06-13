"""Prompt-template loader (§5 prompt templates).

Each contract's prompt lives in ``agent/prompts/<contract>.tmpl``, rendered with
a flat string mapping. ``PRGROOM_PROMPTS_DIR`` lets a power user override a
shipped template per-filename. The tests pin: shipped templates load and render
with no leftover placeholders, the override dir wins when it carries a matching
filename (and falls through to shipped when it does not), and an unresolved
placeholder is a loud error rather than a silent ``{hole}`` in the prompt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from prgroom.agent.prompt_loader import (
    PROMPTS_DIR_ENV,
    PromptTemplate,
    UnresolvedPlaceholderError,
    load_prompt,
)


def test_loads_shipped_cluster_template() -> None:
    tmpl = load_prompt("cluster")
    assert isinstance(tmpl, PromptTemplate)
    assert tmpl.text  # shipped template is non-empty


def test_loads_shipped_fix_template() -> None:
    assert load_prompt("fix").text


# The runner-built payload-delivery section (file mode here; ollama gets inline).
_SECTION = "from this file:\n\n  /var/run/prgroom/in.json"


def test_shipped_cluster_template_renders_with_every_placeholder_filled() -> None:
    # The shipped template embeds literal JSON ({{ }} -> { }), so braces survive
    # by design. The invariant §5 cares about is that no NAMED {placeholder} is
    # left unresolved — render must not raise and must substitute the field values.
    rendered = load_prompt("cluster").render({"contract_version": "1", "input_section": _SECTION})
    assert "{contract_version}" not in rendered
    assert "{input_section}" not in rendered
    assert _SECTION in rendered


def test_shipped_fix_template_renders_with_every_placeholder_filled() -> None:
    rendered = load_prompt("fix").render({"contract_version": "1", "input_section": _SECTION})
    assert "{contract_version}" not in rendered
    assert "{input_section}" not in rendered
    assert _SECTION in rendered


def test_override_dir_wins_for_matching_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "prompts"
    override.mkdir()
    (override / "cluster.tmpl").write_text("OVERRIDDEN {input_path}", encoding="utf-8")
    monkeypatch.setenv(PROMPTS_DIR_ENV, str(override))

    rendered = load_prompt("cluster").render({"input_path": "/x"})
    assert rendered == "OVERRIDDEN /x"


def test_override_dir_falls_through_to_shipped_when_filename_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An override dir that does NOT carry fix.tmpl must not hide the shipped one.
    override = tmp_path / "prompts"
    override.mkdir()
    (override / "cluster.tmpl").write_text("only cluster here {input_path}", encoding="utf-8")
    monkeypatch.setenv(PROMPTS_DIR_ENV, str(override))

    assert load_prompt("fix").text  # shipped fix template still resolves


def test_render_raises_on_unresolved_placeholder() -> None:
    tmpl = PromptTemplate(name="t", text="hello {missing}")
    with pytest.raises(UnresolvedPlaceholderError):
        tmpl.render({"present": "x"})


def test_render_substitutes_provided_placeholders() -> None:
    tmpl = PromptTemplate(name="t", text="a={a} b={b}")
    assert tmpl.render({"a": "1", "b": "2"}) == "a=1 b=2"


def test_literal_braces_are_escaped_and_survive_render() -> None:
    # A template that needs a literal brace (e.g. showing JSON) doubles it; the
    # render must collapse {{ -> { without treating it as a placeholder.
    tmpl = PromptTemplate(name="t", text='json: {{ "k": {v} }}')
    assert tmpl.render({"v": "1"}) == 'json: { "k": 1 }'

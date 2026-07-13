"""The `--format human` renderer: recursive key/value indentation to stderr."""

from __future__ import annotations

from io import StringIO

from vizsuite.envelope import JsonValue
from vizsuite.render import render_human


def _render(envelope: dict[str, JsonValue]) -> str:
    out = StringIO()
    render_human(envelope, out)
    return out.getvalue()


def test_ok_envelope_renders_nested_data():
    text = _render(
        {
            "ok": True,
            "data": {
                "pr": 1,
                "flag": True,
                "missing": None,
                "nested": {"a": 1},
                "items": [1, 2],
                "empty_dict": {},
                "empty_list": [],
            },
        }
    )

    assert text.startswith("ok\n")
    assert "pr: 1" in text
    assert "flag: true" in text
    assert "missing: null" in text
    assert "nested:\n" in text
    assert "  a: 1" in text
    assert "items:\n" in text
    assert "empty_dict: (empty)" in text
    assert "empty_list: (empty)" in text


def test_error_envelope_renders_error_section():
    text = _render({"ok": False, "error": {"code": "E_USAGE", "message": "bad"}})

    assert text.startswith("error\n")
    assert "code: E_USAGE" in text
    assert "message: bad" in text


def test_top_level_empty_dict_renders_empty_marker():
    assert _render({"ok": True, "data": {}}) == "ok\n(empty)\n"


def test_list_of_dicts_scalars_and_empties():
    text = _render({"ok": True, "data": [{"x": 1}, "scalar", {}, []]})

    assert "-\n" in text  # a non-empty dict item
    assert "  x: 1" in text  # its keys render one indent level under the list item
    assert "- scalar" in text  # a scalar item
    assert "- (empty)" in text  # empty dict/list items


def test_top_level_empty_list_renders_empty_marker():
    assert _render({"ok": True, "data": []}) == "ok\n(empty)\n"


def test_top_level_scalar_value():
    assert _render({"ok": True, "data": "hello"}) == "ok\nhello\n"

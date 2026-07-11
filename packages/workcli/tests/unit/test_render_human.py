"""`render_human` — the generic `--format human` renderer (unit-level).

`test_format_human.py` covers the CLI-level contract (stdout untouched,
stderr non-empty); this file exercises `render_human`'s own branches
directly: nested dicts/lists, empty collections, and scalar leaves.
"""

from __future__ import annotations

from io import StringIO

from workcli.render import render_human


def test_renders_a_nested_success_envelope_with_indentation() -> None:
    out = StringIO()

    render_human(
        {
            "protocol": "1.0",
            "ok": True,
            "data": {"id": "x.1", "labels": ["a", "b"], "deps": []},
            "error": None,
        },
        out,
    )

    text = out.getvalue()
    assert text.startswith("ok\n")
    assert "id: x.1\n" in text
    assert "labels:\n" in text
    assert "  - a\n" in text
    assert "  - b\n" in text
    assert "deps: (empty)\n" in text


def test_renders_a_failure_envelope_with_error_detail() -> None:
    out = StringIO()

    render_human(
        {
            "protocol": "1.0",
            "ok": False,
            "data": None,
            "error": {
                "code": "E_NOT_FOUND",
                "message": "no such item",
                "detail": {"id": "bogus"},
            },
        },
        out,
    )

    text = out.getvalue()
    assert text.startswith("error\n")
    assert "code: E_NOT_FOUND\n" in text
    assert "message: no such item\n" in text
    assert "detail:\n" in text
    assert "id: bogus\n" in text


def test_renders_null_and_boolean_scalars_lowercase() -> None:
    out = StringIO()

    render_human({"protocol": "1.0", "ok": True, "data": None, "error": None}, out)

    assert "(empty)" not in out.getvalue()
    # `data` is `None`, not a dict/list -- the top-level value itself renders
    # as the bare scalar "null", not a key: value line (there is no key at
    # the top level).
    assert out.getvalue() == "ok\nnull\n"


def test_renders_a_list_of_nested_dicts_with_dash_markers() -> None:
    out = StringIO()

    render_human({"ok": True, "data": {"items": [{"id": "a"}, {"id": "b"}]}, "error": None}, out)

    text = out.getvalue()
    assert "items:\n" in text
    assert "  -\n" in text
    assert "    id: a\n" in text
    assert "    id: b\n" in text


def test_renders_an_empty_top_level_dict_as_empty_marker() -> None:
    out = StringIO()

    render_human({"ok": True, "data": {}, "error": None}, out)

    assert out.getvalue() == "ok\n(empty)\n"


def test_renders_an_empty_top_level_list_as_empty_marker() -> None:
    out = StringIO()

    render_human({"ok": True, "data": [], "error": None}, out)

    assert out.getvalue() == "ok\n(empty)\n"


def test_renders_an_empty_nested_list_item_with_a_dash_empty_marker() -> None:
    out = StringIO()

    render_human({"ok": True, "data": {"items": [[]]}, "error": None}, out)

    assert out.getvalue() == "ok\nitems:\n  - (empty)\n"


def test_renders_boolean_scalars_lowercase() -> None:
    out = StringIO()

    render_human({"ok": True, "data": {"raw": True, "synced": False}, "error": None}, out)

    text = out.getvalue()
    assert "raw: true\n" in text
    assert "synced: false\n" in text

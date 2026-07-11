"""`--format human` — a generic, boring renderer for direct human use.

Renders the envelope's `data` (on success) or `error` (on failure) to
**stderr only** — stdout always carries the JSON envelope regardless of
`--format` (spec §4); this module never touches stdout and never raises on
malformed input, since a rendering bug must never break the stdout
invariant it sits beside.

No colors, no third-party deps: recursive `key: value` indentation over
whatever JSON-shaped value the envelope carries.
"""

from __future__ import annotations

from typing import TextIO

from workcli.envelope import JsonValue

_INDENT = "  "


def _render_value(value: JsonValue, *, indent: int, out: TextIO) -> None:
    prefix = _INDENT * indent
    if isinstance(value, dict):
        if not value:
            out.write(f"{prefix}(empty)\n")
            return
        for key, nested in value.items():
            if isinstance(nested, dict | list):
                if not nested:
                    out.write(f"{prefix}{key}: (empty)\n")
                else:
                    out.write(f"{prefix}{key}:\n")
                    _render_value(nested, indent=indent + 1, out=out)
            else:
                out.write(f"{prefix}{key}: {_render_scalar(nested)}\n")
    elif isinstance(value, list):
        if not value:
            out.write(f"{prefix}(empty)\n")
            return
        for item in value:
            if isinstance(item, dict | list):
                if not item:
                    out.write(f"{prefix}- (empty)\n")
                else:
                    out.write(f"{prefix}-\n")
                    _render_value(item, indent=indent + 1, out=out)
            else:
                out.write(f"{prefix}- {_render_scalar(item)}\n")
    else:
        out.write(f"{prefix}{_render_scalar(value)}\n")


def _render_scalar(value: JsonValue) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_human(envelope: dict[str, JsonValue], out: TextIO) -> None:
    """Render an already-built envelope's `data` or `error` to `out` (stderr).

    Called only when `--format human` is set, in addition to (never instead
    of) writing the JSON envelope to stdout.
    """
    if envelope.get("ok"):
        out.write("ok\n")
        _render_value(envelope.get("data"), indent=0, out=out)
    else:
        out.write("error\n")
        _render_value(envelope.get("error"), indent=0, out=out)

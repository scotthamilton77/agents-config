"""`GrindError` -- the one typed command-error exception every verb raises for
a boundary failure (malformed payload, refused `create`). `cli.py` is the only
catcher: it turns this into the `{"ok": false, "error": {...}}` envelope with
a non-zero exit code (spec: "a malformed payload is a command error, exit
code != 0, nothing appended"). An *illegal-but-well-formed* event is never a
`GrindError` -- that's the fold's accept-and-flag anomaly, exit 0.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GrindError(Exception):
    message: str

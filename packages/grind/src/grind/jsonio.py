"""Strict JSON decoding at grind's boundaries.

Python's stdlib `json.loads` accepts three non-standard constants -- `NaN`,
`Infinity`, and `-Infinity` -- that RFC 8259 forbids, and `json.dumps` re-emits
them by default. A grind whose seed or `--json` payload smuggled one in would
propagate it into `events.jsonl`, `state.json`, and the stdout envelope, which
standards-compliant JSON consumers cannot parse. Every grind decode boundary
funnels through `loads` here so a non-finite constant is refused exactly like
any other malformed input; the matching `json.dumps` callers pass
`allow_nan=False` as defense in depth on the write side.
"""

from __future__ import annotations

import json
from typing import NoReturn

from grind.model import JsonValue


class NonFiniteJsonError(ValueError):
    """A JSON document contained a non-finite constant (`NaN`, `Infinity`, or
    `-Infinity`) -- non-standard JSON grind refuses at the decode boundary."""


def _reject_non_finite(constant: str) -> NoReturn:
    raise NonFiniteJsonError(f"non-finite JSON constant {constant!r} is not permitted")


def loads(text: str) -> JsonValue:
    """`json.loads` that rejects the non-standard non-finite constants."""
    return json.loads(text, parse_constant=_reject_non_finite)  # type: ignore[no-any-return]

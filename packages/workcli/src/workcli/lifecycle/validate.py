"""Shared field validation for `create` and `discover` -- noun aliases,
priority notation, and folding independent field failures into one envelope.

Both lifecycle verbs mint through the same noun vocabulary (`resolve_noun`)
and accept the same priority notations; this module is their single shared
implementation so the two verbs cannot drift apart on either rule. `create`
and `discover` each own their own required/optional and error-code framing
around these primitives -- that framing differs by verb (a missing priority
is `E_TRIAGE_INCOMPLETE` for `discover`, simply omitted for `create`), so it
stays in each verb's own module.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import cast

from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle.nouns import Noun, resolve_noun

_PRIORITY_RE = re.compile(r"^P[0-4]$")
_BARE_PRIORITY_RE = re.compile(r"^[0-4]$")


def validate_noun(value: str, choices: Sequence[Noun] = tuple(Noun)) -> Noun:
    """Resolve `value` to a `Noun` in `choices`, accepting aliases too.

    Raises `E_USAGE` (field `"noun"`) naming `choices` when `value` is
    neither a canonical noun value, a known alias, nor in `choices` --
    the single validator behind both `create <noun>` (all nouns) and
    `discover --noun` (`LEAF_NOUNS` only).
    """
    noun = resolve_noun(value)
    if noun is not None and noun in choices:
        return noun
    raise WorkError(
        ErrorCode.USAGE,
        f"invalid choice: {value!r} (choose from {', '.join(n.value for n in choices)})",
        detail={"field": "noun"},
    )


def normalize_priority(value: str) -> str:
    """A bare digit ('2') normalizes to the canonical 'P2' notation.

    Nothing else about the value is ambiguous -- only the notation was ever
    rejected -- so anything not matching the bare-digit shape passes through
    unchanged for `validate_priority` to accept or reject as before.
    """
    if _BARE_PRIORITY_RE.match(value):
        return f"P{value}"
    return value


def validate_priority(value: str, *, code: ErrorCode = ErrorCode.USAGE) -> str:
    """Normalize then validate P0-P4; raises `code` (field `"priority"`) on failure.

    `code` lets each call site pick its own error-code framing (`discover`
    raises `E_TRIAGE_INCOMPLETE` for a malformed priority; `create` raises
    plain `E_USAGE`) over the one shared notation rule.
    """
    normalized = normalize_priority(value)
    if not _PRIORITY_RE.match(normalized):
        raise WorkError(
            code, f"priority must be one of P0-P4, got {value!r}", {"field": "priority"}
        )
    return normalized


def combine_errors(errors: Sequence[WorkError]) -> WorkError:
    """Fold 2+ independent field failures into one well-formed error.

    `message` and `detail.errors` preserve every folded failure's own
    message and code verbatim. The top-level `code` is the first non-`E_USAGE`
    code among the folded failures, else `E_USAGE` -- so a caller grepping the
    top level for a semantic rejection (e.g. `E_TRIAGE_INCOMPLETE`) still
    finds one when an unrelated arg-shape mistake co-occurs in the same call.
    """
    detail: dict[str, JsonValue] = {
        "errors": cast(
            "list[JsonValue]",
            [
                {
                    "code": str(error.code),
                    "field": error.detail.get("field"),
                    "message": error.message,
                }
                for error in errors
            ],
        )
    }
    message = "; ".join(f"{error.detail.get('field', '?')}: {error.message}" for error in errors)
    code = next(
        (error.code for error in errors if error.code is not ErrorCode.USAGE), ErrorCode.USAGE
    )
    return WorkError(code, message, detail)

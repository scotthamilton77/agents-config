"""`## Continuations` manifest grammar.

Pure text parsing -- no `Backend`, no I/O. `deliver` and `reconcile` feed
this the spec text an injected file-reader already fetched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle.nouns import Noun

_SECTION_HEADER = "## Continuations"
_NONE_LITERAL = "none"
_AC_SEPARATOR = " — AC: "

# The grammar, stated for whoever tripped over it. Every refusal that fires
# because the section is absent, blank, or holds a bullet this grammar does not
# recognise carries it, because at that moment the author is reading the error
# rather than the parser.
#
# It leads with the item form and closes on the declining form, and the second
# half is the load-bearing one: a spec that genuinely leaves no follow-on work
# still has to resolve its sibling placeholder, so `- none` is the sentence that
# says "considered, and there are none" -- the one thing an absent section
# cannot distinguish from an oversight. An author who never learns the form has
# only one visible way out of the refusal, which is to mint a section that says
# nothing.
_NOUNS = ", ".join(noun.value for noun in Noun)
_GRAMMAR_HELP = (
    f"each item bullet is `- <noun>: <title> — AC: <acceptance>` (noun one of: {_NOUNS}); "
    "a spec that leaves no follow-on work says so with the single bullet "
    "`- none — <why there is none>`"
)


@dataclass(frozen=True)
class ManifestItem:
    noun: str  # a bare Noun value — placement is NOT a manifest field (all items
    title: str  # mint under the objective/placeholder; cross-parent design-doc
    acceptance: str  # annotations like "(under X)" are not part of the facade grammar)


@dataclass(frozen=True)
class Manifest:
    items: tuple[ManifestItem, ...]  # empty iff the manifest is the literal `- none`
    none_reason: str | None  # non-None iff `- none`; None otherwise


def _section_body(spec_text: str) -> list[str]:
    lines = spec_text.splitlines()
    try:
        start = lines.index(_SECTION_HEADER)
    except ValueError:
        raise WorkError(
            ErrorCode.MANIFEST,
            f"spec has no `{_SECTION_HEADER}` section: add one to the spec, under which "
            f"{_GRAMMAR_HELP}",
        ) from None

    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return body


def _accumulate_bullets(body: list[str]) -> list[str]:
    """Fold wrapped bullet lines into one text per `- ` bullet.

    A bullet's text starts at a `- ` line. Any following line that is
    neither a new `- ` bullet, blank, nor a `## ` header gets appended
    (space-joined) -- that is the physical-line wrap. Blank lines are always
    ignored; non-bullet prose before the first bullet has nothing open to
    append to, so it is ignored too.
    """
    bullets: list[str] = []
    current: list[str] | None = None
    for raw_line in body:
        line = raw_line.strip()
        if line.startswith("- "):
            if current is not None:
                bullets.append(" ".join(current))
            current = [line[2:].strip()]
        elif not line:
            continue
        elif current is not None:
            current.append(line)
    if current is not None:
        bullets.append(" ".join(current))
    return bullets


def _is_none_bullet(text: str) -> bool:
    return text == _NONE_LITERAL or text.startswith(f"{_NONE_LITERAL} —")


def _none_reason(text: str) -> str:
    if text == _NONE_LITERAL:
        return ""
    return text.split("—", 1)[1].strip()


def _parse_item_bullet(text: str) -> ManifestItem:
    if ": " not in text:
        raise WorkError(
            ErrorCode.MANIFEST,
            f"manifest bullet {text!r} is neither an item nor a declination: {_GRAMMAR_HELP}",
        )
    noun_token, rest = text.split(": ", 1)
    noun_token = noun_token.strip()
    try:
        Noun(noun_token)
    except ValueError:
        raise WorkError(
            ErrorCode.MANIFEST,
            f"manifest item noun must be a bare noun, one of: {_NOUNS} "
            f"(got {noun_token!r}): {text!r}",
        ) from None

    if _AC_SEPARATOR not in rest:
        raise WorkError(ErrorCode.MANIFEST, f"manifest item is missing ` — AC: `: {text!r}")
    title, acceptance = rest.split(_AC_SEPARATOR, 1)
    title = title.strip()
    acceptance = acceptance.strip()
    if not title or not acceptance:
        raise WorkError(
            ErrorCode.MANIFEST,
            f"manifest item title and acceptance must be non-empty: {text!r}",
        )
    return ManifestItem(noun=noun_token, title=title, acceptance=acceptance)


def parse_continuations(spec_text: str) -> Manifest:
    body = _section_body(spec_text)
    bullets = _accumulate_bullets(body)

    none_bullets = [b for b in bullets if _is_none_bullet(b)]
    item_bullets = [b for b in bullets if not _is_none_bullet(b)]

    if none_bullets and item_bullets:
        raise WorkError(ErrorCode.MANIFEST, "`- none` cannot coexist with real item bullets")
    if none_bullets:
        return Manifest(items=(), none_reason=_none_reason(none_bullets[0]))
    if not item_bullets:
        raise WorkError(
            ErrorCode.MANIFEST,
            f"`{_SECTION_HEADER}` section has no bullets: {_GRAMMAR_HELP}",
        )

    items = tuple(_parse_item_bullet(bullet) for bullet in item_bullets)
    _reject_duplicate_titles(items)
    return Manifest(items=items, none_reason=None)


def _reject_duplicate_titles(items: tuple[ManifestItem, ...]) -> None:
    """Reject a manifest carrying two items with the identical title.

    `reconcile_placeholder`'s multi-unit path (`deliver.py::_reconcile_multi`)
    matches existing children by title to make the mint idempotent under
    replay -- a manifest with two same-titled items would silently mint only
    one, destroying conservation of committed work. Caught here at parse
    time, loudly, rather than as a silent under-mint at delivery.
    """
    seen: set[str] = set()
    for item in items:
        if item.title in seen:
            raise WorkError(
                ErrorCode.MANIFEST, f"manifest has duplicate item titles: {item.title!r}"
            )
        seen.add(item.title)


def serialize_manifest(manifest: Manifest) -> str:
    """Serialize a parsed `Manifest` to a single-line JSON string.

    Recorded in-band as the `[work] manifest:` note's payload at first design
    `deliver`, so recovery replays toward this frozen target instead of
    re-reading the (mutable) spec file. Single-line (no literal newlines, even
    across a multi-line title/AC — JSON escapes them) so it survives as one
    note line the marker parser reads.
    """
    payload = {
        "items": [
            {"noun": item.noun, "title": item.title, "acceptance": item.acceptance}
            for item in manifest.items
        ],
        "none_reason": manifest.none_reason,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _snapshot_drift(text: str) -> WorkError:
    return WorkError(
        ErrorCode.BACKEND_DRIFT,
        f"corrupt in-band manifest snapshot: {text!r}",
        detail={"snapshot": text},
    )


def deserialize_manifest(text: str) -> Manifest:
    """Inverse of `serialize_manifest`: the recorded snapshot back to a `Manifest`.

    The snapshot lives in a note -- shared state, replicated across machines,
    that a human or another agent can hand-edit -- so a truncated, malformed,
    or tampered payload is *expected* corruption, not an internal bug. It surfaces as a typed
    `E_BACKEND_DRIFT` carrying the offending text, so `reconcile` can report one
    poisoned placeholder as a single attention finding instead of a raw
    `JSONDecodeError`/`KeyError` aborting the whole sweep as `E_INTERNAL`.
    Validating the noun here (not just the JSON shape) means a returned
    `Manifest` is fully trustworthy inward -- callers never re-hit `Noun(...)`.
    """
    try:
        payload = json.loads(text)
        items = tuple(
            ManifestItem(noun=item["noun"], title=item["title"], acceptance=item["acceptance"])
            for item in payload["items"]
        )
        for item in items:
            Noun(item.noun)  # boundary validation: reject a tampered noun as drift
        none_reason = payload["none_reason"]
    except (ValueError, KeyError, TypeError) as corruption:
        raise _snapshot_drift(text) from corruption
    if none_reason is not None and not isinstance(none_reason, str):
        raise _snapshot_drift(text)
    return Manifest(items=items, none_reason=none_reason)

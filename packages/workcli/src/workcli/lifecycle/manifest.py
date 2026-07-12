"""`## Continuations` manifest grammar (plan Task 2, finalizes spec §15).

Pure text parsing -- no `Backend`, no I/O. `deliver` (Task 5) and `reconcile`
(Task 6) feed this the spec text an injected file-reader already fetched.
"""

from __future__ import annotations

from dataclasses import dataclass

from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle.nouns import Noun

_SECTION_HEADER = "## Continuations"
_NONE_LITERAL = "none"
_AC_SEPARATOR = " — AC: "


@dataclass(frozen=True)
class ManifestItem:
    noun: str  # a bare Noun value — placement is NOT a manifest field (all items
    title: str  # mint under the objective/placeholder; §12's cross-parent design-doc
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
        raise WorkError(ErrorCode.MANIFEST, "spec has no ## Continuations manifest") from None

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
            f"manifest item must be `<noun>: <title> — AC: <acceptance>`: {text!r}",
        )
    noun_token, rest = text.split(": ", 1)
    noun_token = noun_token.strip()
    try:
        Noun(noun_token)
    except ValueError:
        raise WorkError(
            ErrorCode.MANIFEST,
            f"manifest item noun must be a bare noun (got {noun_token!r}): {text!r}",
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
        raise WorkError(ErrorCode.MANIFEST, "empty manifest")

    items = tuple(_parse_item_bullet(bullet) for bullet in item_bullets)
    return Manifest(items=items, none_reason=None)

"""Idempotency markers for remote reply effects (verb-atomicity spec §4).

Pure helpers, no I/O. Every non-idempotent comment-creating call in ``reply_pr``
appends a hidden, content-stable HTML-comment marker to the posted body; a
pre-flight scan of the PR's comment listings adopts already-posted effects
(records the id, flips the flag, skips the call) so a rerun from any stale
pre-call state converges without duplicates. GitHub — not the local state file —
is the source of truth for "was this posted". ``poll`` uses the same grammar as a
state-independent ingest backstop (never re-ingest prgroom's own posted effect).

The ``prgroom:`` namespace extends the existing ``<!-- prgroom:decisions:start -->``
sentinel family. Matching is strict full-grammar everywhere — prose *mentioning* a
marker cannot be mis-adopted or mis-skipped.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from prgroom.prsession.state import ReviewItem, RoutedMemory

JsonObj = dict[str, Any]

_MARKER_RE = re.compile(r"<!-- prgroom:(?:reply|mem):\S+ -->")


def reply_marker(item: ReviewItem) -> str:
    """Stable marker for the one reply this item ever gets.

    Keyed on the logical effect identity — the ``(kind, gh_id)`` natural key —
    not body content: ``replied`` is monotonic, so one item gets at most one POST
    over its lifetime, while bodies may legally differ across cycles (the
    empty-rationale → later-rationale path). Adoption is body-independent.
    """
    return f"<!-- prgroom:reply:{item.kind.value}:{item.identity.gh_id} -->"


def memory_marker(rm: RoutedMemory) -> str:
    """Globally-unique marker for one routed-memory thread reply.

    A readable batch-key prefix (whitespace-sanitized for marker-grammar safety)
    plus a content digest that carries the identity: ``(retry, source_item)`` is
    only batch-unique (the ordinal restarts per resolve call; cluster ids are
    LLM-minted), so the sha256 digest over ``(retry, source_item, target_hint,
    content)`` restores global uniqueness. It is crash-stable — a rerun replays
    the same persisted entries verbatim, so the digest re-derives byte-identically.
    Entries identical in all four fields collide by construction; skipping such a
    duplicate is correct dedup, not loss.
    """
    digest = hashlib.sha256(
        f"{rm.retry}\x1f{rm.source_item}\x1f{rm.target_hint or ''}\x1f{rm.content}".encode()
    ).hexdigest()[:12]
    prefix = re.sub(r"\s+", "-", f"r{rm.retry}:{rm.source_item}")
    return f"<!-- prgroom:mem:{prefix}:{digest} -->"


def with_marker(body: str, marker: str) -> str:
    """Append the hidden marker on its own trailing paragraph."""
    return f"{body}\n\n{marker}"


def scan_markers(*comment_lists: list[JsonObj]) -> dict[str, int]:
    """Map each full marker string found in any comment body to that comment's id.

    First occurrence wins — the earliest (original) comment claims the marker;
    listing order is ascending (§11 ledger). Entries with a missing/zero/unusable
    ``id`` are skipped: an adoption must record a real comment id or not happen.
    """
    found: dict[str, int] = {}
    for comments in comment_lists:
        for entry in comments:
            try:
                comment_id = int(entry.get("id"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if not comment_id:
                continue
            for match in _MARKER_RE.finditer(str(entry.get("body") or "")):
                found.setdefault(match.group(0), comment_id)
    return found


def carries_own_marker(body: str) -> bool:
    """True iff ``body`` contains a full-grammar prgroom idempotency marker."""
    return bool(_MARKER_RE.search(body))

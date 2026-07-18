"""``reply_pr`` — render + post per-item replies and route CONTEXTUAL memory (§3.3, §8.3)."""

from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING

from prgroom.agent.prompt_loader import PromptTemplate
from prgroom.gh.client import GhNotFoundError
from prgroom.lifecycle.gh_errors import vanished_pr_terminal
from prgroom.lifecycle.idempotency import memory_marker, reply_marker, scan_markers, with_marker
from prgroom.lifecycle.snapshot import (
    DECISIONS_END,
    DECISIONS_START,
    extract_decisions_block,
)
from prgroom.prsession.enums import DispositionKind, ItemKind
from prgroom.prsession.state import RoutedMemory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from prgroom.gh.client import GhClient
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import Disposition, PRGroomingState, ReviewItem

# {location} is " in {sha}" when a commit is known, else "" — guards against a bare
# "Fixed in ." when a FIXED/ALREADY_ADDRESSED disposition carries no commit (reachable
# via `resolve-escalated --as fixed` with no --commits, or legacy/corrupt state).
_T_FIXED = PromptTemplate(name="reply-fixed", text="Fixed{location}. {rationale}")
_T_FIXED_BARE = PromptTemplate(name="reply-fixed-bare", text="Fixed{location}.")
_T_ALREADY = PromptTemplate(name="reply-already", text="Already addressed{location}.")
_T_RATIONALE = PromptTemplate(name="reply-rationale", text="{rationale}")
_ESCALATED_BODY = (
    "Captured for follow-up; will respond on a later push to this PR or in a related issue."
)
_ESCALATED_CAP_BODY = (
    "Round limit reached on this PR; deferring further iterations to a human reviewer."
)
# Word-boundary match: a retry-budget rationale names "budget" as a standalone word
# ("PR-review retry budget exhausted"); "cap" is kept for free-form agent rationales
# still using the older vocabulary. A raw substring test would mis-fire on
# "captured"/"capacity"/"escape"/"budgetary".
_CAP_RE = re.compile(r"\b(?:cap|budget)\b", re.IGNORECASE)
_REPLYABLE = frozenset(
    {
        DispositionKind.FIXED,
        DispositionKind.ALREADY_ADDRESSED,
        DispositionKind.SKIPPED,
        DispositionKind.DEFERRED,
        DispositionKind.WONT_FIX,
        DispositionKind.ESCALATED,
    }
)
# SKIPPED/DEFERRED are internal bookkeeping. On a review thread the rationale belongs
# as a threaded explanation, but a threadless item (review summary / issue comment)
# takes the top-level issue-comment route — minting a fresh gh id no ledger recognizes,
# one new bookkeeping comment per skipped item per cycle (the phantom-review comment
# flood). Suppress the post; the disposition itself is the record.
_BOOKKEEPING_ONLY = frozenset({DispositionKind.SKIPPED, DispositionKind.DEFERRED})


def _render_body(disp: Disposition) -> str:
    kind = disp.kind
    location = f" in {disp.commits[0]}" if disp.commits else ""
    if kind is DispositionKind.FIXED:
        if disp.rationale:
            return _T_FIXED.render({"location": location, "rationale": disp.rationale})
        return _T_FIXED_BARE.render({"location": location})
    if kind is DispositionKind.ALREADY_ADDRESSED:
        return _T_ALREADY.render({"location": location})
    if kind is DispositionKind.ESCALATED:
        return _ESCALATED_CAP_BODY if _CAP_RE.search(disp.rationale) else _ESCALATED_BODY
    return _T_RATIONALE.render({"rationale": disp.rationale})


def _post_reply(gh: GhClient, ref: PRRef, item: ReviewItem, body: str) -> int:
    """POST the reply/comment and return the new comment's numeric id (0 if absent).

    GitHub's reply/comment POST returns the created comment object carrying a numeric
    ``id``; the caller records it on ``item.own_reply_id`` so a later poll can exclude
    our own reply (recursive self-reply prevention). Defensive on shape: the id may be
    int or str, and a malformed response with no usable id degrades to 0.
    """
    if item.kind is ItemKind.REVIEW_THREAD:
        reply_id = item.identity.reply_to_comment_id or int(item.identity.gh_id)
        path = f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/comments/{reply_id}/replies"
    else:
        path = f"repos/{ref.owner}/{ref.repo}/issues/{ref.number}/comments"
    response = gh.rest("POST", path, fields={"body": body})
    raw_id = response.get("id") if isinstance(response, dict) else None
    try:
        return int(raw_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_MARKER_RE = re.compile(r"^<!-- d:r(?P<retry>\d+):(?P<item>\S+) -->")
_ADD_THREAD_REPLY = (
    "mutation($threadId:ID!,$body:String!){"
    "addPullRequestReviewThreadReply(input:{"
    "pullRequestReviewThreadId:$threadId,body:$body}){comment{id}}}"
)


def _sanitize(content: str) -> str:
    """Collapse newlines to spaces and strip HTML comments so one entry is one line."""
    return _COMMENT_RE.sub("", content).replace("\n", " ").replace("\r", " ")


def _decisions_line(rm: RoutedMemory) -> str:
    marker = f"<!-- d:r{rm.retry}:{rm.source_item} -->"
    return f"{marker} - **[r{rm.retry}]** {_sanitize(rm.content)} _(decided_by: {rm.decided_by})_"


def _splice_block(body: str, block: str) -> str:
    start = body.find(DECISIONS_START)
    if start == -1:
        # No block at all — append the fresh block, preserving every existing byte.
        sep = "\n\n" if body.strip() else ""
        return f"{body}{sep}{block}"
    end = body.find(DECISIONS_END, start)
    if end == -1:
        # Orphan start (start present, end missing): re-pair in place, never truncate.
        # extract_decisions_block reads from the FIRST start sentinel, so appending a fresh
        # block at the end would leave the orphan first — the new block would be unreadable
        # (extract would span orphan-start..appended-end, capturing a nested sentinel) and
        # re-merges would keep appending. Replace the orphan start marker with the fresh
        # block and keep everything after it as the tail: the first start is paired again,
        # the block is readable, and merges stay idempotent.
        tail = body[start + len(DECISIONS_START) :]
        return body[:start] + block + tail
    tail = body[end + len(DECISIONS_END) :]
    return body[:start] + block + tail


def merge_decisions_block(body: str, entries: list[RoutedMemory]) -> str:
    """Merge thread-less decisions into the sentinel-bounded ``## Decisions`` block (§8.3).

    Pure. Parse existing lines by the leading ``<!-- d:r<retry>:<item> -->`` marker into
    an ordered key->line map (never markdown-prose guessing); for each new entry, skip if
    its key exists (never overwrite/delete prior), else append; re-render the block
    wholesale and splice between sentinels (creating block + heading if absent). A
    same-retry re-run is byte-identical; an existing key for item A does not block a new
    same-retry entry for item B.
    """
    existing = extract_decisions_block(body)
    ordered: dict[str, str] = {}
    for line in existing.splitlines():
        m = _MARKER_RE.match(line.strip())
        if m:
            ordered[f"{m.group('retry')}:{m.group('item')}"] = line.strip()
    for rm in entries:
        key = f"{rm.retry}:{rm.source_item}"
        if key not in ordered:
            ordered[key] = _decisions_line(rm)
    block = "\n".join([DECISIONS_START, "## Decisions", *ordered.values(), DECISIONS_END])
    return _splice_block(body, block)


def _needs_post(item: ReviewItem) -> bool:
    """True iff this invocation may POST a reply for ``item`` (the §5 surface gate).

    Mirrors the item-loop gates minus the render: an unreplied item with a
    replyable disposition off the bookkeeping-only no-post path. An item whose
    body will render empty still counts — one tolerated over-fetch beats a
    pre-render pass (assumption ledger).
    """
    return (
        not item.replied
        and item.disposition is not None
        and item.disposition.kind in _REPLYABLE
        and not (
            item.kind is not ItemKind.REVIEW_THREAD and item.disposition.kind in _BOOKKEEPING_ONLY
        )
    )


def _reply_surfaces(state: PRGroomingState) -> tuple[bool, bool]:
    """``(need_issue_comments, need_review_comments)`` for this invocation.

    ``REVIEW_THREAD`` items and target-hinted ``pending_memory`` entries post to
    the review-comment surface (thread replies land in ``pulls/{n}/comments``);
    every other replyable item posts to the issue-comment surface. Thread-less
    memory routes via the PR-body PATCH, which needs no scan (content-addressed).
    """
    need_issue = any(_needs_post(i) and i.kind is not ItemKind.REVIEW_THREAD for i in state.items)
    need_review = any(_needs_post(i) and i.kind is ItemKind.REVIEW_THREAD for i in state.items)
    need_review = need_review or any(rm.target_hint is not None for rm in state.pending_memory)
    return need_issue, need_review


def _existing_markers(gh: GhClient, ref: PRRef, *, issue: bool, review: bool) -> dict[str, int]:
    """Pre-flight scan (§5): map already-posted effect markers to their comment ids.

    At most two paginated reads; zero gh calls when neither surface is needed —
    the no-op-when-all-replied contract survives at zero cost.
    """
    listings: list[list[dict[str, object]]] = []
    base = f"repos/{ref.owner}/{ref.repo}"
    if issue:
        listings.append(gh.rest("GET", f"{base}/issues/{ref.number}/comments", paginate=True))
    if review:
        listings.append(gh.rest("GET", f"{base}/pulls/{ref.number}/comments", paginate=True))
    return scan_markers(*listings) if listings else {}


def _route_memory(
    state: PRGroomingState, *, gh: GhClient, ref: PRRef, markers: Mapping[str, int]
) -> None:
    thread_less: list[RoutedMemory] = []
    posted: set[str] = set()  # the pre-flight snapshot can't see this pass's own POSTs
    for rm in state.pending_memory:
        if rm.target_hint is not None:
            marker = memory_marker(rm)
            if marker in markers or marker in posted:
                continue  # already posted (prior partial pass, or earlier this pass)
            gh.graphql(
                _ADD_THREAD_REPLY,
                {"threadId": rm.target_hint, "body": with_marker(rm.content, marker)},
            )
            posted.add(marker)
        else:
            thread_less.append(rm)
    if thread_less:
        detail = gh.rest("GET", f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")
        body = str(detail.get("body") or "")
        merged = merge_decisions_block(body, thread_less)
        # merge_decisions_block is byte-identical on rerun, so a crash-resume with the same
        # pending_memory re-derives the same body. Skip the no-op PATCH (avoid API churn /
        # triggering PR automations, and shrink the GET→PATCH overwrite window).
        if merged != body:
            gh.rest(
                "PATCH",
                f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}",
                fields={"body": merged},
            )
    state.pending_memory = []


def reply_pr(
    state: PRGroomingState,
    *,
    gh: GhClient,
    ref: PRRef,
) -> PRGroomingState:
    """Post per-item replies and route pending CONTEXTUAL memory (§3.2 reply row).

    Works on a deepcopy; caller persists once (verb-atomic). No phase change, no
    ``last_error``. Per-item replies dedup via ``ReviewItem.replied``; pending
    CONTEXTUAL memory routes to thread replies / the PR-body Decisions block.
    """
    state = copy.deepcopy(state)
    try:
        need_issue, need_review = _reply_surfaces(state)
        markers = _existing_markers(gh, ref, issue=need_issue, review=need_review)
        for item in state.items:
            if item.replied or item.disposition is None:
                continue
            if item.disposition.kind not in _REPLYABLE:
                continue
            if (
                item.kind is not ItemKind.REVIEW_THREAD
                and item.disposition.kind in _BOOKKEEPING_ONLY
            ):
                # Finalized without a post — bookkeeping stays internal (see
                # _BOOKKEEPING_ONLY). `replied` marks the reply step done so the
                # item is never revisited.
                item.replied = True
                continue
            marker = reply_marker(item)
            adopted = markers.get(marker)
            if adopted is not None:
                # A prior partial pass already posted this reply; the persist that
                # would have recorded it was discarded. GitHub is the source of
                # truth — adopt the effect. This also recovers the real comment id
                # when the original POST response was malformed (id degraded to 0).
                item.own_reply_id = adopted
                item.replied = True
                continue
            body = _render_body(item.disposition)
            if not body.strip():
                # A rationale-rendered disposition (SKIPPED/DEFERRED/WONT_FIX) with an empty
                # rationale renders no body (reachable via `resolve-escalated` with no
                # --rationale). Posting "" fails the GitHub API; skip it and leave `replied`
                # False so a later rationale can still reply.
                continue
            item.own_reply_id = _post_reply(gh, ref, item, with_marker(body, marker))
            item.replied = True
        _route_memory(state, gh=gh, ref=ref, markers=markers)
    except GhNotFoundError as exc:
        raise vanished_pr_terminal(ref) from exc
    return state

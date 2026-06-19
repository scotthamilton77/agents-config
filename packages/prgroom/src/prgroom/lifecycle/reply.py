"""``reply_pr`` — render + post per-item replies and route CONTEXTUAL memory (§3.3, §8.3)."""

from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING

from prgroom.agent.prompt_loader import PromptTemplate
from prgroom.gh.client import GhNotFoundError
from prgroom.lifecycle.gh_errors import vanished_pr_terminal
from prgroom.lifecycle.snapshot import DECISIONS_END, DECISIONS_START
from prgroom.lifecycle.warn import default_warn
from prgroom.prsession.enums import DispositionKind, ItemKind
from prgroom.prsession.state import RoutedMemory

if TYPE_CHECKING:
    from collections.abc import Callable

    from prgroom.gh.client import GhClient
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import Disposition, PRGroomingState, ReviewItem

_T_FIXED = PromptTemplate(name="reply-fixed", text="Fixed in {sha}. {rationale}")
_T_FIXED_BARE = PromptTemplate(name="reply-fixed-bare", text="Fixed in {sha}.")
_T_ALREADY = PromptTemplate(name="reply-already", text="Already addressed in {sha}.")
_T_RATIONALE = PromptTemplate(name="reply-rationale", text="{rationale}")
_ESCALATED_BODY = (
    "Captured for follow-up; will respond on a later push to this PR or in a related issue."
)
_ESCALATED_CAP_BODY = (
    "Round limit reached on this PR; deferring further iterations to a human reviewer."
)
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


def _render_body(disp: Disposition) -> str:
    kind = disp.kind
    if kind is DispositionKind.FIXED:
        sha = disp.commits[0] if disp.commits else ""
        if disp.rationale:
            return _T_FIXED.render({"sha": sha, "rationale": disp.rationale})
        return _T_FIXED_BARE.render({"sha": sha})
    if kind is DispositionKind.ALREADY_ADDRESSED:
        sha = disp.commits[0] if disp.commits else ""
        return _T_ALREADY.render({"sha": sha})
    if kind is DispositionKind.ESCALATED:
        return _ESCALATED_CAP_BODY if "cap" in disp.rationale.lower() else _ESCALATED_BODY
    return _T_RATIONALE.render({"rationale": disp.rationale})


def _post_reply(gh: GhClient, ref: PRRef, item: ReviewItem, body: str) -> None:
    if item.kind is ItemKind.REVIEW_THREAD:
        reply_id = item.identity.reply_to_comment_id or int(item.identity.gh_id)
        path = f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/comments/{reply_id}/replies"
    else:
        path = f"repos/{ref.owner}/{ref.repo}/issues/{ref.number}/comments"
    gh.rest("POST", path, fields={"body": body})


_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_MARKER_RE = re.compile(r"^<!-- d:r(?P<round>\d+):(?P<item>\S+) -->")
_ADD_THREAD_REPLY = (
    "mutation($threadId:ID!,$body:String!){"
    "addPullRequestReviewThreadReply(input:{"
    "pullRequestReviewThreadId:$threadId,body:$body}){comment{id}}}"
)


def _sanitize(content: str) -> str:
    """Collapse newlines to spaces and strip HTML comments so one entry is one line."""
    return _COMMENT_RE.sub("", content).replace("\n", " ").replace("\r", " ")


def _decisions_line(rm: RoutedMemory) -> str:
    marker = f"<!-- d:r{rm.round}:{rm.source_item} -->"
    return f"{marker} - **[r{rm.round}]** {_sanitize(rm.content)} _(decided_by: {rm.decided_by})_"


def _extract_block(body: str) -> str:
    start = body.find(DECISIONS_START)
    if start == -1:
        return ""
    end = body.find(DECISIONS_END, start)
    if end == -1:
        return ""
    return body[start + len(DECISIONS_START) : end]


def _splice_block(body: str, block: str) -> str:
    start = body.find(DECISIONS_START)
    if start == -1:
        sep = "\n\n" if body.strip() else ""
        return f"{body}{sep}{block}"
    end = body.find(DECISIONS_END, start)
    tail = body[end + len(DECISIONS_END) :] if end != -1 else ""
    return body[:start] + block + tail


def merge_decisions_block(body: str, entries: list[RoutedMemory]) -> str:
    """Merge thread-less decisions into the sentinel-bounded ``## Decisions`` block (§8.3).

    Pure. Parse existing lines by the leading ``<!-- d:r<round>:<item> -->`` marker into
    an ordered key->line map (never markdown-prose guessing); for each new entry, skip if
    its key exists (never overwrite/delete prior), else append; re-render the block
    wholesale and splice between sentinels (creating block + heading if absent). A
    same-round re-run is byte-identical; an existing key for item A does not block a new
    same-round entry for item B.
    """
    existing = _extract_block(body)
    ordered: dict[str, str] = {}
    for line in existing.splitlines():
        m = _MARKER_RE.match(line.strip())
        if m:
            ordered[f"{m.group('round')}:{m.group('item')}"] = line.strip()
    for rm in entries:
        key = f"{rm.round}:{rm.source_item}"
        if key not in ordered:
            ordered[key] = _decisions_line(rm)
    block = "\n".join([DECISIONS_START, "## Decisions", *ordered.values(), DECISIONS_END])
    return _splice_block(body, block)


def _route_memory(state: PRGroomingState, *, gh: GhClient, ref: PRRef) -> None:
    thread_less: list[RoutedMemory] = []
    for rm in state.pending_memory:
        if rm.target_hint is not None:
            gh.graphql(_ADD_THREAD_REPLY, {"threadId": rm.target_hint, "body": rm.content})
        else:
            thread_less.append(rm)
    if thread_less:
        detail = gh.rest("GET", f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")
        body = str(detail.get("body") or "")
        merged = merge_decisions_block(body, thread_less)
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
    warn: Callable[[str], None] = default_warn,  # noqa: ARG001  # reserved for §8.3 memory routing (Task 10)
) -> PRGroomingState:
    """Post per-item replies and route pending CONTEXTUAL memory (§3.2 reply row).

    Works on a deepcopy; caller persists once (verb-atomic). No phase change, no
    ``last_error``. Per-item replies dedup via ``ReviewItem.replied``. (Memory
    routing — Task 10 — appends below the per-item loop in this same function.)
    """
    state = copy.deepcopy(state)
    try:
        for item in state.items:
            if item.replied or item.disposition is None:
                continue
            if item.disposition.kind not in _REPLYABLE:
                continue
            _post_reply(gh, ref, item, _render_body(item.disposition))
            item.replied = True
        _route_memory(state, gh=gh, ref=ref)
    except GhNotFoundError as exc:
        raise vanished_pr_terminal(ref) from exc
    return state

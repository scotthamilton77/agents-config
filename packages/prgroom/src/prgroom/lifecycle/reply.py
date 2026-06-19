"""``reply_pr`` — render + post per-item replies and route CONTEXTUAL memory (§3.3, §8.3)."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from prgroom.agent.prompt_loader import PromptTemplate
from prgroom.gh.client import GhNotFoundError
from prgroom.lifecycle.gh_errors import vanished_pr_terminal
from prgroom.lifecycle.warn import default_warn
from prgroom.prsession.enums import DispositionKind, ItemKind

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
        # --- Task 10 inserts CONTEXTUAL memory routing here ---
    except GhNotFoundError as exc:
        raise vanished_pr_terminal(ref) from exc
    return state

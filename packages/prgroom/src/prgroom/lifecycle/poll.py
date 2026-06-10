"""``poll_pr`` — the read-only ``_poll`` lifecycle internal (§3.2, §3.4, §4.1).

``poll_pr`` is the lock-assuming poll internal: the caller holds the per-ref lock,
hands in the current in-memory :class:`PRGroomingState`, and gets back the mutated
copy (the caller owns ``store.write``). It is **read-only over GitHub** — every gh
call is a REST ``GET`` via the injected :class:`~prgroom.gh.client.GhClient`; no
push, no review re-request, no resolve.

One poll issues six reads in this fixed order:

1. ``head_ref_oid`` — the remote HEAD SHA. Drives the §3.4 bootstrap / attribution
   / push-detection math. An empty HEAD short-circuits the rest (a PR with no
   commits yet).
2. PR resource (``pulls/{n}``) — ``state`` + ``merged_at`` drive the closed-via-merge
   → ``merged`` transition. A 404 here is a vanished PR/repo mid-run, mapped to
   ``RUNTIME_GH_TERMINAL`` (the startup precondition that owns
   ``PRECONDITION_REPO_UNREACHABLE`` is out of this verb's scope).
3. issue comments, 4. reviews, 5. review (inline) comments — ingested into
   :class:`ReviewItem`s (natural key ``(kind, gh_id)``; never re-appended) and used
   to flip reviewer engagement (§4.1).
6. CI combined-status for the head SHA — mapped to ``success | pending | failure |
   absent`` for ``quiescence.ci_state``. A 404 there means no CI configured →
   ``absent`` (not an error).

After the reads it runs ``evaluate_reviewer_timeouts`` (§4.1 auto-decline), stamps
``last_polled_at``, advances ``last_activity_at`` on any observed mutation, and
resolves the next phase per the §3.2 poll row. ``PrgroomError``s raised by the gh
adapter (transient / terminal / graphql) propagate unchanged.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import TYPE_CHECKING, Any

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.gh.client import GhNotFoundError
from prgroom.lifecycle.predicates import flip_stale_required_reviews
from prgroom.lifecycle.quiescence import evaluate_reviewer_timeouts
from prgroom.prsession.enums import ItemKind, PRPhase, ReviewerStatus
from prgroom.prsession.state import Identity, PRGroomingState, ReviewItem

if TYPE_CHECKING:
    from datetime import datetime

    from prgroom.config import PrgroomConfig
    from prgroom.deps import Deps
    from prgroom.gh.client import GhClient
    from prgroom.prsession.pr_ref import PRRef

_BODY_EXCERPT_LEN = 200

# Combined-status states the gh "commits/{sha}/status" endpoint returns, mapped to
# the §4.1 ci_state vocabulary. GitHub's combined status uses {success, pending,
# failure}; an empty/unknown value is treated as pending (CI exists but is not yet
# green), and a 404 (no CI configured) maps to "absent" at the call site.
_CI_STATES: frozenset[str] = frozenset({"success", "pending", "failure"})


def poll_pr(
    state: PRGroomingState,
    *,
    ref: PRRef,
    gh: GhClient,
    deps: Deps,
    config: PrgroomConfig,
) -> PRGroomingState:
    """Read-only poll: ingest gh review state, apply §3.4/§3.2/§4.1, return new state.

    Caller must hold the per-ref lock (see ``lock()``). Works on a copy of ``state``
    so the caller's object is never mutated; returns the copy for the caller to
    persist. Read-only — issues no gh writes.
    """
    state = copy.deepcopy(state)
    now = deps.clock.now()
    state.last_polled_at = now

    new_head = gh.head_ref_oid(ref)
    if not new_head:
        # Empty remote HEAD (PR opened with no commits): leave round/last_poll_sha
        # untouched, no phase change. The next poll re-evaluates the bootstrap.
        return state

    merged = _pr_is_merged(gh, ref)
    activity = False

    new_items, terminal_reviews = _ingest_items(gh, ref, state, now=now)
    if new_items:
        state.items.extend(new_items)
        activity = True
    if _observe_engagement(state, new_items, terminal_reviews):
        activity = True

    new_ci = _ci_state(gh, ref, new_head)
    if new_ci != state.quiescence.ci_state:
        # QuiescenceState is frozen — replace the whole value, preserving quiesced_at.
        state.quiescence = dataclasses.replace(state.quiescence, ci_state=new_ci)
        activity = True

    evaluate_reviewer_timeouts(
        state,
        now=now,
        review_start_timeout=config.review_start_timeout,
        review_finish_timeout=config.review_finish_timeout,
    )

    external_push = _apply_sha_attribution(state, new_head)
    if external_push:
        activity = True

    if activity:
        state.last_activity_at = now

    state.phase = _resolve_poll_phase(
        state.phase,
        merged=merged,
        new_item=bool(new_items),
        external_push=external_push,
        has_items=bool(state.items),
    )
    return state


def _pr_is_merged(gh: GhClient, ref: PRRef) -> bool:
    """True iff the PR resource shows a merged close (§3.2 poll-row merge edge)."""
    try:
        pr = gh.rest("GET", f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")
    except GhNotFoundError as exc:
        # The PR/repo vanished mid-run. The startup precondition that owns
        # PRECONDITION_REPO_UNREACHABLE is out of this verb's scope, so a mid-flight
        # 404 is terminal — a blind retry will not bring the resource back.
        raise PrgroomError(
            tier=Tier.RUNTIME_TERMINAL_USER,
            code=ErrorCode.RUNTIME_GH_TERMINAL,
            detail=f"PR resource not found: {ref.display()}",
        ) from exc
    return bool(pr.get("merged_at"))


# GitHub review states that count as a terminal verdict written by _poll (§4.1).
# COMMENTED is intentionally excluded: §4.1 hedges whether a COMMENTED review is
# terminal to Section 5's fix contract, so MVP treats it as engagement only.
_TERMINAL_REVIEW_STATES: frozenset[str] = frozenset({"APPROVED", "CHANGES_REQUESTED"})


def _ingest_items(
    gh: GhClient, ref: PRRef, state: PRGroomingState, *, now: datetime
) -> tuple[list[ReviewItem], dict[str, datetime]]:
    """Fetch the three item sources; return new items + per-reviewer terminal verdicts.

    The second element maps a reviewer login to the timestamp of its latest
    APPROVED/CHANGES_REQUESTED review (§4.1) so ``_observe_engagement`` can promote
    that reviewer to ``review_found``. Only items new to ``state`` (natural key
    ``(kind, gh_id)``) are returned; the terminal-verdict map is derived from the
    full reviews response (a verdict can repeat across polls without a new item).
    """
    seen = {(item.kind, item.identity.gh_id) for item in state.items}
    base = f"repos/{ref.owner}/{ref.repo}"
    raw_issue = gh.rest("GET", f"{base}/issues/{ref.number}/comments")
    raw_reviews = gh.rest("GET", f"{base}/pulls/{ref.number}/reviews")
    raw_review_comments = gh.rest("GET", f"{base}/pulls/{ref.number}/comments")

    new: list[ReviewItem] = []
    for kind, raw, ts_field in (
        (ItemKind.ISSUE_COMMENT, raw_issue, "created_at"),
        (ItemKind.REVIEW_SUMMARY, raw_reviews, "submitted_at"),
        (ItemKind.REVIEW_THREAD, raw_review_comments, "created_at"),
    ):
        for entry in raw:
            item = _to_item(kind, entry, ts_field, now=now)
            if (item.kind, item.identity.gh_id) not in seen:
                seen.add((item.kind, item.identity.gh_id))
                new.append(item)
    return new, _terminal_review_verdicts(raw_reviews, now=now)


def _terminal_review_verdicts(raw_reviews: Any, *, now: datetime) -> dict[str, datetime]:
    """Map each reviewer login to its latest APPROVED/CHANGES_REQUESTED time (§4.1)."""
    verdicts: dict[str, datetime] = {}
    for entry in raw_reviews:
        if str(entry.get("state", "")) not in _TERMINAL_REVIEW_STATES:
            continue
        login = str(entry.get("user", {}).get("login", ""))
        if not login:
            continue
        submitted = _parse_ts(entry.get("submitted_at"), now=now)
        if login not in verdicts or submitted > verdicts[login]:
            verdicts[login] = submitted
    return verdicts


def _to_item(kind: ItemKind, entry: dict[str, Any], ts_field: str, *, now: datetime) -> ReviewItem:
    """Build a :class:`ReviewItem` from one gh comment/review payload."""
    gh_id = str(entry["id"])
    identity = Identity(gh_id=gh_id)
    if kind is ItemKind.REVIEW_THREAD:
        # GitHub's pulls/{n}/comments exposes the PARENT comment id as
        # `in_reply_to_id` (present only on replies); a top-level inline comment
        # has no parent → 0. The comment's own id lives in `gh_id`.
        parent = entry.get("in_reply_to_id")
        reply_to = int(parent) if parent is not None else 0
        identity = Identity(gh_id=gh_id, reply_to_comment_id=reply_to)
    body = str(entry.get("body") or "")
    return ReviewItem(
        kind=kind,
        identity=identity,
        author=str(entry.get("user", {}).get("login", "")),
        body_excerpt=body[:_BODY_EXCERPT_LEN],
        seen_at=_parse_ts(entry.get(ts_field), now=now),
    )


def _parse_ts(raw: object, *, now: datetime) -> datetime:
    """Parse a gh ISO-8601 timestamp; fall back to the injected ``now`` when absent.

    The fallback uses the run-loop's clock reading (never ``datetime.now``) so the
    §7.6 no-stdlib-singleton discipline holds and the seam stays deterministic.
    """
    from datetime import datetime

    if isinstance(raw, str) and raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return now


def _observe_engagement(
    state: PRGroomingState,
    new_items: list[ReviewItem],
    terminal_reviews: dict[str, datetime],
) -> bool:
    """Update reviewer engagement + terminal verdict from this poll's activity (§4.1).

    Engagement is activity a reviewer's gh login produced **after** its
    ``last_request_at`` — a stale item predating the (re-)request window is pre-window
    noise. (§4.1 also requires "after the most-recent push timestamp"; the MVP state
    schema carries no push timestamp, only ``last_pushed_head_sha``, so that clause is
    approximated by ``last_request_at`` — a stale-activity-on-a-superseded-SHA edge —
    pending a stored push timestamp.) On qualifying activity:

    - ``last_review_at`` is advanced to the **activity's own timestamp** (its
      ``created_at`` / ``submitted_at``, carried on ``item.seen_at``), NOT poll time, so
      the §4.1 stall clock survives crash gaps and resumes correctly. It only ever
      moves **forward** — a later non-review comment that bumped it is never pulled
      back by a re-observed older terminal verdict.
    - An APPROVED / CHANGES_REQUESTED review (a post-request terminal verdict, in
      ``terminal_reviews``) sets the reviewer to ``review_found`` — a genuine verdict
      **supersedes a prior decline** (§4.1: an auto-decline is a fallback for a missing
      verdict — "requested but never engaged" / "engaged but never produced a terminal
      review" — so the real verdict it stood in for wins; both satisfy G_REVIEWERS, so
      only the reported status changes). Any other engagement merely advances
      ``requested`` / ``not_requested`` → ``in_progress`` and leaves an already-terminal
      ``review_found`` / ``declined`` reviewer's status as-is.

    **Idempotent in steady state.** ``terminal_reviews`` is recomputed from the full
    reviews list every poll, so a stable, already-recorded verdict reappears each
    poll; this returns ``True`` ONLY when something actually changed — a status
    transition OR a strictly-newer ``last_review_at``. A poll over an unchanged verdict
    is a no-op, so the caller does not spuriously advance ``last_activity_at`` and the
    §4.1 idle gate can still trip and let the PR quiesce.

    Returns whether anything changed.
    """
    changed = False
    for reviewer in state.reviewers.values():
        activity_times = [
            item.seen_at
            for item in new_items
            if item.author == reviewer.identity and item.seen_at > reviewer.last_request_at
        ]
        verdict_at = terminal_reviews.get(reviewer.identity)
        if verdict_at is not None and verdict_at > reviewer.last_request_at:
            activity_times.append(verdict_at)  # post-request terminal verdict
            target_status: ReviewerStatus | None = ReviewerStatus.REVIEW_FOUND
        elif reviewer.status in {ReviewerStatus.NOT_REQUESTED, ReviewerStatus.REQUESTED}:
            target_status = ReviewerStatus.IN_PROGRESS
        else:
            target_status = None  # engaged but already terminal — keep current status
        if not activity_times:
            continue
        # Advance last_review_at only on a strictly-newer activity time (never
        # regress to a re-observed older verdict); flip status only on a real change.
        candidate = max(activity_times)
        advanced = reviewer.last_review_at is None or candidate > reviewer.last_review_at
        if advanced:
            reviewer.last_review_at = candidate
        if target_status is not None and reviewer.status is not target_status:
            reviewer.status = target_status
            changed = True
        if advanced:
            changed = True
    return changed


def _ci_state(gh: GhClient, ref: PRRef, head_sha: str) -> str:
    """Map the gh combined-status for ``head_sha`` to the §4.1 ci_state vocabulary."""
    try:
        status = gh.rest("GET", f"repos/{ref.owner}/{ref.repo}/commits/{head_sha}/status")
    except GhNotFoundError:
        # No CI configured for this commit → absent (a gate-satisfying state, §4.1).
        return "absent"
    raw = str(status.get("state") or "")
    return raw if raw in _CI_STATES else "pending"


def _apply_sha_attribution(state: PRGroomingState, new_head: str) -> bool:
    """Apply §3.4 round/attribution for the observed HEAD; return external-push flag.

    Bootstrap (``last_poll_sha == ""``): anchor ``round = max(round, 1)``, set
    ``last_poll_sha``, no reviewer flip. Unchanged SHA: no-op. CLI's own push
    (``new_head == last_pushed_head_sha``): advance ``last_poll_sha`` only. External
    push: ``round += 1``, advance ``last_poll_sha``, flip stale required reviews.
    """
    if state.last_poll_sha == "":
        state.round = max(state.round, 1)
        state.last_poll_sha = new_head
        return False
    if new_head == state.last_poll_sha:
        return False
    if new_head == state.last_pushed_head_sha:
        # The CLI's own push — already counted by _push, reviewers already flipped.
        state.last_poll_sha = new_head
        return False
    # External push (operator / third party): count it and invalidate stale reviews.
    state.round += 1
    state.last_poll_sha = new_head
    flip_stale_required_reviews(state.reviewers)
    return True


def _resolve_poll_phase(
    phase: PRPhase,
    *,
    merged: bool,
    new_item: bool,
    external_push: bool,
    has_items: bool,
) -> PRPhase:
    """Resolve the next phase from the §3.2 poll row (first applicable edge wins).

    Reaching this resolver with ``phase is IDLE`` implies a non-empty HEAD was
    observed this poll (an empty HEAD returns from ``poll_pr`` before phase
    resolution), so the bootstrap anchor has fired — the only question left for an
    ``idle`` PR is whether a reviewer item is already on file.
    """
    if phase is PRPhase.MERGED:
        return PRPhase.MERGED
    if merged:
        return PRPhase.MERGED
    if phase is PRPhase.IDLE:
        # First push observed: a reviewer item already filed jumps straight to
        # fixes-pending (the direct idle→fixes-pending edge); else awaiting-review.
        return PRPhase.FIXES_PENDING if has_items else PRPhase.AWAITING_REVIEW
    if new_item:
        return PRPhase.FIXES_PENDING
    if external_push:
        # awaiting-review / fixes-pending stay; quiesced re-enters awaiting-review;
        # human-gated re-enters fixes-pending (operator resolved the gate).
        if phase is PRPhase.QUIESCED:
            return PRPhase.AWAITING_REVIEW
        if phase is PRPhase.HUMAN_GATED:
            return PRPhase.FIXES_PENDING
        return phase
    return phase

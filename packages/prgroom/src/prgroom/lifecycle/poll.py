"""``poll_pr`` — the read-only ``_poll`` lifecycle internal (§3.2, §3.4, §4.1).

``poll_pr`` is the lock-assuming poll internal: the caller holds the per-ref lock,
hands in the current in-memory :class:`PRGroomingState`, and gets back the mutated
copy (the caller owns ``store.write``). It is **read-only over GitHub** — every gh
call is a REST ``GET`` via the injected :class:`~prgroom.gh.client.GhClient`; no
push, no review re-request, no resolve.

One poll issues these REST reads in a fixed order (plus one conditional GraphQL read,
and a conditional combined-status fallback read):

1. ``head_ref_oid`` — the remote HEAD SHA. Drives the §3.4 bootstrap / attribution
   / push-detection math. An empty HEAD short-circuits the rest (a PR with no
   commits yet).
2. PR resource (``pulls/{n}``) — ``state`` + ``merged_at`` drive the closed-via-merge
   → ``merged`` transition. A 404 here is a vanished PR/repo mid-run, mapped to
   ``RUNTIME_GH_TERMINAL`` (the startup precondition that owns
   ``PRECONDITION_REPO_UNREACHABLE`` is out of this verb's scope).
3. issue comments, 4. reviews, 5. review (inline) comments — each a ``--paginate``d
   collection read (all pages, not just GitHub's first 30), ingested into
   :class:`ReviewItem`s (natural key ``(kind, gh_id)``; never re-appended) and used
   to flip reviewer engagement (§4.1).
5a. **GraphQL ``reviewThreads`` thread-id map** — issued only when step 5 returned
   inline comments. It resolves each review-thread item's :attr:`Identity.thread_id`
   to its ``PRRT_*`` node id (the id ``resolveReviewThread`` consumes and §8.2
   recurrence keys on); REST exposes only comment databaseIds, so this one GraphQL
   read bridges the key-space. A comment absent from the map degrades to ``""``.
6. CI for the head SHA — read from **check runs** (``commits/{sha}/check-runs``) and
   rolled up to ``success | pending | failure`` for ``quiescence.ci_state``. A commit
   with no check runs falls back to the legacy combined-status endpoint (classic commit
   statuses); a 404 there means no CI configured → ``absent`` (not an error). Reading
   check runs first is what lets an Actions-only repo ever reach ``success`` — the
   combined-status endpoint is blind to Actions and reports pending/0 forever (jkha6).

After the reads it runs ``evaluate_reviewer_timeouts`` (§4.1 auto-decline), stamps
``last_polled_at``, advances ``last_activity_at`` on any observed mutation, and
resolves the next phase per the §3.2 poll row. ``PrgroomError``s raised by the gh
adapter (transient / terminal / graphql) propagate unchanged.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import TYPE_CHECKING, Any

from prgroom.gh.client import GhNotFoundError
from prgroom.gh.review_threads import fetch_thread_id_map
from prgroom.lifecycle.gh_errors import vanished_pr_terminal
from prgroom.lifecycle.idempotency import carries_own_marker
from prgroom.lifecycle.predicates import (
    WITHDRAWN_REASON,
    flip_stale_required_reviews,
    has_required_reviewers_to_refresh,
)
from prgroom.lifecycle.quiescence import evaluate_reviewer_timeouts, reviewers_gate_satisfied
from prgroom.prsession.enums import ItemKind, PRPhase, ReviewerKind, ReviewerStatus
from prgroom.prsession.state import Identity, PRGroomingState, ReviewerState, ReviewItem

if TYPE_CHECKING:
    from datetime import datetime

    from prgroom.config import PrgroomConfig
    from prgroom.deps import Deps
    from prgroom.gh.client import GhClient
    from prgroom.prsession.pr_ref import PRRef

_BODY_EXCERPT_LEN = 200

# Combined-status states the gh "commits/{sha}/status" endpoint returns, mapped to
# the §4.1 ci_state vocabulary {success, pending, failure, absent}. GitHub's combined
# status is one of {success, pending, failure, error}; `error` (a CI infrastructure
# error, e.g. a check that errored out) is a non-green terminal verdict and maps to
# `failure`. A 404 (no CI configured) maps to `absent` at the call site; any other
# empty/unknown value is treated as `pending` (CI exists but has no verdict yet).
# This endpoint is the FALLBACK path only: it is blind to GitHub Actions check runs,
# so an Actions-only repo reports pending/total_count=0 here forever (the jkha6
# defect) — _ci_state reads check runs first and only falls back here for a commit
# with no check runs (a classic-commit-status CI).
_CI_STATES_PASSTHROUGH: frozenset[str] = frozenset({"success", "pending", "failure"})
_CI_STATES_FAILURE: frozenset[str] = frozenset({"error"})

# GitHub check-run conclusions that are a non-green terminal verdict. A failure among
# them outranks a still-running run — CI cannot go green once one has failed. The rest
# ({success, neutral, skipped}) are non-failing; a run still queued/in_progress (no
# conclusion yet) holds the rollup at `pending`.
_CHECK_RUN_FAILURE_CONCLUSIONS: frozenset[str] = frozenset(
    {"failure", "timed_out", "action_required", "cancelled", "stale"}
)
_CHECK_RUN_SUCCESS_CONCLUSIONS: frozenset[str] = frozenset({"success", "neutral", "skipped"})
# GitHub caps per_page at 100; one page covers realistic check-run matrices. A commit
# with >100 check runs would miss the overflow — an accepted bound, revisited only if a
# real repo hits it. (Object endpoints can't use --paginate: gh would emit one object
# per page and break json.loads.)
_CHECK_RUNS_PER_PAGE = "100"


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

    new_head = _head_ref_oid(gh, ref)
    if not new_head:
        # Empty remote HEAD (PR opened with no commits): leave the retry counter and
        # last_poll_sha untouched, no phase change. The next poll re-evaluates the
        # bootstrap.
        return state

    pr = _pr_resource(gh, ref)
    merged = bool(pr.get("merged_at"))
    requested_reviewers = pr.get("requested_reviewers") or []
    activity = False

    new_items, terminal_reviews, raw_reviews = _ingest_items(gh, ref, state, now=now)
    if new_items:
        state.items.extend(new_items)
        activity = True
    if _reconcile_reviewers(
        state,
        requested_reviewers=requested_reviewers,
        raw_reviews=raw_reviews,
        terminal_reviews=terminal_reviews,
        new_items=new_items,
        now=now,
    ):
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

    external_push = _apply_sha_attribution(state, new_head, now=now)
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
        reviewers_satisfied=reviewers_gate_satisfied(state),
        needs_reviewer_refresh=has_required_reviewers_to_refresh(state),
    )
    return state


def _head_ref_oid(gh: GhClient, ref: PRRef) -> str:
    """Read the remote HEAD SHA; a 404 (vanished PR/repo) is terminal (§3.6)."""
    try:
        return gh.head_ref_oid(ref)
    except GhNotFoundError as exc:
        raise vanished_pr_terminal(ref) from exc


def _gh_get(gh: GhClient, ref: PRRef, path: str, *, paginate: bool = False) -> Any:
    """``gh.rest("GET", path)`` with a 404 mapped to terminal (vanished PR/repo).

    ``paginate`` opts a collection read into gh's ``--paginate`` page-walk so items
    past the first 30 are returned (the jkha6 defect: an unpaginated list read froze
    grooming once a PR accrued >30 reviews/comments).
    """
    try:
        return gh.rest("GET", path, paginate=paginate)
    except GhNotFoundError as exc:
        raise vanished_pr_terminal(ref) from exc


def _pr_resource(gh: GhClient, ref: PRRef) -> Any:
    """Read the PR resource; a 404 is a vanished PR/repo mid-run (terminal, §3.6).

    Returns the whole payload rather than a derived bool: ``merged_at`` drives the
    §3.2 merge edge AND ``requested_reviewers`` drives reviewer reconciliation
    (§2.1), so one read serves both — no second GET.
    """
    return _gh_get(gh, ref, f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")


# GitHub review states that count as a terminal verdict written by _poll (§4.1).
# COMMENTED is intentionally excluded: §4.1 hedges whether a COMMENTED review is
# terminal to Section 5's fix contract, so MVP treats it as engagement only.
_TERMINAL_REVIEW_STATES: frozenset[str] = frozenset({"APPROVED", "CHANGES_REQUESTED"})

# Statuses a vanished pending request may decline (§2.1.3). Deliberately excludes
# NOT_REQUESTED: its only producer is flip_stale_required_reviews on a push, where it
# means "awaiting rereview after invalidation" — declining it would strand the
# reviewer. Terminal statuses (review_found / declined) are excluded as already-settled.
_WITHDRAWABLE_STATUSES: frozenset[ReviewerStatus] = frozenset(
    {ReviewerStatus.REQUESTED, ReviewerStatus.IN_PROGRESS}
)

# Statuses whose presence in ``requested_reviewers`` on an EXISTING entry is provably a
# NEW ask, so the request window restarts (§2.1). GitHub drops a login from
# ``requested_reviewers`` the instant it submits any review, so a REVIEW_FOUND entry
# re-listed there can only be a re-request; NOT_REQUESTED is a post-push flip whose
# re-listing likewise means someone re-asked. REQUESTED / IN_PROGRESS are an ongoing
# pending pass — leave their window alone (no churn); the ONE exception, handled in
# ``_reconcile_existing_request`` rather than by this set, is an IN_PROGRESS entry on the
# required False->True promotion edge, a one-time transition that cannot churn. DECLINED is
# excluded entirely: a withdrawn decline is handled by the reactivation branch, and a
# timeout decline stays CONTINUOUSLY listed, so its bare presence is not a new ask.
_NEW_ASK_RESTART_STATUSES: frozenset[ReviewerStatus] = frozenset(
    {ReviewerStatus.REVIEW_FOUND, ReviewerStatus.NOT_REQUESTED}
)


def _ingest_items(
    gh: GhClient, ref: PRRef, state: PRGroomingState, *, now: datetime
) -> tuple[list[ReviewItem], dict[str, tuple[datetime, int | None]], list[Any]]:
    """Fetch the three item sources; return new items, terminal verdicts, raw reviews.

    The second element maps a reviewer login to the ``(timestamp, review id)`` of its
    latest APPROVED/CHANGES_REQUESTED review (§4.1) so ``_observe_engagement`` can promote
    that reviewer to ``review_found``. Only items new to ``state`` (natural key
    ``(kind, gh_id)``) are returned; the terminal-verdict map is derived from the
    full reviews response (a verdict can repeat across polls without a new item).

    The third element is the unreduced reviews response — reviewer reconciliation
    (§2.1) needs full authorship, not just the terminal-verdict map.
    """
    seen = {(item.kind, item.identity.gh_id) for item in state.items}
    # prgroom replies by POSTing a NEW comment whose fresh gh_id is unknown to `seen`;
    # without this it would re-ingest its own reply every poll and re-triage forever
    # (recursive self-reply spam). The reply's id was recorded on own_reply_id, so drop
    # any ingested entry (any kind) whose gh_id matches one of our own posted replies.
    own_replies = {str(item.own_reply_id) for item in state.items if item.own_reply_id}
    base = f"repos/{ref.owner}/{ref.repo}"
    # Paginate the three collection reads: prgroom's own reply reviews push any
    # nontrivial PR past GitHub's 30-per-page default, and an unpaginated read froze
    # grooming on the invisible page-2+ items (jkha6).
    raw_issue = _gh_get(gh, ref, f"{base}/issues/{ref.number}/comments", paginate=True)
    raw_reviews = _gh_get(gh, ref, f"{base}/pulls/{ref.number}/reviews", paginate=True)
    raw_review_comments = _gh_get(gh, ref, f"{base}/pulls/{ref.number}/comments", paginate=True)
    # Only review-thread items carry a thread_id, so the bridging GraphQL read is
    # skipped entirely when this PR surfaced no inline comments (most polls).
    thread_id_map = fetch_thread_id_map(gh, ref) if raw_review_comments else {}

    new: list[ReviewItem] = []
    for kind, raw, ts_field in (
        (ItemKind.ISSUE_COMMENT, raw_issue, "created_at"),
        (ItemKind.REVIEW_SUMMARY, raw_reviews, "submitted_at"),
        (ItemKind.REVIEW_THREAD, raw_review_comments, "created_at"),
    ):
        for entry in raw:
            if kind is ItemKind.REVIEW_SUMMARY and not str(entry.get("body") or "").strip():
                # GitHub wraps every inline comment posted outside a formal review in a
                # synthetic COMMENTED review with an empty body; that wrapper's id is
                # minted server-side and never returned to the comment POST, so the
                # own_replies ledger structurally cannot cover it. An empty-body review
                # carries nothing reviewable regardless of author or state — a real
                # verdict still lands via _terminal_review_verdicts, which reads the
                # full reviews response, not the ingested items.
                continue
            if carries_own_marker(str(entry.get("body") or "")):
                # prgroom's own posted effect — never ingest, ledger or no ledger.
                # The state-independent backstop for the crash window where a POST
                # landed but the persist recording own_reply_id was discarded
                # (verb-atomicity §6). Content-keyed, never author-keyed.
                continue
            item = _to_item(kind, entry, ts_field, now=now, thread_id_map=thread_id_map)
            if item.identity.gh_id in own_replies:
                continue  # our own posted reply — never re-ingest (self-reply prevention)
            if (item.kind, item.identity.gh_id) not in seen:
                seen.add((item.kind, item.identity.gh_id))
                new.append(item)
    return new, _terminal_review_verdicts(raw_reviews, now=now), raw_reviews


def _reviewer_kind(user: Any) -> ReviewerKind:
    """Classify a gh user object as bot or human (§2.1).

    Mirrors the pinned check in ``lifecycle/human_review.py``: the API's
    ``type == "Bot"`` is the primary signal, a ``[bot]``-suffixed login the
    defensive fallback for payloads that omit ``type``. Duplicated rather than
    imported — that helper is private, takes a review wrapper rather than a bare
    user object, and is one line.
    """
    user = user or {}
    if str(user.get("type", "")) == "Bot":
        return ReviewerKind.BOT
    return ReviewerKind.BOT if str(user.get("login", "")).endswith("[bot]") else ReviewerKind.HUMAN


def _requested_by_login(requested_reviewers: list[Any]) -> dict[str, Any]:
    """Map each pending-request login to its gh user object (§2.1).

    ``requested_teams`` is deliberately not consulted: a team object carries a slug,
    not members, and GitHub attributes every review to an individual login — a
    team-keyed entry could never resolve against real review data.
    """
    out: dict[str, Any] = {}
    for user in requested_reviewers:
        login = str((user or {}).get("login", ""))
        if login:
            out[login] = user
    return out


def _review_activity_by_login(
    raw_reviews: Any, *, now: datetime
) -> dict[str, tuple[datetime, Any, int | None]]:
    """Map each reviewer login to its latest review time + gh user object + review id (§2.1).

    Unlike ``_terminal_review_verdicts`` this counts EVERY review state, ``COMMENTED``
    included: a login that responded at all is a login prgroom must know about, even
    though only an APPROVED/CHANGES_REQUESTED verdict is terminal.

    The third tuple element is the review's own GitHub id (unique + monotonic per
    submission); it lets the reactivation logic disambiguate a genuinely fresh review
    from a re-observed historical one when they collide on GitHub's second-precision
    timestamp.
    """
    out: dict[str, tuple[datetime, Any, int | None]] = {}
    for entry in raw_reviews:
        user = entry.get("user") or {}
        login = str(user.get("login", ""))
        if not login:
            continue
        submitted = _parse_ts(entry.get("submitted_at"), now=now)
        review_id = _review_id(entry)
        current = out.get(login)
        if current is None or _review_rank(submitted, review_id) > _review_rank(
            current[0], current[2]
        ):
            out[login] = (submitted, user, review_id)
    return out


def _review_id(entry: Any) -> int | None:
    """The review's numeric GitHub id, or ``None`` when the payload omits/malforms it.

    Review ids are unique and monotonically increasing per submission, so a larger id
    at an equal timestamp marks a genuinely newer review. A missing/non-integer id
    degrades to ``None`` — the freshness test then falls back to timestamp-only order.
    """
    raw = entry.get("id")
    if isinstance(raw, int):
        return raw
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _review_rank(submitted: datetime, review_id: int | None) -> tuple[datetime, bool, int]:
    """Ordering key for choosing a login's latest review inside a reducer.

    Newest ``submitted`` timestamp wins; an equal-second tie breaks to the numerically
    larger review id — ids are unique and monotonic per submission, so the larger id is the
    genuinely newer review. Without this tiebreaker a timestamp-only reducer retains
    whichever entry it saw first, and GitHub returns reviews oldest-first, so it would hand
    the OLDER id to the reactivation freshness test, which then compares it against the
    stored ``last_review_id`` and rejects the fresh same-second re-review.

    Id handling is fail-closed: a known id outranks a missing one (the ``is not None`` flag
    sorts below any real id), and two missing ids never displace each other, so an
    equal-second tie with no id on either side is resolved toward the first-seen entry — the
    bb92bde invariant, where an unknown id can never be treated as fresh.
    """
    return (submitted, review_id is not None, review_id if review_id is not None else 0)


def _item_review_id(item: ReviewItem) -> int | None:
    """The review id an ingested activity item carries, for ``last_review_id`` stamping.

    Only a ``REVIEW_SUMMARY`` item is review-derived: its ``gh_id`` is the review's own
    numeric id (unique + monotonic per submission) — the value the reactivation freshness
    test disambiguates an equal-second collision on. An issue or inline comment is not a
    review, so it returns ``None``: its advance of ``last_review_at`` clears
    ``last_review_id``, since no review corresponds to the newly-stamped timestamp. A
    non-integer ``gh_id`` degrades to ``None`` (fail-closed
    — the freshness test then treats a same-second collision as historical, the bb92bde
    invariant).
    """
    if item.kind is not ItemKind.REVIEW_SUMMARY:
        return None
    try:
        return int(item.identity.gh_id)
    except (TypeError, ValueError):
        return None


def _split_verdict(
    verdict: tuple[datetime, int | None] | None,
) -> tuple[datetime | None, int | None]:
    """Split a ``(timestamp, review_id)`` verdict into its parts; ``(None, None)`` when absent."""
    return verdict if verdict is not None else (None, None)


def _seed_reviewer(
    login: str,
    *,
    user: Any,
    required: bool,
    terminal_at: datetime | None,
    terminal_id: int | None,
    reviewed_at: datetime | None,
    reviewed_id: int | None,
    now: datetime,
) -> ReviewerState:
    """Build the entry for a login seen for the first time this poll (§2.1.1).

    A **currently-requested** login (``required`` True — the sole call site passes
    ``required=login in requested_reviewers``) always seeds ``REQUESTED`` at ``now``,
    ignoring any review co-present this poll. GitHub exposes review timestamps at only
    second precision and ``now`` is captured before the PR-resource read, so a review
    landing in the same whole second as the request cannot be ordered against it at seed
    time: honouring it would let an operator's same-second re-request accept the reviewer's
    OLDER verdict and let ``reviewers_gate_satisfied`` pass without the wanted fresh review,
    quiescing the PR behind the reviewer's back.

    The decision is deferred one poll instead. GitHub drops a login from
    ``requested_reviewers`` the instant it submits ANY review, so the NEXT poll's
    presence/absence disambiguates for free: a genuine in-flight response (the reviewer
    answered the pending request) leaves the login ABSENT next poll —
    ``_reconcile_reviewers``' delayed-response pass then promotes it to
    ``REVIEW_FOUND`` / ``IN_PROGRESS`` at the review's own stamps — while a historical
    verdict the operator merely re-requested over keeps the login PRESENT and REQUESTED,
    its stale review correctly rejected by ``_observe_engagement``'s strictly-after gate. A
    bare request with no review seeds ``REQUESTED`` likewise.

    A login discovered ONLY through an already-submitted review (``required`` False — a
    drive-by, or a fast reviewer GitHub already cleared from ``requested_reviewers``) is
    seeded at that review's own verdict and timestamp — NOT left to
    ``_observe_engagement``, whose "activity strictly after ``last_request_at``" gate
    would permanently reject the very review that revealed the reviewer if
    ``last_request_at`` were stamped ``now``. Backdating both stamps to the review keeps
    that comparison honest.
    """
    if not required and terminal_at is not None:
        status, stamp, review_id = ReviewerStatus.REVIEW_FOUND, terminal_at, terminal_id
    elif not required and reviewed_at is not None:
        status, stamp, review_id = ReviewerStatus.IN_PROGRESS, reviewed_at, reviewed_id
    else:
        # A currently-requested login (or a bare request with no review yet) seeds REQUESTED
        # at ``now``; a same-second co-present review is deferred to the next poll's
        # presence/absence disambiguation (see docstring).
        return ReviewerState(
            identity=login,
            kind=_reviewer_kind(user),
            status=ReviewerStatus.REQUESTED,
            required=required,
            last_request_at=now,
        )
    return ReviewerState(
        identity=login,
        kind=_reviewer_kind(user),
        status=status,
        required=required,
        last_request_at=stamp,
        last_review_at=stamp,
        last_review_id=review_id,
    )


def _reactivation_engagement(
    existing: ReviewerState,
    *,
    terminal_at: datetime | None,
    terminal_id: int | None,
    reviewed_at: datetime | None,
    reviewed_id: int | None,
) -> tuple[ReviewerStatus, datetime, int | None] | None:
    """Fresh same-poll engagement for a settled reviewer being (re-)requested (§2.1).

    Shared by both re-request paths: a withdrawn-decline reactivation and the
    REVIEW_FOUND / NOT_REQUESTED window-restart in ``_reconcile_existing_request``. A
    reviewer (re-)requested this poll may have submitted a review in the window between
    the PR-resource GET and the later reviews GET. That review is genuine fresh engagement
    iff it post-dates the reviewer's known history — the recorded withdrawal
    (``declined_at``, ``None`` on the non-declined restart path) or any prior
    ``last_review_at``, whichever is later. A review at or before that boundary is a
    historical verdict that must NOT satisfy the fresh request (mirrors ``_seed_reviewer``'s
    requested-wins rule for a first-seen re-request).

    **Same-second disambiguation.** GitHub review timestamps have second precision, so a
    genuinely fresh re-review submitted in the same wall-clock second as the prior verdict
    lands with ``terminal_at == boundary`` — a strict ``>`` would misfile it as historical,
    reset the reviewer to REQUESTED, and let the next poll read the normal post-review
    absence as a withdrawal, excluding the reviewer from future refreshes. A blind ``>=``
    is equally wrong: at steady state every poll re-observes the SAME verdict at the SAME
    timestamp (``terminal_at == last_review_at``), so equality-as-fresh would re-promote a
    stale verdict on every re-request (the bug commit bb92bde fixed). Review **identity**
    is the sound tiebreaker, but ONLY when the stored ``last_review_id`` corresponds to
    the boundary — i.e. ``last_review_at`` IS the boundary (the max side). Ids are unique
    and monotonic per submission, so under that condition a review whose id strictly
    exceeds the stored id at an equal timestamp is a new submission (fresh), while an
    equal id is the same review re-observed (historical). When ``declined_at`` is the
    boundary instead, the stored id belongs to the older ``last_review_at`` and cannot
    order a verdict at the boundary second; likewise an unknown id on either side (legacy
    state, cleared after a comment advance, malformed payload) cannot disambiguate. In all
    those cases the equal-timestamp verdict falls back to historical — failing closed on
    equality, preserving the bb92bde invariant.

    Returns the ``(status, stamp, review_id)`` to reactivate directly into — REVIEW_FOUND
    for a fresh terminal verdict, IN_PROGRESS for fresh non-terminal engagement — with the
    stamp being the review's own timestamp so the caller can backdate
    ``last_request_at`` / ``last_review_at`` (and record ``last_review_id``) and keep
    ``_observe_engagement``'s strictly-after gate from re-rejecting the very review that
    reopened the reviewer. Returns ``None`` when no fresh engagement arrived, so the caller
    reactivates to REQUESTED at ``now`` as before.
    """
    history = [t for t in (existing.declined_at, existing.last_review_at) if t is not None]
    boundary = max(history) if history else None

    # The stored id disambiguates an equal-second collision ONLY when it corresponds to
    # the boundary — i.e. last_review_at IS the boundary (the max side). When declined_at
    # is the boundary (declined_at > last_review_at), the stored id belongs to the older
    # last_review_at, not to the boundary, so it cannot order a verdict at the boundary
    # second and the tiebreaker is unavailable.
    id_corresponds_to_boundary = (
        existing.last_review_at is not None and boundary == existing.last_review_at
    )

    def _is_fresh(at: datetime, review_id: int | None) -> bool:
        if boundary is None or at > boundary:
            return True
        # Equal-second collision: a strictly-newer review id disambiguates a fresh
        # submission from a re-observed historical verdict, but only when the stored id
        # corresponds to the boundary. Otherwise — or when a missing id on either side
        # cannot disambiguate — fail closed on equality (bb92bde invariant).
        return (
            at == boundary
            and id_corresponds_to_boundary
            and review_id is not None
            and existing.last_review_id is not None
            and review_id > existing.last_review_id
        )

    if terminal_at is not None and _is_fresh(terminal_at, terminal_id):
        return ReviewerStatus.REVIEW_FOUND, terminal_at, terminal_id
    if reviewed_at is not None and _is_fresh(reviewed_at, reviewed_id):
        return ReviewerStatus.IN_PROGRESS, reviewed_at, reviewed_id
    return None


def _reconcile_existing_request(
    existing: ReviewerState,
    *,
    terminal_at: datetime | None,
    terminal_id: int | None,
    reviewed_at: datetime | None,
    reviewed_id: int | None,
    now: datetime,
) -> bool:
    """Reconcile a non-declined EXISTING reviewer that GitHub is requesting NOW (§2.1).

    Two independent effects, both driven by "GitHub is asking this poll":

    - **Promote to required.** A formerly-optional drive-by (``required=False``) who
      later lands in ``requested_reviewers`` is now a formal ask and must count toward
      ``reviewers_gate_satisfied`` — even a currently-IN_PROGRESS drive-by, whose
      in-flight review simply continues and now blocks quiescence until it produces a
      verdict.
    - **Restart the request window** — only when the current status makes this presence
      provably a NEW ask (``_NEW_ASK_RESTART_STATUSES``: REVIEW_FOUND or NOT_REQUESTED).
      GitHub removes a login from ``requested_reviewers`` the instant it reviews, so a
      re-listed REVIEW_FOUND entry is a re-request; a NOT_REQUESTED post-push flip that
      reappears there was re-asked by an operator. First consult this poll's review
      activity (``terminal_at`` / ``reviewed_at``) against the reviewer's PRIOR history
      via ``_reactivation_engagement``: a review can arrive in the window between the
      PR-resource GET (which still lists the login as pending) and the later reviews GET,
      and because GitHub review timestamps have second precision, a verdict posted in the
      same second as ``now`` is not strictly greater than a ``now``-stamped
      ``last_request_at``, so a blind restart would leave ``_observe_engagement`` to
      reject it and the next poll to read the absent request as a withdrawal — losing a
      real fresh verdict. Activity strictly newer than the prior ``last_review_at`` (the
      natural boundary here: this path never touched a decline, so ``declined_at`` is
      ``None``) is fresh post-re-request engagement → go straight to REVIEW_FOUND /
      IN_PROGRESS with both stamps backdated to the review, mirroring the withdrawn-
      reactivation branch. Absent such activity, reset to REQUESTED at ``now`` and clear
      ``last_review_at`` (the recovery-timeout rule, commit 393e22d) so the review-start
      timeout can still fire if the wanted fresh review never lands. A historical verdict
      (timestamp <= prior ``last_review_at`` — the one that made the reviewer
      REVIEW_FOUND) is at or before the boundary, so it correctly does NOT satisfy the
      new window (the bb92bde invariant). The same restart runs for an IN_PROGRESS entry,
      but ONLY on the required False->True promotion edge: a formerly-optional drive-by,
      now formally requested, must not inherit the unsolicited review's engagement stamps —
      a stale ``last_review_at`` near the finish-timeout boundary would let the next poll
      auto-decline the newly-required reviewer off activity that predates the formal ask,
      satisfying the gate without the wanted review. Promotion is a one-time edge, so the
      restart there cannot churn; a steady-state IN_PROGRESS (already required, or
      comment-derived and continuously co-present) is left untouched. A REQUESTED reviewer
      is likewise left alone: required=False + REQUESTED is not a producible state (a
      drive-by is seeded from its review activity, never REQUESTED), so REQUESTED only
      arrives already required, an ongoing pass with a live start-window to preserve.

    Callers gate this on ``existing.status is not DECLINED``: a withdrawn decline is the
    reactivation branch's job, and a timeout decline is continuously present in
    ``requested_reviewers`` (its decline never called gh), so restarting it here would
    undo every timeout decline on the next poll. Returns whether anything changed.
    """
    changed = False
    promoted = not existing.required
    if promoted:
        existing.required = True
        changed = True
    # Restart the request window when this presence is provably a NEW ask. Two disjoint
    # triggers:
    #   - REVIEW_FOUND / NOT_REQUESTED (``_NEW_ASK_RESTART_STATUSES``): GitHub drops a
    #     login from ``requested_reviewers`` the instant it reviews, so re-listing such an
    #     entry is itself proof of a fresh ask — restart on every such presence.
    #   - IN_PROGRESS, but ONLY on the promotion edge. A review-derived IN_PROGRESS
    #     drive-by (a COMMENTED review, which GitHub DID drop from the pending array)
    #     re-listed here is a genuine re-ask; a comment-derived IN_PROGRESS (issue / inline
    #     comments never clear the pending request) is CONTINUOUSLY co-present, so
    #     restarting it on bare presence would churn ``last_request_at`` every poll. The
    #     one-time required False->True promotion is the sound discriminator: a
    #     comment-derived reviewer GitHub is asking for is already ``required=True`` (it
    #     was formally requested), so it never reaches this edge; only the promoted
    #     drive-by does, and the edge fires at most once, so it cannot churn.
    if existing.status in _NEW_ASK_RESTART_STATUSES or (
        promoted and existing.status is ReviewerStatus.IN_PROGRESS
    ):
        reactivation = _reactivation_engagement(
            existing,
            terminal_at=terminal_at,
            terminal_id=terminal_id,
            reviewed_at=reviewed_at,
            reviewed_id=reviewed_id,
        )
        if reactivation is not None:
            existing.status, stamp, review_id = reactivation
            existing.last_request_at = stamp
            existing.last_review_at = stamp
            existing.last_review_id = review_id
        else:
            existing.status = ReviewerStatus.REQUESTED
            existing.last_request_at = now
            existing.last_review_at = None
            existing.last_review_id = None
        changed = True
    return changed


def _reconcile_reviewers(
    state: PRGroomingState,
    *,
    requested_reviewers: list[Any],
    raw_reviews: Any,
    terminal_reviews: dict[str, tuple[datetime, int | None]],
    new_items: list[ReviewItem],
    now: datetime,
) -> bool:
    """Reconcile ``state.reviewers`` against BOTH GitHub reviewer signals (§2.1).

    Neither signal alone is sufficient. GitHub removes a reviewer from
    ``requested_reviewers`` the instant they submit any review — including
    ``COMMENTED`` — so absence from that array is the ORDINARY shape of "they just
    reviewed", and a reviewer who responded before prgroom's first poll appears
    only in the reviews collection.

    Returns whether anything changed, so the caller folds it into ``activity`` the
    same way ``_ingest_items`` / ``_ci_state`` / ``_apply_sha_attribution`` do. An
    unchanged reviewer set is NOT activity — otherwise the §4.1 idle gate could never
    trip and the PR could never quiesce.
    """
    requested = _requested_by_login(requested_reviewers)
    reviewed = _review_activity_by_login(raw_reviews, now=now)
    changed = False
    for login in (*requested, *(ln for ln in reviewed if ln not in requested)):
        terminal_at, terminal_id = _split_verdict(terminal_reviews.get(login))
        reviewed_at, reviewed_user, reviewed_id = reviewed.get(login, (None, None, None))
        existing = state.reviewers.get(login)
        if existing is not None:
            # Reactivate ONLY a genuine withdrawal. Deliberately not "any
            # declined_reason": a timeout decline never removed the reviewer from
            # GitHub's requested_reviewers (quiescence._decline is a local mutation
            # with no gh call), so their login is CONTINUOUSLY present — reactivating
            # on bare presence would undo every timeout decline in the same cycle it
            # fired. request-withdrawn is the one reason defined by an observed
            # ABSENCE, so a reappearance under it is a real transition.
            if (
                login in requested
                and existing.status is ReviewerStatus.DECLINED
                and existing.declined_reason == WITHDRAWN_REASON
            ):
                reactivation = _reactivation_engagement(
                    existing,
                    terminal_at=terminal_at,
                    terminal_id=terminal_id,
                    reviewed_at=reviewed_at,
                    reviewed_id=reviewed_id,
                )
                if reactivation is not None:
                    # Fresh same-poll engagement arrived with the re-request: reactivate
                    # straight into its verdict-appropriate state, backdating both stamps
                    # to the review so _observe_engagement's strictly-after gate keeps it.
                    existing.status, stamp, review_id = reactivation
                    existing.last_request_at = stamp
                    existing.last_review_at = stamp
                    existing.last_review_id = review_id
                else:
                    existing.status = ReviewerStatus.REQUESTED
                    existing.last_request_at = now
                    # Fresh re-request awaiting its first engagement: drop any drive-by
                    # last_review_at recorded while withdrawn. The review-start timeout
                    # only fires while last_review_at is None, so leaving a stale stamp
                    # here would wedge a re-requested reviewer at REQUESTED forever when
                    # the wanted fresh review never lands. Clearing it (and its review id)
                    # keeps the stuck-REQUESTED → timeout → decline recovery alive.
                    existing.last_review_at = None
                    existing.last_review_id = None
                existing.declined_at = None
                existing.declined_reason = None
                changed = True
            elif login in requested and existing.status is not ReviewerStatus.DECLINED:
                # GitHub is asking NOW for a reviewer already on file: promote a drive-by
                # to required, and restart the window when the presence is provably a new
                # ask (§2.1). DECLINED is excluded here — the reactivation branch owns a
                # withdrawn decline, and a timeout decline is continuously listed, so its
                # bare presence must never restart the window.
                if _reconcile_existing_request(
                    existing,
                    terminal_at=terminal_at,
                    terminal_id=terminal_id,
                    reviewed_at=reviewed_at,
                    reviewed_id=reviewed_id,
                    now=now,
                ):
                    changed = True
            continue
        state.reviewers[login] = _seed_reviewer(
            login,
            user=requested.get(login) or reviewed_user,
            # `required` tracks GitHub actually asking — a drive-by reviewer who was
            # never requested must not gain the power to block quiescence (§3).
            required=login in requested,
            terminal_at=terminal_at,
            terminal_id=terminal_id,
            reviewed_at=reviewed_at,
            reviewed_id=reviewed_id,
            now=now,
        )
        changed = True

    # Decline pass — narrowly. A login qualifies only when GitHub is no longer asking
    # and it produced no CURRENT-window activity this poll. Suppression must be scoped to
    # the reviewer's live request window: ``reviewed`` is derived from the FULL reviews
    # response, so a bare ``login in reviewed`` lets ANY historical review keep a reviewer
    # permanently active. A COMMENTED review answering a PRIOR ask would then wedge a
    # since-withdrawn reviewer IN_PROGRESS → timeout-stalled → refreshable, so a later
    # push re-requests an ask the operator already pulled. Only activity belonging to the
    # current window suppresses the withdrawal: an item newly ingested this poll (fresh
    # feedback that is itself what cleared the pending request), or a review whose
    # timestamp is strictly after ``last_request_at`` (in-window engagement, matching
    # ``_observe_engagement``'s strictly-after gate). A review at or before
    # ``last_request_at`` answered a superseded ask and must not block withdrawal.
    new_item_authors = {item.author for item in new_items if item.author}
    for login, reviewer in state.reviewers.items():
        if login in requested or login in new_item_authors:
            continue
        review_activity = reviewed.get(login)
        if review_activity is not None and review_activity[0] > reviewer.last_request_at:
            continue
        # A now-absent REQUESTED reviewer that never engaged, but whose reviews carry a
        # response landing at or after this poll floor of ``last_request_at``, is a DELAYED
        # in-flight response, not a withdrawal: GitHub dropped the login BECAUSE the reviewer
        # submitted. The seed deferred the same-second (request, review) ordering to this
        # poll (``_seed_reviewer``); the observed absence is now the proof the review answered
        # the request. Promote to its verdict-appropriate state at the review's own stamps
        # before the withdrawal branch can fire.
        terminal_at, terminal_id = _split_verdict(terminal_reviews.get(login))
        reviewed_at, _reviewed_user, reviewed_id = reviewed.get(login, (None, None, None))
        promotion = _delayed_in_flight_response(
            reviewer,
            terminal_at=terminal_at,
            terminal_id=terminal_id,
            reviewed_at=reviewed_at,
            reviewed_id=reviewed_id,
        )
        if promotion is not None:
            reviewer.status, stamp, review_id = promotion
            reviewer.last_request_at = stamp
            reviewer.last_review_at = stamp
            reviewer.last_review_id = review_id
            changed = True
            continue
        if reviewer.status in _WITHDRAWABLE_STATUSES:
            reviewer.status = ReviewerStatus.DECLINED
            reviewer.declined_at = now
            reviewer.declined_reason = WITHDRAWN_REASON
            changed = True
        elif _timeout_decline_now_withdrawn(reviewer):
            # A timeout-no-start decline is an in-memory mutation only — GitHub kept the
            # pending request, so the login stayed CONTINUOUSLY listed in
            # requested_reviewers until this poll. A reviewer that never engaged
            # (last_review_at is None) can leave that array ONLY by an operator pulling
            # the request, so this observed absence IS the withdrawal signal. Restamp the
            # retained timeout reason to request-withdrawn — status stays DECLINED, so the
            # reviewer gate is unaffected — so a later re-add reaches the reactivation
            # branch above and reopens the gate. A stalled decline (last_review_at set) is
            # deliberately left alone: it engaged, so GitHub already dropped it and its
            # absence is the ordinary post-review shape, not a withdrawal; it keeps its
            # push-driven re-ask via reviewer_needs_refresh.
            reviewer.declined_at = now
            reviewer.declined_reason = WITHDRAWN_REASON
            changed = True
    return changed


def _delayed_in_flight_response(
    reviewer: ReviewerState,
    *,
    terminal_at: datetime | None,
    terminal_id: int | None,
    reviewed_at: datetime | None,
    reviewed_id: int | None,
) -> tuple[ReviewerStatus, datetime, int | None] | None:
    """Resolve a now-absent REQUESTED reviewer's reviews as a deferred in-flight response (§2.1).

    ``_seed_reviewer`` seeds a currently-requested login ``REQUESTED`` even when a review is
    co-present, because GitHub's second-precision timestamps cannot prove a same-second
    review post-dated the request at seed time. This poll's ABSENCE from
    ``requested_reviewers`` is that proof: GitHub removes a login from the pending array the
    instant it submits ANY review, so a review this reviewer carries stamped at or after
    ``last_request_at`` floored to whole seconds is the genuine response the request was
    waiting for. Returns the verdict-appropriate ``(status, stamp, review_id)`` — REVIEW_FOUND
    for a terminal verdict, IN_PROGRESS for a COMMENTED response — so the caller can backdate
    both stamps to the review and record its id.

    Only a never-engaged REQUESTED reviewer (``last_review_at is None``) qualifies: an
    already-engaged reviewer's absence is the ordinary post-review shape handled by the
    strictly-after suppression above. A review stamped strictly BEFORE
    ``floor(last_request_at)`` is a pre-request historical verdict — the operator pulled the
    request after it — and returns ``None`` so the caller applies the ordinary withdrawal /
    timeout semantics.
    """
    if reviewer.status is not ReviewerStatus.REQUESTED or reviewer.last_review_at is not None:
        return None
    boundary = reviewer.last_request_at.replace(microsecond=0)
    if terminal_at is not None and terminal_at >= boundary:
        return ReviewerStatus.REVIEW_FOUND, terminal_at, terminal_id
    if reviewed_at is not None and reviewed_at >= boundary:
        return ReviewerStatus.IN_PROGRESS, reviewed_at, reviewed_id
    return None


def _timeout_decline_now_withdrawn(reviewer: ReviewerState) -> bool:
    """True iff a never-engaged timeout decline's absence is a genuine withdrawal (§2.1.2).

    Gates the decline-pass restamp: a DECLINED reviewer whose reason is exactly
    ``timeout-no-start`` — the one decline that both implies never-engaged and is
    produced by the in-memory timeout path whose continuous-presence semantics this
    conversion exists for — that never produced any review (``last_review_at is None``).
    Such a reviewer was continuously listed in ``requested_reviewers`` until now, so its
    absence this poll can only be an operator pulling the request. Matching on the exact
    reason (rather than "any non-withdrawn reason") is deliberate: an explicit
    ``user-declined`` — whose contract in ``reviewer_needs_refresh`` keeps it refreshable —
    must NOT be restamped to ``request-withdrawn``, or a later push silently stops issuing
    its intended re-review request. Excludes an already-withdrawn reviewer (idempotent
    across polls) and a stalled decline (``last_review_at`` set), whose absence is the
    ordinary post-review shape.
    """
    return (
        reviewer.status is ReviewerStatus.DECLINED
        and reviewer.declined_reason == "timeout-no-start"
        and reviewer.last_review_at is None
    )


def _terminal_review_verdicts(
    raw_reviews: Any, *, now: datetime
) -> dict[str, tuple[datetime, int | None]]:
    """Map each login to its latest APPROVED/CHANGES_REQUESTED time + review id (§4.1).

    The review id rides alongside the timestamp so the reactivation freshness test can
    tell a genuinely fresh verdict from a re-observed historical one that shares the
    same second-precision GitHub timestamp.
    """
    verdicts: dict[str, tuple[datetime, int | None]] = {}
    for entry in raw_reviews:
        if str(entry.get("state", "")) not in _TERMINAL_REVIEW_STATES:
            continue
        login = str(entry.get("user", {}).get("login", ""))
        if not login:
            continue
        submitted = _parse_ts(entry.get("submitted_at"), now=now)
        review_id = _review_id(entry)
        current = verdicts.get(login)
        if current is None or _review_rank(submitted, review_id) > _review_rank(*current):
            verdicts[login] = (submitted, review_id)
    return verdicts


def _to_item(
    kind: ItemKind,
    entry: dict[str, Any],
    ts_field: str,
    *,
    now: datetime,
    thread_id_map: dict[str, str],
) -> ReviewItem:
    """Build a :class:`ReviewItem` from one gh comment/review payload.

    ``thread_id_map`` ({REST comment databaseId -> GraphQL ``PRRT_*`` node id})
    populates a review-thread item's ``thread_id``; a comment absent from the map
    (or any non-thread kind) leaves it ``""``.
    """
    gh_id = str(entry["id"])
    identity = Identity(gh_id=gh_id)
    if kind is ItemKind.REVIEW_THREAD:
        # GitHub's pulls/{n}/comments exposes the PARENT comment id as
        # `in_reply_to_id` (present only on replies); a top-level inline comment
        # has no parent → 0. The comment's own id lives in `gh_id`. The GraphQL
        # node id (thread_id) comes from the bridging map, keyed by that same gh_id.
        parent = entry.get("in_reply_to_id")
        reply_to = int(parent) if parent is not None else 0
        identity = Identity(
            gh_id=gh_id,
            reply_to_comment_id=reply_to,
            thread_id=thread_id_map.get(gh_id, ""),
        )
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
    terminal_reviews: dict[str, tuple[datetime, int | None]],
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
      back by a re-observed older terminal verdict. ``last_review_id`` upholds the
      coherence invariant "the id of the review observed AT ``last_review_at``, else
      ``None``": a review-derived advance (a COMMENTED review-summary or a terminal
      verdict) stamps that review's own id, while a comment-derived advance CLEARS the
      id — the prior id belonged to the superseded timestamp and no longer corresponds
      to the newly-stamped one. The reactivation freshness test relies on this
      correspondence to break equal-second collisions soundly.
    - An APPROVED / CHANGES_REQUESTED review (a post-request terminal verdict, in
      ``terminal_reviews``) sets the reviewer to ``review_found`` — a genuine verdict
      **supersedes a prior decline** (§4.1: an auto-decline is a fallback for a missing
      verdict — "requested but never engaged" / "engaged but never produced a terminal
      review" — so the real verdict it stood in for wins; both satisfy G_REVIEWERS, so
      only the reported status changes). Any other engagement merely advances a pending
      ``requested`` reviewer to ``in_progress`` and leaves an already-terminal
      ``review_found`` / ``declined`` reviewer's status as-is. A ``not_requested``
      reviewer (invalidated by a push) is NOT promoted by non-terminal engagement — its
      activity still advances ``last_review_at`` (tracking), but only a re-request or a
      post-boundary terminal verdict lifts it out of ``not_requested``, keeping it
      refreshable until the review window is genuinely re-established.

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
        # Each candidate is (activity_time, review_id). review_id is the advancing
        # review's own id when the activity is review-derived — a COMMENTED review-summary
        # item (`_item_review_id`) or the terminal verdict — and None for an issue/inline
        # comment, which advances last_review_at but must NOT disturb last_review_id.
        candidates: list[tuple[datetime, int | None]] = [
            (item.seen_at, _item_review_id(item))
            for item in new_items
            if item.author == reviewer.identity and item.seen_at > reviewer.last_request_at
        ]
        verdict_at, verdict_id = _split_verdict(terminal_reviews.get(reviewer.identity))
        withdrawn = (
            reviewer.status is ReviewerStatus.DECLINED
            and reviewer.declined_reason == WITHDRAWN_REASON
        )
        if verdict_at is not None and verdict_at > reviewer.last_request_at:
            candidates.append((verdict_at, verdict_id))  # post-request terminal verdict
            # A withdrawn reviewer's terminal review is a drive-by against a request that
            # was PULLED. Record it (last_review_at advances below) so a later re-request
            # can order this verdict against the withdrawal, but do NOT promote to
            # review_found: only a review established as post-re-request satisfies a
            # withdrawn request (the reactivation branch handles that). Promoting a
            # pre-re-request drive-by here would swallow the operator's re-request and
            # quiesce the PR on a stale verdict. A timeout decline is different — its
            # verdict genuinely supersedes the fallback decline (§4.1) — so this
            # suppression is withdrawal-only.
            target_status: ReviewerStatus | None = (
                None if withdrawn else ReviewerStatus.REVIEW_FOUND
            )
        elif reviewer.status is ReviewerStatus.REQUESTED:
            # Non-terminal engagement (issue/inline comment, COMMENTED review) advances a
            # pending REQUESTED reviewer to IN_PROGRESS. NOT_REQUESTED is deliberately
            # EXCLUDED: an external push invalidated that reviewer, so post-push chatter
            # must not promote them out of the refreshable set — only a re-request
            # (rereview → REQUESTED) or a post-boundary terminal verdict (the branch above,
            # gated by the stamped invalidation boundary) may. The comment still advances
            # last_review_at below (activity tracking); only the status flip is withheld.
            target_status = ReviewerStatus.IN_PROGRESS
        else:
            target_status = None  # engaged but already terminal — keep current status
        if not candidates:
            continue
        # Advance last_review_at only on a strictly-newer activity time (never regress to
        # a re-observed older verdict); flip status only on a real change. Rank ties with
        # the same _review_rank key the reducers use: on an equal-second tie the greatest
        # review id wins (a review-derived candidate outranks a coincident comment's None,
        # and among reviews the numerically larger — genuinely newer — id is carried
        # forward), so last_review_id records the newest review at the selected timestamp.
        candidate_at, candidate_id = max(candidates, key=lambda c: _review_rank(c[0], c[1]))
        advanced = reviewer.last_review_at is None or candidate_at > reviewer.last_review_at
        if advanced:
            reviewer.last_review_at = candidate_at
            # Coherence invariant: last_review_id is the id of the review observed AT
            # last_review_at, else None. A review-derived advance (a COMMENTED review or a
            # terminal verdict) stamps that review's own id; a comment-derived advance
            # (candidate_id is None) CLEARS the stored id, because the prior id belonged to
            # the OLD timestamp and no longer corresponds to the newly-stamped one. Keeping
            # a stale id would let the reactivation freshness test read an old review at the
            # same second as fresh; clearing it makes that test fail closed instead.
            reviewer.last_review_id = candidate_id
        elif (
            candidate_at == reviewer.last_review_at
            and candidate_id is not None
            and (reviewer.last_review_id is None or candidate_id > reviewer.last_review_id)
        ):
            # Cross-poll equal-second, newer-id update. A review id can surface a poll after
            # last_review_at was stamped (eventual consistency, or a same-second submission
            # seen late). candidate_at ties the stored timestamp so `advanced` is False, yet
            # the candidate ranks newer at that second (_review_rank convention: a known id
            # outranks None, larger id outranks smaller). Record it so the reactivation
            # freshness test keeps a sound tiebreaker; do NOT advance last_review_at or flip
            # status — only the id moves. candidate_id is None is guarded out, so a coincident
            # comment can never clear a stored review id.
            reviewer.last_review_id = candidate_id
            changed = True
        if target_status is not None and reviewer.status is not target_status:
            reviewer.status = target_status
            changed = True
        if advanced:
            changed = True
    return changed


def _ci_state(gh: GhClient, ref: PRRef, head_sha: str) -> str:
    """Resolve §4.1 ci_state for ``head_sha``, preferring check runs over combined-status.

    GitHub Actions reports via check runs; the legacy combined-status endpoint returns
    pending/total_count=0 on an Actions-only repo, so it can never reach `success` there
    (the jkha6 defect). Read check runs first and roll them up; only a commit with no
    check runs (a classic-commit-status CI, or none configured) falls back to
    combined-status.
    """
    rollup = _check_runs_state(gh, ref, head_sha)
    return rollup if rollup is not None else _combined_status_state(gh, ref, head_sha)


def _check_runs_state(gh: GhClient, ref: PRRef, head_sha: str) -> str | None:
    """Roll the head SHA's check runs up to success|pending|failure; ``None`` if none exist.

    ``None`` signals "no check runs on this commit" so ``_ci_state`` falls back to the
    combined-status endpoint. A 404 (unexpected on a valid head SHA) is treated the same
    as no check runs — fall back rather than error.
    """
    try:
        payload = gh.rest(
            "GET",
            f"repos/{ref.owner}/{ref.repo}/commits/{head_sha}/check-runs",
            fields={"per_page": _CHECK_RUNS_PER_PAGE},
        )
    except GhNotFoundError:
        return None
    runs = payload.get("check_runs") or []
    if not runs:
        return None
    all_passed = True
    for run in runs:
        conclusion = str(run.get("conclusion") or "")
        if conclusion in _CHECK_RUN_FAILURE_CONCLUSIONS:
            return "failure"  # a definitive failure outranks any still-running run
        if not (
            str(run.get("status") or "") == "completed"
            and conclusion in _CHECK_RUN_SUCCESS_CONCLUSIONS
        ):
            all_passed = False
    return "success" if all_passed else "pending"


def _combined_status_state(gh: GhClient, ref: PRRef, head_sha: str) -> str:
    """Map the legacy combined-status for ``head_sha`` to ci_state (the fallback path)."""
    try:
        status = gh.rest("GET", f"repos/{ref.owner}/{ref.repo}/commits/{head_sha}/status")
    except GhNotFoundError:
        # No CI configured for this commit → absent (a gate-satisfying state, §4.1).
        # Distinct from a vanished PR: a 404 on the status endpoint is the documented
        # "no CI" case, NOT terminal — so this read does NOT go through _gh_get.
        return "absent"
    raw = str(status.get("state") or "")
    if raw in _CI_STATES_PASSTHROUGH:
        return raw
    if raw in _CI_STATES_FAILURE:  # `error` is a CI error → failure, before the fallback
        return "failure"
    return "pending"


def _apply_sha_attribution(state: PRGroomingState, new_head: str, *, now: datetime) -> bool:
    """Apply §3.4 retry counting/attribution for the observed HEAD; return external-push flag.

    Bootstrap (``last_poll_sha == ""``): set ``last_poll_sha``, no reviewer flip,
    counter untouched — the initial observed push consumes no retry (the counter
    is a 0-indexed count of fix-push retries). Unchanged SHA: no-op. CLI's own
    push (``new_head == last_pushed_head_sha``): advance ``last_poll_sha`` only.
    External push: ``pr_review_retries_used += 1``, advance ``last_poll_sha``,
    flip stale required reviews and stamp the invalidation boundary (``now``) on
    each flipped reviewer.

    The boundary stamp is what keeps a standalone ``poll`` (or a crash after this poll
    persists but before ``rereview``) from silently un-inverting the flip: without it the
    flipped reviewer's pre-push terminal review still satisfies ``terminal_at >
    last_request_at`` on the next poll, so ``_observe_engagement`` restores REVIEW_FOUND
    and ``rereview`` then sees nothing to refresh. Advancing ``last_request_at`` to ``now``
    moves the freshness boundary past that stale verdict (see
    :func:`~prgroom.lifecycle.predicates.flip_stale_required_reviews`).
    """
    if state.last_poll_sha == "":
        state.last_poll_sha = new_head
        return False
    if new_head == state.last_poll_sha:
        return False
    if new_head == state.last_pushed_head_sha:
        # The CLI's own push — already counted by _push, reviewers already flipped.
        state.last_poll_sha = new_head
        return False
    # External push (operator / third party): count it and invalidate stale reviews.
    state.pr_review_retries_used += 1
    state.last_poll_sha = new_head
    flip_stale_required_reviews(state.reviewers, now=now)
    state.last_review_invalidated_sha = new_head
    return True


def _resolve_poll_phase(
    phase: PRPhase,
    *,
    merged: bool,
    new_item: bool,
    external_push: bool,
    has_items: bool,
    reviewers_satisfied: bool,
    needs_reviewer_refresh: bool,
) -> PRPhase:
    """Resolve the next phase from the §3.2 poll row (first applicable edge wins).

    Reaching this resolver with ``phase is IDLE`` implies a non-empty HEAD was
    observed this poll (an empty HEAD returns from ``poll_pr`` before phase
    resolution), so the bootstrap anchor has fired — the only question left for an
    ``idle`` PR is whether a reviewer item is already on file.

    ``reviewers_satisfied`` / ``needs_reviewer_refresh`` arrive as scalars (like
    ``has_items``) rather than as ``state``, keeping this resolver a pure function of
    booleans. Both are evaluated by the caller AFTER reconciliation and SHA
    attribution, so they reflect this poll's reviewer changes.
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
    if phase is PRPhase.QUIESCED and external_push and needs_reviewer_refresh:
        # An external push invalidated a required review on a resting PR. This must take
        # precedence over the `not reviewers_satisfied` arm below: that arm returns
        # AWAITING_REVIEW, which sends the run loop into `wait` and never runs the
        # FIXES_PENDING pipeline's `rereview` step — so the newly pushed head would stay
        # unreviewed indefinitely. Route to FIXES_PENDING so rereview re-asks the
        # invalidated reviewer (mirrors the AWAITING_REVIEW external-push refresh arm below).
        return PRPhase.FIXES_PENDING
    if phase is PRPhase.QUIESCED and not reviewers_satisfied:
        # A reviewer was newly requested (or reactivated) on a resting PR — no push,
        # no new item, so neither existing arm below fires. Without this the phase and
        # the quiescence predicate silently disagree and the request is ignored.
        return PRPhase.AWAITING_REVIEW
    if external_push:
        # awaiting-review / fixes-pending stay; quiesced re-enters awaiting-review;
        # human-gated re-enters fixes-pending (operator resolved the gate).
        if phase is PRPhase.QUIESCED:
            return PRPhase.AWAITING_REVIEW
        if phase is PRPhase.HUMAN_GATED:
            return PRPhase.FIXES_PENDING
        if phase is PRPhase.AWAITING_REVIEW and needs_reviewer_refresh:
            # The push invalidated a required review, but `rereview` is a
            # FIXES_PENDING pipeline step and awaiting-review only ever calls `wait`.
            # Advance so the reviewer actually gets re-asked; the pipeline's rereview
            # step flips them back to `requested`, after which the end-of-cycle
            # resolver returns the PR here with nothing left to refresh.
            return PRPhase.FIXES_PENDING
        return phase
    return phase

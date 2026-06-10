"""Human-review merge-constraint derivation (§4.4, §4.6).

The ``human-review-required`` PR label is a **merge** constraint, not a lifecycle
gate — it never blocks quiescence. This module answers, per status-query, "is the
human-review constraint satisfied, and if not, why didn't approval X count?".

Both inputs are **live gh reads** (labels + PR-approval reviews): the built state
schema stores neither labels nor approval-actor-type, so the data view pins this as
a per-query gh enrichment (Source: GitHub, not state). The fetch is isolated in
:func:`fetch_human_review_inputs`; the precedence + bot-filter logic is the **pure**
:func:`derive_human_review` over the fetched payloads, so it is unit-tested without a
fake subprocess.

The result is **never persisted** — ``human_review_satisfied`` is recomputed every
status query because it is a function of current GitHub state, not lifecycle history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.gh.client import GhNotFoundError

if TYPE_CHECKING:
    from prgroom.gh.client import GhClient
    from prgroom.prsession.pr_ref import PRRef

JsonObj = dict[str, Any]

# §4.4 literal label strings, matched case-insensitively.
_REQUIRED_LABEL = "human-review-required"
_APPROVED_LABEL = "human-approved"
# GitHub's APPROVED review state — the only state that satisfies via the standard
# reviewer flow (§4.4). CHANGES_REQUESTED / COMMENTED reviews are not candidates.
_APPROVED_STATE = "APPROVED"
# The bot-login suffix GitHub appends to app/bot accounts (e.g. github-copilot[bot]).
_BOT_LOGIN_SUFFIX = "[bot]"


@dataclass(frozen=True, slots=True)
class ApprovalCandidate:
    """One examined PR-approval review with its bot-filter outcome (§4.6).

    ``counted`` is whether this approval could satisfy the constraint (a non-bot
    APPROVED); ``reason`` is ``"bot"`` for a filtered bot approval, ``""`` for a
    counted human one. The row exists purely for operator debuggability — "why
    didn't approval X count?".
    """

    login: str
    approved: bool
    counted: bool
    reason: str

    def to_dict(self) -> JsonObj:
        return {
            "login": self.login,
            "approved": self.approved,
            "counted": self.counted,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class HumanReview:
    """The derived §4.6 human-review block. NEVER persisted to state."""

    required: bool
    satisfied_by: str | None
    candidates_seen: list[ApprovalCandidate] = field(default_factory=list)

    @property
    def satisfied(self) -> bool:
        """§4.6 ``merge_gates.human_review_satisfied``: unconstrained, or satisfied."""
        return not self.required or self.satisfied_by is not None

    def to_dict(self) -> JsonObj:
        return {
            "required": self.required,
            "satisfied_by": self.satisfied_by,
            "candidates_seen": [c.to_dict() for c in self.candidates_seen],
        }


def _is_bot(review: JsonObj) -> bool:
    """True iff the review's actor is a GitHub bot (§4.4 load-bearing filter).

    Primary signal is the API's ``user.type == "Bot"`` (the §4.4 pinned
    ``actor.type != "Bot"``); a ``login`` ending in ``[bot]`` is a defensive
    fallback for payloads that omit ``type``. Without this filter, Copilot's
    auto-approval of a self-PR would wrongly satisfy the human-review gate.
    """
    user = review.get("user") or {}
    if str(user.get("type", "")) == "Bot":
        return True
    return str(user.get("login", "")).endswith(_BOT_LOGIN_SUFFIX)


def derive_human_review(*, labels: list[str], reviews: list[JsonObj]) -> HumanReview:
    """Derive the §4.6 human-review block from fetched labels + reviews (pure).

    ``required`` = the ``human-review-required`` label is present (case-insensitive).
    ``satisfied_by`` resolves in PRECEDENCE order: ``"label"`` (a ``human-approved``
    label) > ``"approval:{login}"`` (the FIRST counted APPROVED review, in API order)
    > ``None``. A review is counted only when it is non-bot AND carries a non-empty
    ``login`` — a bot approval (``reason="bot"``) and an anonymous/loginless approval
    (``reason="no-login"``) are both recorded non-counted and cannot satisfy.
    ``candidates_seen`` carries one row per APPROVED review with its filter outcome.
    Label satisfaction does not manufacture a candidate row — candidates are
    PR-approval reviews only.
    """
    lowered = {label.lower() for label in labels}
    required = _REQUIRED_LABEL in lowered
    label_satisfies = _APPROVED_LABEL in lowered

    candidates: list[ApprovalCandidate] = []
    first_human: str | None = None
    for review in reviews:
        if str(review.get("state", "")) != _APPROVED_STATE:
            continue
        login = str((review.get("user") or {}).get("login", ""))
        # Reason precedence: a bot is filtered first (the load-bearing §4.4 filter);
        # a loginless human approval cannot identify an approver, so it cannot
        # satisfy either — recorded non-counted for operator debuggability.
        if _is_bot(review):
            reason = "bot"
        elif not login:
            reason = "no-login"
        else:
            reason = ""
        counted = reason == ""
        candidates.append(
            ApprovalCandidate(login=login, approved=True, counted=counted, reason=reason)
        )
        if counted and first_human is None:
            first_human = login

    if label_satisfies:
        satisfied_by: str | None = "label"
    elif first_human is not None:
        satisfied_by = f"approval:{first_human}"
    else:
        satisfied_by = None

    return HumanReview(required=required, satisfied_by=satisfied_by, candidates_seen=candidates)


def _get(gh: GhClient, ref: PRRef, path: str) -> Any:
    """``gh.rest("GET", path)`` with a 404 mapped to a terminal ``PrgroomError``.

    ``gh.rest`` raises :class:`~prgroom.gh.client.GhNotFoundError` (NOT a
    :class:`PrgroomError`) on a 404. Status enrichment races the lock-free state
    read: the PR can close/delete, or repo access can drop, between the two. A blind
    retry won't bring it back, so a 404 here is terminal (``RUNTIME_GH_TERMINAL``,
    exit 77) — the same mapping ``poll.py``'s ``_vanished_pr_terminal`` pins.
    Other gh failures already arrive as registry-tagged :class:`PrgroomError`s and
    propagate unchanged.
    """
    try:
        return gh.rest("GET", path)
    except GhNotFoundError as exc:
        raise PrgroomError(
            tier=Tier.RUNTIME_TERMINAL_USER,
            code=ErrorCode.RUNTIME_GH_TERMINAL,
            detail=f"PR resource not found: {ref.display()}",
        ) from exc


def fetch_human_review_inputs(gh: GhClient, ref: PRRef) -> tuple[list[str], list[JsonObj]]:
    """Live gh reads for the human-review derivation: labels + PR-approval reviews.

    Two REST GETs — the issue's labels (``issues/{n}/labels``) and the PR's reviews
    (``pulls/{n}/reviews``). Read-only. A 404 maps to a terminal ``PrgroomError`` via
    :func:`_get`; other gh failures propagate as the adapter's registry-tagged error.
    The caller hands the payloads to :func:`derive_human_review`.
    """
    base = f"repos/{ref.owner}/{ref.repo}"
    raw_labels = _get(gh, ref, f"{base}/issues/{ref.number}/labels")
    raw_reviews = _get(gh, ref, f"{base}/pulls/{ref.number}/reviews")
    labels = [str(entry.get("name", "")) for entry in raw_labels]
    reviews = [entry for entry in raw_reviews if isinstance(entry, dict)]
    return labels, reviews

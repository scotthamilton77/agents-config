# prgroom `status` verb + merge-gate contract — Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the read-only `status` verb — the lock-free §3.3 carve-out (with a `--locked` opt-in) — that emits the stable §4.6 `status --json` merge-gate envelope a future merge-gate consumes, plus the §4.4 human-review merge-constraint derivation (label/approval precedence, bot-filtered).

**Architecture:** Three layers. (1) `lifecycle/human_review.py` — a **pure** derivation (`derive_human_review`) over already-fetched gh inputs (labels + review candidates) producing the `human_review` block (`required`, `satisfied_by`, `candidates_seen`) plus a thin gh-enrichment fetch that turns two REST GETs into those inputs. (2) `lifecycle/status.py` — assembles the §4.6 envelope from the in-memory `PRGroomingState` + the human-review block, derives the four `merge_gates` bools and `auto_merge_eligible`. (3) `cli.py` `status` wiring — default path is an **unlocked** `store.read`; `--locked` wraps the read in `with_lock`; renders `--json` or a human-readable default. Nothing here is persisted to state.

**Tech Stack:** Python >=3.11 (the package's declared `requires-python`; developed on 3.14), typer, dataclasses, the existing `prsession` state/enums/`Store`, `lifecycle.quiescence` (gates), `lifecycle.locking.with_lock`, `gh.GhClient`, `errors` registry.

---

## Resolved design decisions

- **human_review uses a LIVE gh fetch, not stored state.** §4.4 prose says "no new API calls" (premised on a `_poll` that fetches labels), but the authoritative data-view (`data-view.md`, contract #1, same source bead) pins `human_review.required` / `satisfied_by` / `candidates_seen` as a "live gh fetch / Source: GitHub, not state". The built state schema stores **neither** labels **nor** approval-actor-type (`ReviewerStatus` has no `approved` value, by design — data-view line 114), so state-only derivation is impossible. The data-view wins. The fetch is isolated in `fetch_human_review_inputs(gh, ref)` (two REST GETs); the precedence + bot-filter logic is a **pure** function over the fetched payloads, unit-tested without a fake subprocess.
- **Bot filter signal:** `user.type == "Bot"` (the §4.4 pinned signal "reviewer.actor.type != Bot"). GitHub's reviews API returns `user.type: "Bot"` for app/bot reviewers (`github-copilot[bot]`). A `login` ending in `[bot]` is a defensive secondary signal (covers payloads where `type` is absent).
- **`satisfied_by` precedence:** `"label"` (a `human-approved` label, case-insensitive) > `"approval:{login}"` (FIRST non-bot APPROVED review, in API order) > `None`.
- **`candidates_seen`:** one row per APPROVED review candidate — `{"login", "approved": true, "counted": bool, "reason": str}`. A review is `counted` only when it is non-bot AND carries a non-empty `login`; `reason` is `"bot"` for a filtered bot, `"no-login"` for an anonymous/loginless approval (which cannot identify an approver), `""` for a counted human. Label-satisfaction does not manufacture a candidate row (candidates are PR-approval reviews only, per §4.6).
- **`status` against a never-polled PR:** the lock-free read raises `StateNotFoundError`. Re-raised as a **dedicated `PreconditionError(PRECONDITION_NO_STATE)`** (user-error tier → exit 2, registry `how` = "run `poll` (or `run`) first"). Reusing `PRECONDITION_NO_ITEMS` was rejected: it is a no-work code → exit **0**, which would falsely tell a scheduler "done" for a PR that was simply never started. `PRECONDITION_NO_STATE` is the only option whose exit code AND operator message are both correct — worth the one new registry entry.
- **No new state fields, no writes.** `status` never calls `store.write`. `human_review_satisfied` is derived per-query, never persisted, and never feeds quiescence.

---

## File structure

- Create `packages/prgroom/src/prgroom/lifecycle/human_review.py` — `HumanReview` dataclass + `ApprovalCandidate` + `fetch_human_review_inputs` + pure `derive_human_review`.
- Create `packages/prgroom/src/prgroom/lifecycle/status.py` — `StatusEnvelope` builder `build_status` returning a `JsonObj` envelope.
- Modify `packages/prgroom/src/prgroom/cli.py` — replace the `status` skeleton with the wired verb (`--json`, `--locked`).
- Create `packages/prgroom/tests/unit/test_human_review.py`
- Create `packages/prgroom/tests/unit/test_status_envelope.py`
- Create `packages/prgroom/tests/unit/test_cli_status.py`

---

## Task 1: human-review pure derivation + gh fetch

**Files:**
- Create: `packages/prgroom/src/prgroom/lifecycle/human_review.py`
- Test: `packages/prgroom/tests/unit/test_human_review.py`

The module:

```python
"""Human-review merge-constraint derivation (§4.4, §4.6).

The `human-review-required` PR label is a MERGE constraint, not a lifecycle
gate — it never blocks quiescence. This module answers, per status-query, "is the
human-review constraint satisfied, and if not, why didn't approval X count?".

Both inputs are LIVE gh reads (labels + PR-approval reviews): the built state
schema stores neither labels nor approval-actor-type, so the data-view pins this
as a per-query gh enrichment (Source: GitHub, not state). The fetch is isolated in
`fetch_human_review_inputs`; the precedence + bot-filter logic is a PURE function
(`derive_human_review`) over the fetched payloads, so it is unit-tested without a
fake subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from prgroom.gh.client import GhClient
    from prgroom.prsession.pr_ref import PRRef

JsonObj = dict[str, Any]

# §4.4 literal label strings, matched case-insensitively.
_REQUIRED_LABEL = "human-review-required"
_APPROVED_LABEL = "human-approved"
# GitHub's APPROVED review state — the only state that can satisfy via the
# standard reviewer flow (§4.4).
_APPROVED_STATE = "APPROVED"


@dataclass(frozen=True, slots=True)
class ApprovalCandidate:
    """One examined PR-approval review with its bot-filter outcome (§4.6).

    `counted` is whether this approval satisfied (or could satisfy) the constraint;
    `reason` is "bot" for a filtered bot approval, "" for a counted human one.
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
        """§4.6 merge_gates.human_review_satisfied: unconstrained, or satisfied."""
        return not self.required or self.satisfied_by is not None

    def to_dict(self) -> JsonObj:
        return {
            "required": self.required,
            "satisfied_by": self.satisfied_by,
            "candidates_seen": [c.to_dict() for c in self.candidates_seen],
        }


def _is_bot(review: JsonObj) -> bool:
    """True iff the review's actor is a GitHub bot (§4.4 load-bearing filter).

    Primary signal is the API's `user.type == "Bot"` (the §4.4 pinned
    `actor.type != "Bot"`); a `login` ending in `[bot]` is a defensive fallback
    for payloads that omit `type`.
    """
    user = review.get("user") or {}
    if str(user.get("type", "")) == "Bot":
        return True
    return str(user.get("login", "")).endswith("[bot]")


def derive_human_review(
    *, labels: list[str], reviews: list[JsonObj]
) -> HumanReview:
    """Derive the §4.6 human-review block from fetched labels + reviews (pure).

    `required` = the `human-review-required` label is present (case-insensitive).
    `satisfied_by` resolves in PRECEDENCE order: `"label"` (a `human-approved`
    label) > `"approval:{login}"` (the FIRST non-bot APPROVED review, in API
    order) > `None`. `candidates_seen` carries one row per APPROVED review with its
    bot-filter outcome, for operator debuggability.
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
        # Reason precedence: bot (the load-bearing §4.4 filter) > no-login (an
        # anonymous approval cannot identify an approver) > counted human.
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

    return HumanReview(
        required=required, satisfied_by=satisfied_by, candidates_seen=candidates
    )


def fetch_human_review_inputs(
    gh: GhClient, ref: PRRef
) -> tuple[list[str], list[JsonObj]]:
    """Live gh reads for the human-review derivation: labels + PR-approval reviews.

    Two REST GETs: the issue's labels (`issues/{n}/labels`) and the PR's reviews
    (`pulls/{n}/reviews`). Read-only; any gh failure propagates as the adapter's
    registry-tagged error. The caller hands the payloads to `derive_human_review`.
    """
    base = f"repos/{ref.owner}/{ref.repo}"
    raw_labels = gh.rest("GET", f"{base}/issues/{ref.number}/labels")
    raw_reviews = gh.rest("GET", f"{base}/pulls/{ref.number}/reviews")
    labels = [str(entry.get("name", "")) for entry in raw_labels]
    reviews = [entry for entry in raw_reviews if isinstance(entry, dict)]
    return labels, reviews
```

- [ ] **Step 1: Write failing tests** (`test_human_review.py`):

```python
"""Tests for the §4.4/§4.6 human-review derivation."""

from __future__ import annotations

from prgroom.lifecycle.human_review import (
    derive_human_review,
    fetch_human_review_inputs,
)
from prgroom.prsession.pr_ref import PRRef


def _review(login: str, state: str = "APPROVED", *, type_: str = "User") -> dict:
    return {"state": state, "user": {"login": login, "type": type_}}


def test_unconstrained_pr_is_satisfied_with_no_label() -> None:
    hr = derive_human_review(labels=[], reviews=[])
    assert hr.required is False
    assert hr.satisfied_by is None
    assert hr.satisfied is True  # not required -> satisfied


def test_required_label_unsatisfied_without_approval() -> None:
    hr = derive_human_review(labels=["human-review-required"], reviews=[])
    assert hr.required is True
    assert hr.satisfied_by is None
    assert hr.satisfied is False


def test_label_satisfaction_takes_precedence_over_approval() -> None:
    hr = derive_human_review(
        labels=["human-review-required", "human-approved"],
        reviews=[_review("alice")],
    )
    assert hr.satisfied_by == "label"


def test_label_match_is_case_insensitive() -> None:
    hr = derive_human_review(labels=["Human-Review-Required", "HUMAN-APPROVED"], reviews=[])
    assert hr.required is True
    assert hr.satisfied_by == "label"


def test_first_non_bot_approval_satisfies() -> None:
    hr = derive_human_review(
        labels=["human-review-required"], reviews=[_review("alice")]
    )
    assert hr.satisfied_by == "approval:alice"
    assert hr.satisfied is True


def test_bot_approval_does_not_satisfy() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("github-copilot[bot]", type_="Bot")],
    )
    assert hr.satisfied_by is None
    assert hr.candidates_seen[0].counted is False
    assert hr.candidates_seen[0].reason == "bot"


def test_bot_detected_by_login_suffix_when_type_absent() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[{"state": "APPROVED", "user": {"login": "dependabot[bot]"}}],
    )
    assert hr.satisfied_by is None
    assert hr.candidates_seen[0].reason == "bot"


def test_bot_then_human_skips_bot_picks_human() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("github-copilot[bot]", type_="Bot"), _review("bob")],
    )
    assert hr.satisfied_by == "approval:bob"
    assert [c.login for c in hr.candidates_seen] == ["github-copilot[bot]", "bob"]
    assert hr.candidates_seen[1].counted is True
    assert hr.candidates_seen[1].reason == ""


def test_first_of_two_humans_wins() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("alice"), _review("bob")],
    )
    assert hr.satisfied_by == "approval:alice"


def test_non_approved_reviews_are_not_candidates() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("alice", state="CHANGES_REQUESTED"), _review("bob", state="COMMENTED")],
    )
    assert hr.candidates_seen == []
    assert hr.satisfied_by is None


def test_to_dict_shape() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("github-copilot[bot]", type_="Bot")],
    )
    d = hr.to_dict()
    assert d == {
        "required": True,
        "satisfied_by": None,
        "candidates_seen": [
            {"login": "github-copilot[bot]", "approved": True, "counted": False, "reason": "bot"}
        ],
    }


class _FakeGh:
    def __init__(self, labels: object, reviews: object) -> None:
        self._labels = labels
        self._reviews = reviews

    def rest(self, method: str, path: str, *, fields: object = None) -> object:
        assert method == "GET"
        return self._labels if path.endswith("/labels") else self._reviews


def test_fetch_maps_payloads_to_inputs() -> None:
    gh = _FakeGh(
        labels=[{"name": "human-review-required"}, {"name": "bug"}],
        reviews=[_review("alice")],
    )
    ref = PRRef(owner="octo", repo="demo", number=7)
    labels, reviews = fetch_human_review_inputs(gh, ref)  # type: ignore[arg-type]
    assert labels == ["human-review-required", "bug"]
    assert reviews == [_review("alice")]
```

- [ ] **Step 2: Run, verify red** — `uv run pytest tests/unit/test_human_review.py -q` → fails (module missing).
- [ ] **Step 3: Create `human_review.py`** as above.
- [ ] **Step 4: Run, verify green.**
- [ ] **Step 5: Commit** — `test(prgroom): human-review derivation — precedence + bot-filter (8.11)` then `feat(prgroom): human-review merge-constraint derivation (8.11)`.

---

## Task 2: status envelope builder

**Files:**
- Create: `packages/prgroom/src/prgroom/lifecycle/status.py`
- Test: `packages/prgroom/tests/unit/test_status_envelope.py`

The module:

```python
"""The §4.6 `status --json` envelope — the stable merge-gate handoff contract.

`build_status` assembles the envelope from the in-memory `PRGroomingState` plus the
derived §4.4 `HumanReview` block. The four `merge_gates` bools and
`auto_merge_eligible` are derived per-query and NEVER persisted. The shape is the
§4.6 stable interface: adding fields is non-breaking; renaming/removing is breaking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from prgroom.prsession.enums import DispositionKind, PRPhase

if TYPE_CHECKING:
    from prgroom.lifecycle.human_review import HumanReview
    from prgroom.prsession.state import PRGroomingState

JsonObj = dict[str, Any]

# Dispositions that block auto-merge (§4.6 no_blocker_items). Mirrors the
# quiescence blocker set — do NOT fork a parallel notion.
_BLOCKER_DISPOSITIONS: frozenset[DispositionKind] = frozenset(
    {DispositionKind.ESCALATED, DispositionKind.FAILED}
)


def _last_error_clear(state: PRGroomingState) -> bool:
    return state.last_error is None or state.last_error == ""


def _no_blocker_items(state: PRGroomingState) -> bool:
    return not any(
        item.disposition is not None and item.disposition.kind in _BLOCKER_DISPOSITIONS
        for item in state.items
    )


def _items_summary(state: PRGroomingState) -> JsonObj:
    summary = {kind.value: 0 for kind in DispositionKind}
    for item in state.items:
        if item.disposition is not None:
            summary[item.disposition.kind.value] += 1
    return summary


def _reviewers(state: PRGroomingState) -> list[JsonObj]:
    from prgroom.prsession.enums import ReviewerKind

    rows: list[JsonObj] = []
    for login in sorted(state.reviewers):
        r = state.reviewers[login]
        rows.append(
            {
                "login": r.identity,
                "required": r.required,
                "is_bot": r.kind is ReviewerKind.BOT,
                "status": r.status.value,
                "declined_reason": r.declined_reason or "",
            }
        )
    return rows


def build_status(state: PRGroomingState, human_review: HumanReview) -> JsonObj:
    """Build the §4.6 `status --json` envelope (pure; never persists)."""
    phase_is_quiesced = state.phase is PRPhase.QUIESCED
    last_error_clear = _last_error_clear(state)
    no_blocker_items = _no_blocker_items(state)
    human_review_satisfied = human_review.satisfied

    auto_merge_eligible = (
        phase_is_quiesced
        and last_error_clear
        and no_blocker_items
        and human_review_satisfied
    )

    quiesced_at = state.quiescence.quiesced_at
    return {
        "pr": state.pr.number,
        "phase": state.phase.value,
        "last_error": state.last_error or "",
        "round": state.round,
        "reviewers": _reviewers(state),
        "ci_state": state.quiescence.ci_state,
        "items_summary": _items_summary(state),
        "last_activity_at": state.last_activity_at.isoformat(),
        "quiesced_at": quiesced_at.isoformat() if quiesced_at is not None else "",
        "merge_gates": {
            "phase_is_quiesced": phase_is_quiesced,
            "last_error_clear": last_error_clear,
            "no_blocker_items": no_blocker_items,
            "human_review_satisfied": human_review_satisfied,
        },
        "human_review": human_review.to_dict(),
        "auto_merge_eligible": auto_merge_eligible,
    }
```

- [ ] **Step 1: Write failing tests** (`test_status_envelope.py`). Cover: envelope shape/keys; each merge-gate bool; the `auto_merge_eligible` AND truth table (all-true → True; flip each one false → False); `items_summary` counts (all 7 disposition keys present, zeroed, incremented per disposition); reviewers sorted by login with `is_bot`/`declined_reason`; `quiesced_at` "" when None vs ISO string when set; `human_review_satisfied` mirrors `HumanReview.satisfied` (required+unsatisfied → gate False).

```python
"""Tests for the §4.6 status envelope builder."""

from __future__ import annotations

from datetime import UTC, datetime

from prgroom.lifecycle.human_review import HumanReview
from prgroom.lifecycle.status import build_status
from prgroom.prsession.enums import (
    DispositionKind,
    ItemKind,
    PRPhase,
    ReviewerKind,
    ReviewerStatus,
)
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
    ReviewerState,
)

_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_REF = PRRef(owner="octo", repo="demo", number=42)


def _state(**overrides: object) -> PRGroomingState:
    base = dict(
        pr=_REF,
        phase=PRPhase.QUIESCED,
        round=2,
        last_polled_at=_NOW,
        last_activity_at=_NOW,
        quiescence=QuiescenceState(ci_state="success", quiesced_at=_NOW),
        last_error=None,
        reviewers={},
        items=[],
    )
    base.update(overrides)
    return PRGroomingState(**base)  # type: ignore[arg-type]


def _item(kind: DispositionKind) -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="c1"),
        author="alice",
        body_excerpt="x",
        seen_at=_NOW,
        disposition=Disposition(kind=kind, decided_at=_NOW, decided_by="claude"),
    )


_SATISFIED = HumanReview(required=False, satisfied_by=None)
_UNSATISFIED = HumanReview(required=True, satisfied_by=None)


def test_envelope_top_level_keys() -> None:
    env = build_status(_state(), _SATISFIED)
    assert set(env) == {
        "pr", "phase", "last_error", "round", "reviewers", "ci_state",
        "items_summary", "last_activity_at", "quiesced_at", "merge_gates",
        "human_review", "auto_merge_eligible",
    }
    assert env["pr"] == 42
    assert env["phase"] == "quiesced"


def test_all_gates_green_is_auto_merge_eligible() -> None:
    env = build_status(_state(), _SATISFIED)
    assert env["merge_gates"] == {
        "phase_is_quiesced": True,
        "last_error_clear": True,
        "no_blocker_items": True,
        "human_review_satisfied": True,
    }
    assert env["auto_merge_eligible"] is True


def test_non_quiesced_phase_blocks_eligibility() -> None:
    env = build_status(_state(phase=PRPhase.AWAITING_REVIEW), _SATISFIED)
    assert env["merge_gates"]["phase_is_quiesced"] is False
    assert env["auto_merge_eligible"] is False


def test_last_error_blocks_eligibility() -> None:
    env = build_status(_state(last_error="LIFECYCLE_HARD_CAP_EXCEEDED"), _SATISFIED)
    assert env["merge_gates"]["last_error_clear"] is False
    assert env["last_error"] == "LIFECYCLE_HARD_CAP_EXCEEDED"
    assert env["auto_merge_eligible"] is False


def test_empty_string_last_error_is_clear() -> None:
    env = build_status(_state(last_error=""), _SATISFIED)
    assert env["merge_gates"]["last_error_clear"] is True


def test_blocker_disposition_blocks_eligibility() -> None:
    for kind in (DispositionKind.ESCALATED, DispositionKind.FAILED):
        env = build_status(_state(items=[_item(kind)]), _SATISFIED)
        assert env["merge_gates"]["no_blocker_items"] is False
        assert env["auto_merge_eligible"] is False


def test_non_blocker_dispositions_do_not_block() -> None:
    env = build_status(_state(items=[_item(DispositionKind.FIXED)]), _SATISFIED)
    assert env["merge_gates"]["no_blocker_items"] is True


def test_unsatisfied_human_review_blocks_eligibility() -> None:
    env = build_status(_state(), _UNSATISFIED)
    assert env["merge_gates"]["human_review_satisfied"] is False
    assert env["auto_merge_eligible"] is False


def test_items_summary_counts_all_kinds() -> None:
    items = [_item(DispositionKind.FIXED), _item(DispositionKind.FIXED), _item(DispositionKind.WONT_FIX)]
    env = build_status(_state(items=items), _SATISFIED)
    assert env["items_summary"]["fixed"] == 2
    assert env["items_summary"]["wont_fix"] == 1
    assert env["items_summary"]["escalated"] == 0
    assert set(env["items_summary"]) == {k.value for k in DispositionKind}


def test_reviewers_sorted_with_bot_and_decline_reason() -> None:
    reviewers = {
        "zoe": ReviewerState(
            identity="zoe", kind=ReviewerKind.HUMAN, status=ReviewerStatus.IN_PROGRESS,
            required=False, last_request_at=_NOW,
        ),
        "copilot": ReviewerState(
            identity="copilot", kind=ReviewerKind.BOT, status=ReviewerStatus.DECLINED,
            required=True, last_request_at=_NOW, declined_reason="timeout-no-start",
        ),
    }
    env = build_status(_state(reviewers=reviewers), _SATISFIED)
    assert [r["login"] for r in env["reviewers"]] == ["copilot", "zoe"]
    assert env["reviewers"][0]["is_bot"] is True
    assert env["reviewers"][0]["declined_reason"] == "timeout-no-start"
    assert env["reviewers"][1]["declined_reason"] == ""


def test_quiesced_at_empty_when_unset() -> None:
    env = build_status(_state(quiescence=QuiescenceState(ci_state="pending")), _SATISFIED)
    assert env["quiesced_at"] == ""


def test_human_review_block_is_embedded() -> None:
    env = build_status(_state(), _UNSATISFIED)
    assert env["human_review"] == {
        "required": True, "satisfied_by": None, "candidates_seen": [],
    }
```

- [ ] **Step 2: Run, verify red.**
- [ ] **Step 3: Create `status.py`.**
- [ ] **Step 4: Run, verify green.**
- [ ] **Step 5: Commit** — `test(prgroom): status envelope + merge-gate truth table (8.11)` then `feat(prgroom): build the §4.6 status --json envelope (8.11)`.

---

## Task 3: CLI `status` wiring (lock-free default, `--locked` opt-in)

**Files:**
- Modify: `packages/prgroom/src/prgroom/cli.py` (replace the `status` skeleton + imports)
- Test: `packages/prgroom/tests/unit/test_cli_status.py`

Replace the skeleton `status` command. New implementation:

```python
@app.command()
def status(
    ctx: typer.Context,
    pr: str = typer.Argument(..., help="PR ref: owner/repo#n or a full PR URL."),
    json_out: bool = typer.Option(False, "--json", help="Emit the §4.6 status envelope as JSON."),
    locked: bool = typer.Option(
        False, "--locked", help="Acquire the PR lock for a strictly-consistent read (exit 75 under contention)."
    ),
) -> None:
    """Print current grooming state + the §4.6 merge-gate envelope (read-only).

    The §3.3 carve-out: the default path is LOCK-FREE — a single ``store.read``
    that may observe a stale-but-internally-consistent snapshot under a concurrent
    write, never partial (writes are file-atomic). ``--locked`` acquires the PR lock
    via :func:`with_lock` for a strictly-consistent read and exits 75 under
    contention. Human-review is a live gh enrichment (labels + PR-approval reviews).
    """
    store: Store = ctx.obj
    try:
        ref = PRRef.parse(pr)
        gh = _build_gh()

        def _read() -> PRGroomingState:
            try:
                return store.read(ref)
            except StateNotFoundError as exc:
                # Dedicated user-error code (exit 2); NOT a no-work code (exit 0).
                raise PreconditionError(
                    ErrorCode.PRECONDITION_NO_STATE,
                    detail=ref.display(),
                ) from exc

        state = with_lock(store, ref, _read) if locked else _read()
        labels, reviews = fetch_human_review_inputs(gh, ref)
        human_review = derive_human_review(labels=labels, reviews=reviews)
        envelope = build_status(state, human_review)
        _render_status(envelope, json_out=json_out)
    except PrgroomError as err:
        raise typer.Exit(code=handle_cli_error(err)) from err
```

Add a render helper near `handle_cli_error`:

```python
def _render_status(envelope: dict[str, object], *, json_out: bool) -> None:
    """Render the §4.6 envelope as JSON (--json) or a human-readable summary."""
    if json_out:
        sys.stdout.write(json.dumps(envelope, indent=2) + "\n")
        return
    gates = envelope["merge_gates"]
    sys.stdout.write(
        f"PR #{envelope['pr']}  phase={envelope['phase']}  round={envelope['round']}\n"
        f"  ci={envelope['ci_state']}  last_error={envelope['last_error'] or '(clear)'}\n"
        f"  items={envelope['items_summary']}\n"
        f"  merge_gates={gates}\n"
        f"  human_review={envelope['human_review']}\n"
        f"  auto_merge_eligible={envelope['auto_merge_eligible']}\n"
    )
```

Imports to add at top of `cli.py`: `import json`; `from prgroom.errors import ErrorCode` (extend the existing errors import); `from prgroom.lifecycle.human_review import derive_human_review, fetch_human_review_inputs`; `from prgroom.lifecycle.status import build_status`; `from prgroom.prsession.state import PRGroomingState` (extend existing). `PreconditionError`, `with_lock`, `StateNotFoundError` are already imported.

- [ ] **Step 1: Write failing tests** (`test_cli_status.py`) — mirror `test_cli_poll.py`'s harness (monkeypatch `_build_store`, `_build_gh`; `CliRunner`). The gh fake here only needs the two human-review reads (labels, reviews), so a small `RecordedRunner([_ok(labels), _ok(reviews)])` `GhCli` suffices. Cover:
  - `--json` against a quiesced, all-green state → exit 0, parseable envelope, `auto_merge_eligible == true`.
  - default (human-readable) render → exit 0, contains `auto_merge_eligible`.
  - never-polled PR (no state) → exit 2, `PRECONDITION_NO_STATE`, `how:` block.
  - malformed ref → exit 2, `PRECONDITION_BAD_PR_REF`.
  - `--locked` under contention (pre-acquire the lock) → exit 75, `PRECONDITION_LOCK_HELD`; assert the gh fake was NOT consulted (lock fails before fetch).
  - default lock-free read SUCCEEDS while the lock is held by another holder (pre-acquire, invoke without `--locked`) → exit 0 — proves the carve-out.
  - bot-only approval + `human-review-required` label → `human_review_satisfied == false`, `auto_merge_eligible == false`, `candidates_seen[0].reason == "bot"`.

```python
"""Tests for the wired ``status`` CLI verb (§3.3 carve-out, §4.6 envelope)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.gh import GhCli
from prgroom.proc import CommandResult
from prgroom.prsession.enums import PRPhase
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import QuiescenceState, bootstrap_state
from tests.conftest import FIXED_NOW
from tests.fakes import RecordedRunner

runner = CliRunner()
_REF = PRRef(owner="octo", repo="demo", number=7)


def _ok(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


def _gh(labels: object = None, reviews: object = None) -> GhCli:
    return GhCli(RecordedRunner([_ok(labels or []), _ok(reviews or [])]))


def _quiesced_state() -> object:
    state = bootstrap_state(_REF, now=FIXED_NOW)
    state.phase = PRPhase.QUIESCED
    state.quiescence = QuiescenceState(ci_state="success", quiesced_at=FIXED_NOW)
    return state


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> InMemoryStore:
    store = InMemoryStore()
    monkeypatch.setattr(cli, "_build_store", lambda _name: store)
    return store


def test_status_json_all_green_eligible(patched: InMemoryStore, monkeypatch) -> None:
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    result = runner.invoke(cli.app, ["status", "octo/demo#7", "--json"])
    assert result.exit_code == 0, result.output
    env = json.loads(result.output)
    assert env["pr"] == 7
    assert env["auto_merge_eligible"] is True


def test_status_default_render(patched: InMemoryStore, monkeypatch) -> None:
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    result = runner.invoke(cli.app, ["status", "octo/demo#7"])
    assert result.exit_code == 0, result.output
    assert "auto_merge_eligible" in result.output


@pytest.mark.usefixtures("patched")
def test_status_missing_state_is_precondition(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    result = runner.invoke(cli.app, ["status", "octo/demo#7"])
    assert result.exit_code == 2
    assert "PRECONDITION_NO_STATE" in result.output
    assert "how:" in result.output


@pytest.mark.usefixtures("patched")
def test_status_malformed_ref(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    result = runner.invoke(cli.app, ["status", "not-a-ref"])
    assert result.exit_code == 2
    assert "PRECONDITION_BAD_PR_REF" in result.output


def test_status_locked_contention_exits_75(patched: InMemoryStore, monkeypatch) -> None:
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    assert patched.try_acquire(_REF)
    try:
        result = runner.invoke(cli.app, ["status", "octo/demo#7", "--locked"])
    finally:
        patched.release(_REF)
    assert result.exit_code == 75
    assert "PRECONDITION_LOCK_HELD" in result.output


def test_status_lockfree_reads_under_held_lock(patched: InMemoryStore, monkeypatch) -> None:
    # The §3.3 carve-out: default status does NOT acquire the lock, so it reads
    # cleanly even while another holder owns it.
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(cli, "_build_gh", lambda: _gh())
    assert patched.try_acquire(_REF)
    try:
        result = runner.invoke(cli.app, ["status", "octo/demo#7", "--json"])
    finally:
        patched.release(_REF)
    assert result.exit_code == 0, result.output


def test_status_bot_approval_does_not_satisfy(patched: InMemoryStore, monkeypatch) -> None:
    patched.write(_REF, _quiesced_state())
    monkeypatch.setattr(
        cli, "_build_gh",
        lambda: _gh(
            labels=[{"name": "human-review-required"}],
            reviews=[{"state": "APPROVED", "user": {"login": "github-copilot[bot]", "type": "Bot"}}],
        ),
    )
    result = runner.invoke(cli.app, ["status", "octo/demo#7", "--json"])
    assert result.exit_code == 0, result.output
    env = json.loads(result.output)
    assert env["merge_gates"]["human_review_satisfied"] is False
    assert env["auto_merge_eligible"] is False
    assert env["human_review"]["candidates_seen"][0]["reason"] == "bot"
```

- [ ] **Step 2: Run, verify red.**
- [ ] **Step 3: Implement the wiring** in `cli.py`.
- [ ] **Step 4: Run, verify green.**
- [ ] **Step 5: Commit** — `test(prgroom): status CLI — carve-out, --locked, --json (8.11)` then `feat(prgroom): wire the status verb through the lock-free carve-out (8.11)`.

---

## Task 4: full gate + completion

- [ ] Run `make ci-prgroom` from repo root; reach green (lint, format, typecheck --strict, coverage, audit, entry).
- [ ] Confirm 100% coverage on the three new modules (no `# pragma: no cover` cheats beyond the established production-boundary idiom).
- [ ] `quality-reviewer` → address → `simplify` → address → `verify-checklist`.

---

## Self-review against the spec

- §4.6 envelope shape (all 12 top-level fields, `merge_gates` 4-tuple, `human_review` 3-tuple, `auto_merge_eligible`) → Task 2 `build_status` + `test_envelope_top_level_keys`.
- `auto_merge_eligible` = AND of the four gates → Task 2 truth-table tests.
- `merge_gates.no_blocker_items` reuses `{ESCALATED, FAILED}` (not a parallel notion) → Task 2 `_BLOCKER_DISPOSITIONS`.
- §4.4 `satisfied_by` precedence (label > approval > None) + bot-filter → Task 1 precedence/bot tests.
- §4.6 `candidates_seen` rows with bot-filter outcome → Task 1 `candidates_seen` tests.
- `human_review_satisfied` derived, never persisted, never gates quiescence → no state field added; `status` never writes (Task 3); quiescence module untouched.
- §3.3 lock-free default; `--locked` → `with_lock`; exit 75 under contention → Task 3 carve-out + contention tests.
- Stable string contract `approval:{login}` → Task 1 `test_first_non_bot_approval_satisfies`.
- enum-exhaustiveness on `DispositionKind` → `_items_summary` enumerates the full enum; `_BLOCKER_DISPOSITIONS` is a closed frozenset (no open match needing `assert_never` — these are membership tests, not match statements).

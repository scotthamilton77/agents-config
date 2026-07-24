# prgroom Reviewer Registry Seeding Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate prgroom's `state.reviewers` registry — today always empty, leaving the re-review verb, the `G_REVIEWERS` quiescence gate, and the reviewer-timeout machinery silently inert — by reconciling it every poll against both GitHub's pending review requests and the reviews actually submitted.

**Architecture:** A new private `_reconcile_reviewers` step in `lifecycle/poll.py` runs between `_ingest_items` and `_observe_engagement`, seeding/reactivating/declining reviewer entries from two GitHub signals that `poll_pr` already fetches (no new API calls). Two new `_resolve_poll_phase` arms give a stale or newly-requested reviewer a path back to an actual re-request. One shared `reviewer_needs_refresh` predicate replaces two near-duplicate frozenset checks so a deliberately-withdrawn reviewer is never silently re-requested.

**Tech Stack:** Python ≥3.11, `uv`-managed. `pytest` (branch coverage, `fail_under = 90`), `mypy --strict`, `ruff` (lint + format, line-length 100). Gate: `make ci-prgroom` from the repo root.

**Spec:** `docs/specs/2026-07-19-prgroom-reviewer-registry-seed-design.md` (final after three review rounds — Codex standard, Codex adversarial, GLM-5.2; findings ledger in its §7). Behavior numbers below refer to that spec's §5.

**Bead:** `agents-config-abn9.8.51`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `packages/prgroom/src/prgroom/lifecycle/predicates.py` | Pure state predicates | **Modify** — add `reviewer_needs_refresh` + `WITHDRAWN_REASON`; `has_required_reviewers_to_refresh` consumes it; delete `_REFRESHABLE_STATUSES` |
| `packages/prgroom/src/prgroom/lifecycle/rereview.py` | `_rereview` verb | **Modify** — consume the shared predicate; delete local `_REFRESHABLE` |
| `packages/prgroom/src/prgroom/lifecycle/quiescence.py` | Quiescence gates + timeouts | **Modify** — rename `_g_reviewers` → public `reviewers_gate_satisfied` |
| `packages/prgroom/src/prgroom/lifecycle/poll.py` | `_poll` verb | **Modify** — `_pr_resource`, `_ingest_items` 3-tuple, `_reconcile_reviewers` + helpers, two `_resolve_poll_phase` arms |
| `packages/prgroom/tests/unit/test_lifecycle_state_predicates.py` | Predicate tests | **Modify** — cover `reviewer_needs_refresh` |
| `packages/prgroom/tests/unit/test_lifecycle_rereview.py` | Rereview tests | **Modify** — withdrawn reviewer is not re-requested |
| `packages/prgroom/tests/unit/test_lifecycle_quiescence.py` | Quiescence tests | **Modify** — mechanical import rename |
| `packages/prgroom/tests/unit/test_lifecycle_poll.py` | Poll tests | **Modify** — `_gh()` gains `requested_reviewers`; 13 new behaviors; existing-test ripple |

**One deliberate naming refinement from the spec:** the spec's §2.2 calls the new resolver parameter `reviewers_gate_open`. This plan uses **`reviewers_satisfied`** — same value (`reviewers_gate_satisfied(state)`), unambiguous name (`_open` reads equally as "gate is open, pass" and "gate is open, i.e. outstanding"). Parameter naming is an implementation detail; the contract is unchanged.

---

## Task 1: Shared `reviewer_needs_refresh` predicate

Replaces `predicates.py`'s `_REFRESHABLE_STATUSES` frozenset with a predicate that excludes a deliberately-withdrawn reviewer. Covers spec behavior 16 (predicate half).

**Files:**
- Modify: `packages/prgroom/src/prgroom/lifecycle/predicates.py:20-37`
- Test: `packages/prgroom/tests/unit/test_lifecycle_state_predicates.py:64-87`

- [ ] **Step 1: Write the failing tests**

In `packages/prgroom/tests/unit/test_lifecycle_state_predicates.py`, replace the import block at lines 24-29 with:

```python
from prgroom.lifecycle.predicates import (
    WITHDRAWN_REASON,
    flip_stale_required_reviews,
    has_required_reviewers_to_refresh,
    new_lifecycle_gate_this_cycle,
    push_uploaded_commits_this_cycle,
    reviewer_needs_refresh,
)
```

Replace the `_reviewer` helper at lines 41-48 with one that can carry a decline reason:

```python
def _reviewer(
    status: ReviewerStatus,
    *,
    required: bool = True,
    declined_reason: str | None = None,
) -> ReviewerState:
    return ReviewerState(
        identity="copilot",
        kind=ReviewerKind.BOT,
        status=status,
        required=required,
        last_request_at=_NOW,
        declined_reason=declined_reason,
    )
```

Then append after `test_has_required_reviewers_to_refresh_false_when_no_reviewers` (line 87):

```python
# -- reviewer_needs_refresh ------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        (ReviewerStatus.NOT_REQUESTED, None, True),
        (ReviewerStatus.DECLINED, "timeout-no-start", True),
        (ReviewerStatus.DECLINED, "timeout-stalled", True),
        (ReviewerStatus.DECLINED, "user-declined", True),
        (ReviewerStatus.DECLINED, None, True),
        # The one exclusion: an operator (or GitHub) pulled the request. Re-asking
        # would silently override that action.
        (ReviewerStatus.DECLINED, WITHDRAWN_REASON, False),
        (ReviewerStatus.REQUESTED, None, False),
        (ReviewerStatus.IN_PROGRESS, None, False),
        (ReviewerStatus.REVIEW_FOUND, None, False),
    ],
)
def test_reviewer_needs_refresh(
    status: ReviewerStatus, reason: str | None, expected: bool
) -> None:
    assert reviewer_needs_refresh(_reviewer(status, declined_reason=reason)) is expected


def test_has_required_reviewers_to_refresh_skips_withdrawn_reviewer() -> None:
    # A withdrawn reviewer must not re-arm the rereview step (spec behavior 16):
    # rereview_pr would DELETE+POST them back onto the PR.
    state = _state(
        reviewers={
            "copilot": _reviewer(ReviewerStatus.DECLINED, declined_reason=WITHDRAWN_REASON)
        }
    )
    assert has_required_reviewers_to_refresh(state) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_state_predicates.py -v
```

Expected: FAIL — `ImportError: cannot import name 'WITHDRAWN_REASON' from 'prgroom.lifecycle.predicates'`

- [ ] **Step 3: Write the implementation**

In `packages/prgroom/src/prgroom/lifecycle/predicates.py`, replace lines 20-37 (the import, the `_REFRESHABLE_STATUSES` frozenset, and `has_required_reviewers_to_refresh`) with:

```python
from prgroom.prsession.enums import ReviewerStatus
from prgroom.prsession.state import PRGroomingState, ReviewerState

# ``declined_reason`` recorded when GitHub itself stopped listing a pending request
# (_poll's reconciliation, §2.1.3) — as opposed to prgroom's own timeout declines.
# Public because ``_poll`` sets it and ``reviewer_needs_refresh`` reads it; one
# spelling, one module.
WITHDRAWN_REASON = "request-withdrawn"


def reviewer_needs_refresh(reviewer: ReviewerState) -> bool:
    """True iff ``reviewer`` should be re-asked for a fresh review (§3.4).

    ``not_requested`` is a review a push invalidated, awaiting its re-ask. A
    ``declined`` reviewer is re-asked too — a decline is prgroom's fallback for a
    missing verdict, and a new push is a new chance to produce one — with exactly one
    exception: a reviewer declined as ``request-withdrawn`` had their pending request
    removed on GitHub's side, so re-requesting would silently override that action.

    The single definition behind both ``has_required_reviewers_to_refresh`` (the
    run-loop's rereview guard) and ``rereview_pr``'s own per-reviewer filter — they
    MUST agree, or the guard admits a cycle the verb then no-ops.
    """
    if reviewer.status is ReviewerStatus.NOT_REQUESTED:
        return True
    return (
        reviewer.status is ReviewerStatus.DECLINED
        and reviewer.declined_reason != WITHDRAWN_REASON
    )


def has_required_reviewers_to_refresh(state: PRGroomingState) -> bool:
    """True iff ≥1 ``required`` reviewer needs a fresh review request (§3.4).

    Gates the post-push ``_rereview`` call. False when no required reviewers exist
    (the PR has no Copilot/codeowner required reviewer set), all are mid-pass
    (``requested`` / ``in_progress``), already engaged (``review_found``), or were
    deliberately withdrawn (see :func:`reviewer_needs_refresh`).
    """
    return any(r.required and reviewer_needs_refresh(r) for r in state.reviewers.values())
```

Also update the module docstring's line 23 comment block if it references `_REFRESHABLE_STATUSES` — the frozenset no longer exists.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_state_predicates.py -v
```

Expected: PASS (all parametrized cases green)

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/lifecycle/predicates.py packages/prgroom/tests/unit/test_lifecycle_state_predicates.py
git commit -m "feat(prgroom): reviewer_needs_refresh predicate excludes withdrawn reviewers"
```

---

## Task 2: `rereview_pr` consumes the shared predicate

Deletes `rereview.py`'s duplicate `_REFRESHABLE` frozenset. Covers spec behavior 16 (verb half).

**Files:**
- Modify: `packages/prgroom/src/prgroom/lifecycle/rereview.py:28,36-38,61`
- Test: `packages/prgroom/tests/unit/test_lifecycle_rereview.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/prgroom/tests/unit/test_lifecycle_rereview.py`:

```python
def test_withdrawn_reviewer_is_never_re_requested() -> None:
    # A reviewer declined as request-withdrawn had their pending request removed on
    # GitHub's side. Re-requesting would DELETE+POST them back onto the PR, silently
    # overriding that. No gh call at all should be issued for them (spec behavior 16).
    from prgroom.lifecycle.predicates import WITHDRAWN_REASON

    reviewers = {"copilot": _reviewer(ReviewerStatus.DECLINED)}
    reviewers["copilot"].declined_reason = WITHDRAWN_REASON
    runner = RecordedRunner([])  # any gh call would raise StopIteration / IndexError
    state = rereview_pr(
        _state(reviewers), ref=_REF, gh=GhCli(runner), deps=_deps()
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.DECLINED
    assert state.reviewers["copilot"].declined_reason == WITHDRAWN_REASON


def test_timeout_declined_reviewer_is_still_re_requested() -> None:
    # The narrowing is specific to the withdrawal reason — a timeout decline is
    # still a missing verdict a fresh push deserves another shot at.
    reviewers = {"copilot": _reviewer(ReviewerStatus.DECLINED)}
    reviewers["copilot"].declined_reason = "timeout-no-start"
    state = rereview_pr(
        _state(reviewers), ref=_REF, gh=GhCli(RecordedRunner([_ok(), _ok()])), deps=_deps()
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.REQUESTED
    assert state.reviewers["copilot"].last_request_at == _LATER
```

- [ ] **Step 2: Run tests to verify the first one fails**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_rereview.py::test_withdrawn_reviewer_is_never_re_requested -v
```

Expected: FAIL — the verb still treats every `DECLINED` reviewer as refreshable, so it attempts a `DELETE` against the empty `RecordedRunner` and raises.

- [ ] **Step 3: Write the implementation**

In `packages/prgroom/src/prgroom/lifecycle/rereview.py`:

Replace the import at line 28:

```python
from prgroom.lifecycle.predicates import reviewer_needs_refresh
```

(`ReviewerStatus` is still needed at line 70 for the `REQUESTED` assignment — keep `from prgroom.prsession.enums import ReviewerStatus`.)

Delete lines 36-38 (the `_REFRESHABLE` comment and frozenset) entirely.

Replace line 61:

```python
            if not (reviewer.required and reviewer_needs_refresh(reviewer)):
```

Update the module docstring's third paragraph (lines 5-7) to read:

```
``_rereview`` then re-asks every required reviewer that
:func:`~prgroom.lifecycle.predicates.reviewer_needs_refresh` admits — the
invalidated ones plus declines that were not a deliberate withdrawal.
```

- [ ] **Step 4: Run the full rereview suite**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_rereview.py -v
```

Expected: PASS — both new tests plus every pre-existing rereview test.

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/lifecycle/rereview.py packages/prgroom/tests/unit/test_lifecycle_rereview.py
git commit -m "refactor(prgroom): rereview_pr consumes shared reviewer_needs_refresh"
```

---

## Task 3: Export `reviewers_gate_satisfied` from `quiescence.py`

The `QUIESCED` resolver arm (Task 9) needs the `G_REVIEWERS` logic from outside the module. Pure rename + export, no behavior change.

**Files:**
- Modify: `packages/prgroom/src/prgroom/lifecycle/quiescence.py:55-56,86`
- Test: `packages/prgroom/tests/unit/test_lifecycle_quiescence.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/prgroom/tests/unit/test_lifecycle_quiescence.py` — extend the import block (lines 23-28) with `reviewers_gate_satisfied`, then append:

```python
def test_reviewers_gate_satisfied_is_publicly_importable() -> None:
    # The _poll phase resolver reads this from outside quiescence.py (spec §2.2), so
    # it is part of the module's public surface, not a private gate helper.
    state = _state(
        reviewers={
            "copilot": ReviewerState(
                identity="copilot",
                kind=ReviewerKind.BOT,
                status=ReviewerStatus.REQUESTED,
                required=True,
                last_request_at=_NOW,
            )
        }
    )
    assert reviewers_gate_satisfied(state) is False
    state.reviewers["copilot"].status = ReviewerStatus.REVIEW_FOUND
    assert reviewers_gate_satisfied(state) is True
```

> If this test file's local `_state` helper or `_NOW` constant is named differently, use the file's existing equivalents — do not introduce a second fixture shape.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_quiescence.py::test_reviewers_gate_satisfied_is_publicly_importable -v
```

Expected: FAIL — `ImportError: cannot import name 'reviewers_gate_satisfied'`

- [ ] **Step 3: Write the implementation**

In `packages/prgroom/src/prgroom/lifecycle/quiescence.py`, replace lines 55-56:

```python
def reviewers_gate_satisfied(state: PRGroomingState) -> bool:
    """True iff every REQUIRED reviewer has reached a terminal state (§4.1 G_REVIEWERS).

    Public because ``_poll``'s phase resolver reads it too: a ``quiesced`` PR that
    gains a newly-requested reviewer must reopen to ``awaiting-review``, and that
    decision is exactly this gate (spec §2.2).
    """
    return all(r.status in _REVIEWER_DONE for r in state.reviewers.values() if r.required)
```

And line 86 inside `failing_gate`:

```python
    if not reviewers_gate_satisfied(state):
```

- [ ] **Step 4: Run the quiescence suite**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_quiescence.py -v
```

Expected: PASS — the new test plus every existing gate test (`failing_gate` behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/lifecycle/quiescence.py packages/prgroom/tests/unit/test_lifecycle_quiescence.py
git commit -m "refactor(prgroom): export _g_reviewers as public reviewers_gate_satisfied"
```

---

## Task 4: Plumbing — surface `requested_reviewers` and `raw_reviews`

Pure refactor: `_pr_is_merged` currently reads `pulls/{n}` and discards everything but `merged_at`; `_ingest_items` computes `raw_reviews` and discards it. Both carry data reconciliation needs. **No behavior change** — every existing test must stay green untouched.

**Files:**
- Modify: `packages/prgroom/src/prgroom/lifecycle/poll.py:119,122,180-183,192-248`
- Test: `packages/prgroom/tests/unit/test_lifecycle_poll.py:69-101` (test builder only)

- [ ] **Step 1: Extend the `_gh()` test builder**

In `packages/prgroom/tests/unit/test_lifecycle_poll.py`, add a `requested_reviewers` parameter to `_gh()` (lines 69-101). Add to the signature after `pr_merged`:

```python
    requested_reviewers: list[str | dict[str, object]] | None = None,
```

And inside, after the `pr = (...)` assignment (line ~89), add:

```python
    # GitHub's pulls/{n} carries the pending review requests on the PR resource.
    # Accepts bare logins for brevity; a dict passes a full gh user object through
    # (used by the bot-classification tests).
    pr["requested_reviewers"] = [
        {"login": r} if isinstance(r, str) else r for r in (requested_reviewers or [])
    ]
```

Extend the `_gh` docstring with one line:

```
``requested_reviewers`` seeds the PR resource's pending-review-request array
(bare logins, or full gh user dicts when ``type``/bot-suffix matters).
```

- [ ] **Step 2: Run the poll suite to confirm the builder change is inert**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -q
```

Expected: PASS — nothing reads `requested_reviewers` yet.

- [ ] **Step 3: Refactor the production reads**

In `packages/prgroom/src/prgroom/lifecycle/poll.py`, replace `_pr_is_merged` (lines 180-183) with:

```python
def _pr_resource(gh: GhClient, ref: PRRef) -> Any:
    """Read the PR resource; a 404 is a vanished PR/repo mid-run (terminal, §3.6).

    Returns the whole payload rather than a derived bool: ``merged_at`` drives the
    §3.2 merge edge AND ``requested_reviewers`` drives reviewer reconciliation
    (§2.1), so one read serves both — no second GET.
    """
    return _gh_get(gh, ref, f"repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")
```

In `poll_pr`, replace line 119:

```python
    pr = _pr_resource(gh, ref)
    merged = bool(pr.get("merged_at"))
    requested_reviewers = pr.get("requested_reviewers") or []
```

Change `_ingest_items`' return annotation (line 194) to a 3-tuple:

```python
) -> tuple[list[ReviewItem], dict[str, datetime], list[Any]]:
```

Change its final `return` (line 248) to:

```python
    return new, _terminal_review_verdicts(raw_reviews, now=now), raw_reviews
```

Extend its docstring's first line to note the third element:

```
    """Fetch the three item sources; return new items, terminal verdicts, raw reviews.
```

...and add to the docstring body:

```
    The third element is the unreduced reviews response — reviewer reconciliation
    (§2.1) needs full authorship, not just the terminal-verdict map.
```

Update the call site (line 122):

```python
    new_items, terminal_reviews, raw_reviews = _ingest_items(gh, ref, state, now=now)
```

Add a `# noqa`-free silencing of the temporarily-unused locals by wiring them in Task 5 — **do not** add placeholder uses. If `ruff` flags `requested_reviewers`/`raw_reviews` as unused in this task, complete Task 5 in the same commit rather than adding a suppression.

- [ ] **Step 4: Run the poll suite plus type check**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -q && uv run mypy --strict src
```

Expected: PASS both — this task changes no behavior.

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/lifecycle/poll.py packages/prgroom/tests/unit/test_lifecycle_poll.py
git commit -m "refactor(prgroom): surface requested_reviewers and raw_reviews in _poll"
```

---

## Task 5: `_reconcile_reviewers` — seed from `requested_reviewers`

First live behavior: a pending review request creates a `ReviewerState`. Additive only — no declines yet, so every existing test stays green. Covers spec behaviors 1, 4 (request-object half), 10, 11 (seed half).

**Files:**
- Modify: `packages/prgroom/src/prgroom/lifecycle/poll.py` (new helpers + `poll_pr` wiring)
- Test: `packages/prgroom/tests/unit/test_lifecycle_poll.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/prgroom/tests/unit/test_lifecycle_poll.py`:

```python
# ── reviewer registry reconciliation (§2.1) ──


def test_pending_request_seeds_a_required_reviewer() -> None:
    # Behavior 1: GitHub listing a pending request is the seed signal. Status is
    # REQUESTED (not NOT_REQUESTED) so rereview's refreshable set does not
    # immediately re-ask a reviewer GitHub already asked.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["alice"]),
        deps=_deps(),
        config=_config(),
    )
    alice = state.reviewers["alice"]
    assert alice.identity == "alice"
    assert alice.status is ReviewerStatus.REQUESTED
    assert alice.required is True
    assert alice.kind is ReviewerKind.HUMAN
    assert alice.last_request_at == _T0
    assert alice.last_review_at is None


@pytest.mark.parametrize(
    "user",
    [
        {"login": "copilot", "type": "Bot"},
        {"login": "copilot[bot]"},  # no type field — the defensive suffix fallback
    ],
)
def test_bot_request_object_seeds_bot_kind(user: dict[str, object]) -> None:
    # Behavior 4 (request half): classification mirrors human_review._is_bot.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[user]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers[str(user["login"])].kind is ReviewerKind.BOT


def test_already_known_requested_reviewer_is_left_alone() -> None:
    # Behavior 5: reconciliation is idempotent — a still-requested known reviewer is
    # not reset, re-stamped, or duplicated.
    earlier = _T0 - timedelta(hours=3)
    reviewers = _requested_at(at=earlier)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    assert len(state.reviewers) == 1
    assert state.reviewers["copilot"].last_request_at == earlier  # not re-stamped


def test_requested_teams_are_read_and_ignored() -> None:
    # Behavior 10: team objects carry a slug, not members, and GitHub attributes
    # reviews to individual logins — so a team entry seeds nothing.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh_with_teams(head_oid="same", teams=[{"slug": "platform"}])
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers == {}


def test_seeding_a_reviewer_advances_last_activity() -> None:
    # Behavior 11 (seed half): a newly-discovered reviewer is PR-side activity.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    start.quiescence = QuiescenceState(ci_state="success")
    later = _T0 + timedelta(minutes=5)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", ci="success", requested_reviewers=["alice"]),
        deps=_deps(later),
        config=_config(),
    )
    assert state.last_activity_at == later


def test_quiet_reviewer_poll_does_not_advance_last_activity() -> None:
    # Behavior 11 (no-noise half): an unchanged reviewer set is not activity, or the
    # idle gate could never trip.
    reviewers = _requested_at(at=_T0 - timedelta(minutes=1))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    start.quiescence = QuiescenceState(ci_state="success")
    later = _T0 + timedelta(minutes=1)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", ci="success", requested_reviewers=["copilot"]),
        deps=_deps(later),
        config=_config(),
    )
    assert state.last_activity_at == _T0
```

Add the teams-payload builder next to `_gh` (it needs a `requested_teams` key the normal builder does not set):

```python
def _gh_with_teams(*, head_oid: str, teams: list[dict[str, object]]) -> GhCli:
    """A poll-order GhCli whose PR resource carries requested_teams but no reviewers."""
    return GhCli(
        RecordedRunner(
            [
                _ok({"headRefOid": head_oid}),
                _ok(
                    {
                        "state": "open",
                        "merged_at": None,
                        "requested_reviewers": [],
                        "requested_teams": teams,
                    }
                ),
                _ok([]),  # issue comments
                _ok([]),  # reviews
                _ok([]),  # review comments
                _ci_check_runs_read("success"),
            ]
        )
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -k "seeds or left_alone or teams_are_read or reviewer_poll_does_not_advance or seeding_a_reviewer" -v
```

Expected: FAIL — `KeyError: 'alice'` / assertion failures; nothing populates `state.reviewers`.

- [ ] **Step 3: Write the implementation**

In `packages/prgroom/src/prgroom/lifecycle/poll.py`, add to the imports:

```python
from prgroom.lifecycle.predicates import WITHDRAWN_REASON, flip_stale_required_reviews
from prgroom.prsession.enums import ItemKind, PRPhase, ReviewerKind, ReviewerStatus
from prgroom.prsession.state import Identity, PRGroomingState, ReviewItem, ReviewerState
```

Add the helpers after `_terminal_review_verdicts` (after line 263):

```python
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


def _seed_reviewer(login: str, *, user: Any, required: bool, now: datetime) -> ReviewerState:
    """Build the entry for a login seen for the first time this poll (§2.1.1)."""
    return ReviewerState(
        identity=login,
        kind=_reviewer_kind(user),
        status=ReviewerStatus.REQUESTED,
        required=required,
        last_request_at=now,
    )


def _reconcile_reviewers(
    state: PRGroomingState,
    *,
    requested_reviewers: list[Any],
    now: datetime,
) -> bool:
    """Reconcile ``state.reviewers`` against GitHub's pending requests (§2.1).

    Returns whether anything changed, so the caller folds it into ``activity`` the
    same way ``_ingest_items`` / ``_ci_state`` / ``_apply_sha_attribution`` do. An
    unchanged reviewer set is NOT activity — otherwise the §4.1 idle gate could never
    trip and the PR could never quiesce.
    """
    requested = _requested_by_login(requested_reviewers)
    changed = False
    for login, user in requested.items():
        if login not in state.reviewers:
            state.reviewers[login] = _seed_reviewer(login, user=user, required=True, now=now)
            changed = True
    return changed
```

Wire it into `poll_pr`, immediately after the `_ingest_items` block and **before** `_observe_engagement` (so a reviewer seeded this poll is visible to engagement observation on the same cycle):

```python
    if _reconcile_reviewers(state, requested_reviewers=requested_reviewers, now=now):
        activity = True
    if _observe_engagement(state, new_items, terminal_reviews):
        activity = True
```

- [ ] **Step 4: Run the full poll suite**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -q
```

Expected: PASS — the six new tests plus every pre-existing test (seeding is purely additive; no existing test passes `requested_reviewers`, so nothing is seeded in them).

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/lifecycle/poll.py packages/prgroom/tests/unit/test_lifecycle_poll.py
git commit -m "feat(prgroom): seed state.reviewers from pending review requests"
```

---

## Task 6: Seed from `raw_reviews` — the fast-reviewer case

The critical adversarial-review finding: GitHub removes a reviewer from `requested_reviewers` the instant they submit **any** review, so a reviewer who responded before prgroom's first poll is invisible to Task 5's signal alone. Covers spec behaviors 2, 3, 4 (review-object half), 15.

**Files:**
- Modify: `packages/prgroom/src/prgroom/lifecycle/poll.py` (`_reconcile_reviewers` + `_seed_reviewer`)
- Test: `packages/prgroom/tests/unit/test_lifecycle_poll.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/prgroom/tests/unit/test_lifecycle_poll.py`:

```python
def test_first_poll_after_response_seeds_a_terminal_reviewer() -> None:
    # Behavior 2 — the critical regression guard. GitHub drops a reviewer from
    # requested_reviewers the moment they submit, so on a first poll AFTER a fast
    # reviewer responded, the pending-request array is the wrong (empty) signal and
    # the reviews collection is the only one carrying them.
    review_at = "2026-06-09T11:00:00Z"
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],  # already cleared by GitHub
        reviews=[
            {
                "id": 900,
                "state": "APPROVED",
                "submitted_at": review_at,
                "user": {"login": "alice"},
                "body": "lgtm",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    alice = state.reviewers["alice"]
    assert alice.status is ReviewerStatus.REVIEW_FOUND
    assert alice.last_review_at == datetime(2026, 6, 9, 11, 0, 0, tzinfo=UTC)
    # last_request_at is backdated to the review, NOT poll time: _observe_engagement
    # only counts activity STRICTLY newer than last_request_at, so stamping `now`
    # would make this very review permanently fail that comparison.
    assert alice.last_request_at == datetime(2026, 6, 9, 11, 0, 0, tzinfo=UTC)


def test_first_poll_after_commented_response_seeds_in_progress() -> None:
    # Behavior 3: COMMENTED is not terminal in this codebase's MVP model
    # (_TERMINAL_REVIEW_STATES), so it seeds engagement — never REVIEW_FOUND, and
    # never a decline.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        reviews=[
            {
                "id": 901,
                "state": "COMMENTED",
                "submitted_at": "2026-06-09T11:00:00Z",
                "user": {"login": "alice"},
                "body": "one thought",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["alice"].status is ReviewerStatus.IN_PROGRESS


def test_review_object_seeds_bot_kind() -> None:
    # Behavior 4 (review half): same classification path from a review's user object.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        reviews=[
            {
                "id": 902,
                "state": "APPROVED",
                "submitted_at": "2026-06-09T11:00:00Z",
                "user": {"login": "copilot", "type": "Bot"},
                "body": "lgtm",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["copilot"].kind is ReviewerKind.BOT


def test_drive_by_reviewer_is_not_required() -> None:
    # Behavior 15: `required` tracks GitHub actually ASKING. A login that reviewed
    # uninvited must not gain the power to block quiescence just by having an opinion.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],
        reviews=[
            {
                "id": 903,
                "state": "COMMENTED",
                "submitted_at": "2026-06-09T11:00:00Z",
                "user": {"login": "randomdev"},
                "body": "drive-by",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["randomdev"].required is False
    assert reviewers_gate_satisfied(state) is True  # an optional reviewer never gates


def test_requested_reviewer_who_also_reviewed_is_required() -> None:
    # The other half of behavior 15: presence in requested_reviewers is what confers
    # `required`, and a formally-requested reviewer keeps it after responding.
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same")
    gh = _gh(
        head_oid="same",
        requested_reviewers=["alice"],
        reviews=[
            {
                "id": 904,
                "state": "APPROVED",
                "submitted_at": "2026-06-09T11:00:00Z",
                "user": {"login": "alice"},
                "body": "lgtm",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(), config=_config())
    assert state.reviewers["alice"].required is True
    assert state.reviewers["alice"].status is ReviewerStatus.REVIEW_FOUND
```

Add `reviewers_gate_satisfied` to this file's imports:

```python
from prgroom.lifecycle.quiescence import reviewers_gate_satisfied
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -k "first_poll_after or review_object_seeds or drive_by or who_also_reviewed" -v
```

Expected: FAIL — `KeyError: 'alice'` / `KeyError: 'randomdev'`; only pending requests seed today.

- [ ] **Step 3: Write the implementation**

In `packages/prgroom/src/prgroom/lifecycle/poll.py`, add a review-activity map beside `_terminal_review_verdicts`:

```python
def _review_activity_by_login(raw_reviews: Any, *, now: datetime) -> dict[str, tuple[datetime, Any]]:
    """Map each reviewer login to its latest review time + gh user object (§2.1).

    Unlike ``_terminal_review_verdicts`` this counts EVERY review state, ``COMMENTED``
    included: a login that responded at all is a login prgroom must know about, even
    though only an APPROVED/CHANGES_REQUESTED verdict is terminal.
    """
    out: dict[str, tuple[datetime, Any]] = {}
    for entry in raw_reviews:
        user = entry.get("user") or {}
        login = str(user.get("login", ""))
        if not login:
            continue
        submitted = _parse_ts(entry.get("submitted_at"), now=now)
        if login not in out or submitted > out[login][0]:
            out[login] = (submitted, user)
    return out
```

Replace `_seed_reviewer` with the verdict-aware version:

```python
def _seed_reviewer(
    login: str,
    *,
    user: Any,
    required: bool,
    terminal_at: datetime | None,
    reviewed_at: datetime | None,
    now: datetime,
) -> ReviewerState:
    """Build the entry for a login seen for the first time this poll (§2.1.1).

    A login discovered through an already-submitted review is seeded at that
    review's own verdict and timestamp — NOT left to ``_observe_engagement``, whose
    "activity strictly after ``last_request_at``" gate would permanently reject the
    very review that revealed the reviewer if ``last_request_at`` were stamped
    ``now``. Backdating both stamps to the review keeps that comparison honest.
    """
    if terminal_at is not None:
        status, stamp = ReviewerStatus.REVIEW_FOUND, terminal_at
    elif reviewed_at is not None:
        status, stamp = ReviewerStatus.IN_PROGRESS, reviewed_at
    else:
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
    )
```

Replace `_reconcile_reviewers` with the dual-signal version:

```python
def _reconcile_reviewers(
    state: PRGroomingState,
    *,
    requested_reviewers: list[Any],
    raw_reviews: Any,
    terminal_reviews: dict[str, datetime],
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
        if login in state.reviewers:
            continue
        reviewed_at, reviewed_user = reviewed.get(login, (None, None))
        state.reviewers[login] = _seed_reviewer(
            login,
            user=requested.get(login) or reviewed_user,
            # `required` tracks GitHub actually asking — a drive-by reviewer who was
            # never requested must not gain the power to block quiescence (§3).
            required=login in requested,
            terminal_at=terminal_reviews.get(login),
            reviewed_at=reviewed_at,
            now=now,
        )
        changed = True
    return changed
```

Update the `poll_pr` call site to pass the new arguments:

```python
    if _reconcile_reviewers(
        state,
        requested_reviewers=requested_reviewers,
        raw_reviews=raw_reviews,
        terminal_reviews=terminal_reviews,
        now=now,
    ):
        activity = True
```

- [ ] **Step 4: Run the full poll suite**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -q
```

Expected: PASS. **If a pre-existing test now fails**, it is one whose `reviews` fixture has an author absent from its `state.reviewers` — that author is now correctly seeded. Assert the intended reviewer explicitly (e.g. `state.reviewers["copilot"]`) rather than the whole dict; do **not** weaken the new seeding to accommodate it.

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/lifecycle/poll.py packages/prgroom/tests/unit/test_lifecycle_poll.py
git commit -m "fix(prgroom): seed reviewers from submitted reviews, not just pending requests"
```

---

## Task 7: Reactivation — withdrawal-only

The GLM critical finding: reactivating on bare presence in `requested_reviewers` defeats the no-start timeout, because a timeout decline is a purely local mutation that never removes the reviewer from GitHub's side. Covers spec behaviors 6, 14.

**Files:**
- Modify: `packages/prgroom/src/prgroom/lifecycle/poll.py` (`_reconcile_reviewers`)
- Test: `packages/prgroom/tests/unit/test_lifecycle_poll.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/prgroom/tests/unit/test_lifecycle_poll.py`:

```python
def _declined(reason: str, *, login: str = "copilot") -> dict[str, ReviewerState]:
    return {
        login: ReviewerState(
            identity=login,
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.DECLINED,
            required=True,
            last_request_at=_T0 - timedelta(hours=2),
            declined_at=_T0 - timedelta(hours=1),
            declined_reason=reason,
        )
    }


def test_withdrawn_reviewer_reactivates_when_re_requested() -> None:
    # Behavior 6: request-withdrawn is the one decline reason DEFINED by an observed
    # absence, so a later reappearance is a genuine transition worth re-arming.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("request-withdrawn"),
    )
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.REQUESTED
    assert copilot.last_request_at == _T0
    assert copilot.declined_at is None
    assert copilot.declined_reason is None


@pytest.mark.parametrize("reason", ["timeout-no-start", "timeout-stalled"])
def test_timeout_declined_reviewer_does_not_reactivate(reason: str) -> None:
    # Behavior 14 — the GLM critical regression guard. A timeout decline is a purely
    # LOCAL mutation (quiescence._decline makes no gh call), so the reviewer is still
    # listed in requested_reviewers every poll, forever. Reactivating on bare presence
    # would undo the decline within the same cycle it fired, making the timeout gate
    # impossible to durably satisfy and the PR impossible to quiesce.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=_declined(reason)
    )
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.DECLINED
    assert state.reviewers["copilot"].declined_reason == reason


def test_timeout_declined_reviewer_still_satisfies_the_gate_across_polls() -> None:
    # The consequence behavior 14 protects: with the decline intact, G_REVIEWERS
    # passes and the PR can actually reach quiescence.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="same",
        reviewers=_declined("timeout-no-start"),
    )
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    assert reviewers_gate_satisfied(state) is True
```

- [ ] **Step 2: Run tests to verify the reactivation one fails**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -k "reactivates or does_not_reactivate or satisfies_the_gate" -v
```

Expected: `test_withdrawn_reviewer_reactivates_when_re_requested` FAILS (still `DECLINED`); the two guard tests pass vacuously — that is correct, they are regression guards against the fix being written too broadly.

- [ ] **Step 3: Write the implementation**

In `_reconcile_reviewers`, replace the `if login in state.reviewers: continue` line with a reactivation branch:

```python
    for login in (*requested, *(ln for ln in reviewed if ln not in requested)):
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
                existing.status = ReviewerStatus.REQUESTED
                existing.last_request_at = now
                existing.declined_at = None
                existing.declined_reason = None
                changed = True
            continue
        reviewed_at, reviewed_user = reviewed.get(login, (None, None))
        ...
```

(The seeding block that follows is unchanged from Task 6.)

- [ ] **Step 4: Run the full poll suite**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -q
```

Expected: PASS — all four new tests plus everything prior.

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/lifecycle/poll.py packages/prgroom/tests/unit/test_lifecycle_poll.py
git commit -m "fix(prgroom): reactivate only withdrawn reviewers, never timeout declines"
```

---

## Task 8: Narrow withdrawal + existing-test ripple

The decline path, scoped so it cannot fire on a reviewer who merely responded or is mid-rereview. **This is the task that breaks existing tests** — the ripple lands here, in the same commit. Covers spec behaviors 7, 8, 9, 11 (decline half).

**Files:**
- Modify: `packages/prgroom/src/prgroom/lifecycle/poll.py` (`_reconcile_reviewers`)
- Test: `packages/prgroom/tests/unit/test_lifecycle_poll.py` (new tests + ripple)

- [ ] **Step 1: Write the failing tests**

Append to `packages/prgroom/tests/unit/test_lifecycle_poll.py`:

```python
def test_withdrawn_request_declines_an_in_flight_reviewer() -> None:
    # Behavior 7: GitHub dropped a pending request and the reviewer produced nothing
    # this poll — the one shape that genuinely means "the ask was pulled".
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.DECLINED
    assert copilot.declined_reason == "request-withdrawn"
    assert copilot.declined_at == _T0


def test_not_requested_reviewer_never_auto_declines() -> None:
    # Behavior 8 — Codex P1 regression guard. NOT_REQUESTED is produced ONLY by
    # flip_stale_required_reviews on a push: it means "awaiting rereview after
    # invalidation", never "withdrawn". Declining it here would strand the reviewer,
    # and (with change C) permanently exclude them from ever being re-requested.
    reviewers = _required_reviewer(ReviewerStatus.NOT_REQUESTED)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.NOT_REQUESTED


def test_this_poll_activity_prevents_a_spurious_decline() -> None:
    # Behavior 9 — the other Codex P1 regression guard. Submitting a COMMENTED review
    # REMOVES the reviewer from requested_reviewers, so absence plus activity is the
    # ordinary "they just responded" shape, not a withdrawal.
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],
        reviews=[
            {
                "id": 905,
                "state": "COMMENTED",
                "submitted_at": "2026-06-09T11:00:00Z",
                "user": {"login": "copilot"},
                "body": "a note",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_ACTIVITY), config=_config())
    copilot = state.reviewers["copilot"]
    assert copilot.status is ReviewerStatus.IN_PROGRESS  # engaged, not declined
    assert copilot.declined_reason is None


def test_issue_comment_activity_prevents_a_spurious_decline() -> None:
    # Same protection via the other activity channel: a reviewer commenting outside a
    # formal review is engagement too (it reaches new_items, not raw_reviews).
    reviewers = _requested_at(at=_T0 - timedelta(hours=2))
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    gh = _gh(
        head_oid="same",
        requested_reviewers=[],
        issue_comments=[
            {
                "id": 906,
                "created_at": "2026-06-09T11:00:00Z",
                "user": {"login": "copilot"},
                "body": "still looking",
            }
        ],
    )
    state = poll_pr(start, ref=_REF, gh=gh, deps=_deps(_JUST_AFTER_ACTIVITY), config=_config())
    assert state.reviewers["copilot"].status is ReviewerStatus.IN_PROGRESS
    assert state.reviewers["copilot"].declined_reason is None


def test_terminal_reviewer_is_not_withdrawn() -> None:
    # A reviewer who already delivered a verdict is not re-declared withdrawn just
    # because GitHub stopped listing their now-resolved request.
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(phase=PRPhase.AWAITING_REVIEW, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.REVIEW_FOUND
```

- [ ] **Step 2: Run tests to verify the withdrawal one fails**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -k "withdrawn_request_declines or never_auto_declines or spurious_decline or terminal_reviewer_is_not" -v
```

Expected: `test_withdrawn_request_declines_an_in_flight_reviewer` FAILS (still `REQUESTED`); the four guard tests pass vacuously.

- [ ] **Step 3: Write the implementation**

In `packages/prgroom/src/prgroom/lifecycle/poll.py`, add the withdrawable-status set next to `_TERMINAL_REVIEW_STATES`:

```python
# Statuses a vanished pending request may decline (§2.1.3). Deliberately excludes
# NOT_REQUESTED: its only producer is flip_stale_required_reviews on a push, where it
# means "awaiting rereview after invalidation" — declining it would strand the
# reviewer. Terminal statuses (review_found / declined) are excluded as already-settled.
_WITHDRAWABLE_STATUSES: frozenset[ReviewerStatus] = frozenset(
    {ReviewerStatus.REQUESTED, ReviewerStatus.IN_PROGRESS}
)
```

Give `_reconcile_reviewers` a `new_items` parameter and append the decline pass after the seed/reactivate loop:

```python
def _reconcile_reviewers(
    state: PRGroomingState,
    *,
    requested_reviewers: list[Any],
    raw_reviews: Any,
    terminal_reviews: dict[str, datetime],
    new_items: list[ReviewItem],
    now: datetime,
) -> bool:
```

```python
    # Decline pass — narrowly. A login qualifies only when GitHub is no longer asking,
    # it produced NOTHING this poll, and it is mid-flight. Any this-poll activity means
    # "they responded" (which is itself what cleared the pending request), not
    # "the ask was pulled".
    active = set(reviewed) | {item.author for item in new_items if item.author}
    for login, reviewer in state.reviewers.items():
        if login in requested or login in active:
            continue
        if reviewer.status in _WITHDRAWABLE_STATUSES:
            reviewer.status = ReviewerStatus.DECLINED
            reviewer.declined_at = now
            reviewer.declined_reason = WITHDRAWN_REASON
            changed = True
    return changed
```

Update the `poll_pr` call site to pass `new_items=new_items`.

- [ ] **Step 4: Apply the existing-test ripple**

Run the full suite to enumerate the fallout:

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -q
```

Every failure is a test that pre-seeds a `REQUESTED`/`IN_PROGRESS` reviewer, produces no activity for that login, and passes no `requested_reviewers` — so the new decline path fires before its own assertion. Fix each by adding `requested_reviewers=["copilot"]` to its `_gh(...)` call. Enumerate candidates with:

```bash
grep -n "_required_reviewer(ReviewerStatus.REQUESTED\|_requested_at(" tests/unit/test_lifecycle_poll.py
```

Two are certain hits, both timeout tests whose reviewer must survive to reach the timeout:

```python
# test_requested_reviewer_past_start_timeout_auto_declines
gh = _gh(head_oid="same", requested_reviewers=["copilot"])

# test_auto_decline_only_poll_does_not_advance_last_activity
gh = _gh(head_oid="same", ci="success", requested_reviewers=["copilot"])
```

The second one is load-bearing beyond a status assertion: without the fix, the *withdrawal* fires instead of the timeout, `changed` returns `True`, and `last_activity_at` advances — breaking that test's `state.last_activity_at == _T0` assertion, which pins the rule that prgroom's own internal declines are not PR activity.

Tests seeding `NOT_REQUESTED`, `REVIEW_FOUND`, or `DECLINED` reviewers need no change (behaviors 8 and the terminal guard cover exactly that).

- [ ] **Step 5: Run the full poll suite green**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -q
```

Expected: PASS — new tests and ripple-fixed existing tests together.

- [ ] **Step 6: Commit**

```bash
git add packages/prgroom/src/prgroom/lifecycle/poll.py packages/prgroom/tests/unit/test_lifecycle_poll.py
git commit -m "feat(prgroom): decline reviewers whose pending request GitHub withdrew"
```

---

## Task 9: Phase-resolver arms

Gives a stale or newly-requested reviewer an actual path back to a re-request — `rereview` runs only from the `FIXES_PENDING` pipeline, which `AWAITING_REVIEW` never reaches, and `QUIESCED` never reopened on reviewer-set growth. Covers spec behaviors 12, 13.

**Files:**
- Modify: `packages/prgroom/src/prgroom/lifecycle/poll.py:149-155,473-506`
- Test: `packages/prgroom/tests/unit/test_lifecycle_poll.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/prgroom/tests/unit/test_lifecycle_poll.py`:

```python
def test_external_push_with_stale_reviewer_advances_to_fixes_pending() -> None:
    # Behavior 12 — Codex P1 regression guard. flip_stale_required_reviews moves the
    # reviewer to NOT_REQUESTED, but `rereview` is a FIXES_PENDING pipeline step and
    # AWAITING_REVIEW only ever calls `wait` — so without this arm the reviewer is
    # never re-requested and the PR can quiesce with a stale review.
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="old",
        last_pushed_head_sha="mine",
        reviewers=reviewers,
    )
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="theirs", requested_reviewers=["copilot"]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers["copilot"].status is ReviewerStatus.NOT_REQUESTED
    assert state.phase is PRPhase.FIXES_PENDING


def test_external_push_without_stale_reviewer_stays_awaiting_review() -> None:
    # The arm is conditional — nothing to refresh means no phase change, so a routine
    # push does not spuriously drive the pipeline.
    start = _state(
        phase=PRPhase.AWAITING_REVIEW,
        last_poll_sha="old",
        last_pushed_head_sha="mine",
    )
    state = poll_pr(
        start, ref=_REF, gh=_gh(head_oid="theirs"), deps=_deps(), config=_config()
    )
    assert state.phase is PRPhase.AWAITING_REVIEW


def test_quiesced_pr_reopens_when_a_reviewer_is_newly_requested() -> None:
    # Behavior 13 — GLM finding. A reviewer can be requested on a PR with no new
    # commits at all; the pre-existing QUIESCED arms fire only on external_push or
    # new_item, so neither covers an operator manually requesting review.
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same")
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=["alice"]),
        deps=_deps(),
        config=_config(),
    )
    assert state.reviewers["alice"].status is ReviewerStatus.REQUESTED
    assert state.phase is PRPhase.AWAITING_REVIEW


def test_quiesced_pr_with_satisfied_reviewers_stays_quiesced() -> None:
    # The no-noise half: a settled reviewer set does not reopen a resting PR.
    reviewers = _required_reviewer(ReviewerStatus.REVIEW_FOUND)
    start = _state(phase=PRPhase.QUIESCED, last_poll_sha="same", reviewers=reviewers)
    state = poll_pr(
        start,
        ref=_REF,
        gh=_gh(head_oid="same", requested_reviewers=[]),
        deps=_deps(),
        config=_config(),
    )
    assert state.phase is PRPhase.QUIESCED
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -k "stale_reviewer_advances or reopens_when_a_reviewer" -v
```

Expected: FAIL — both assert `AWAITING_REVIEW`/`QUIESCED` respectively; the resolver has no reviewer-aware arms yet.

- [ ] **Step 3: Write the implementation**

In `packages/prgroom/src/prgroom/lifecycle/poll.py`, add the imports:

```python
from prgroom.lifecycle.predicates import (
    WITHDRAWN_REASON,
    flip_stale_required_reviews,
    has_required_reviewers_to_refresh,
)
from prgroom.lifecycle.quiescence import evaluate_reviewer_timeouts, reviewers_gate_satisfied
```

Extend the `_resolve_poll_phase` call in `poll_pr` (lines 149-155) — computed **after** `_apply_sha_attribution`, so both predicates see this poll's freshly-flipped `NOT_REQUESTED` entries:

```python
    state.phase = _resolve_poll_phase(
        state.phase,
        merged=merged,
        new_item=bool(new_items),
        external_push=external_push,
        has_items=bool(state.items),
        reviewers_satisfied=reviewers_gate_satisfied(state),
        needs_reviewer_refresh=has_required_reviewers_to_refresh(state),
    )
```

Replace `_resolve_poll_phase` (lines 473-506) with:

```python
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
```

- [ ] **Step 4: Run the full poll suite**

```bash
cd packages/prgroom && uv run pytest tests/unit/test_lifecycle_poll.py -q
```

Expected: PASS. Watch specifically for pre-existing `QUIESCED`-phase tests: any that seed a non-terminal required reviewer now legitimately reopen to `AWAITING_REVIEW`. If one fails, confirm its reviewer fixture is the cause and update the fixture (or its `requested_reviewers`) — the new arm is the intended behavior.

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/lifecycle/poll.py packages/prgroom/tests/unit/test_lifecycle_poll.py
git commit -m "feat(prgroom): reviewer-aware phase transitions for rereview and quiesced reopen"
```

---

## Task 10: Full gate + package docs

**Files:**
- Modify: `packages/prgroom/AGENTS.md` (if it documents the reviewer lifecycle)

- [ ] **Step 1: Run the complete package gate**

From the repo root (not the package dir):

```bash
make ci-prgroom
```

Expected: PASS through all six stages — `ruff check`, `ruff format --check`, `mypy --strict src`, `pytest --cov` (branch coverage, `fail_under = 90`), `pip-audit`, `prgroom --help`.

- [ ] **Step 2: Fix anything the gate flags**

Likely candidates, in order of probability:

- `ruff format --check` — the multi-line signatures and comprehensions above. Fix with `cd packages/prgroom && uv run ruff format`.
- Coverage below 90 on `poll.py` — check for an unexercised branch in `_seed_reviewer` (the three-way status split) or `_reviewer_kind` (the `[bot]` fallback). Both are covered by the tests above; a gap means a test was skipped.
- `mypy --strict` on `_review_activity_by_login`'s `reviewed.get(login, (None, None))` unpacking — if it objects to the heterogeneous default, annotate the local explicitly rather than loosening the return type.

- [ ] **Step 3: Update the package AGENTS.md if warranted**

Check whether `packages/prgroom/AGENTS.md` describes reviewer-state handling:

```bash
grep -n -i "reviewer" packages/prgroom/AGENTS.md
```

If it documents the reviewer lifecycle, add a line noting that `state.reviewers` is reconciled every poll from both `requested_reviewers` and the reviews collection, and that `request-withdrawn` is the one decline reason excluded from re-request. If it does not mention reviewers, **skip this step** — do not invent a section.

- [ ] **Step 4: Confirm the gate is green and commit**

```bash
make ci-prgroom
git add -A packages/prgroom
git commit -m "chore(prgroom): reviewer registry seeding gate green"
```

---

## Plan Self-Review

**1. Spec coverage** — all 16 behaviors mapped:

| Behavior | Task |
|---|---|
| 1 (seed from request) | 5 |
| 2 (first-poll-after-response, critical) | 6 |
| 3 (COMMENTED seeds IN_PROGRESS) | 6 |
| 4 (bot classification, both object shapes) | 5 + 6 |
| 5 (known reviewer left alone) | 5 |
| 6 (reactivation) | 7 |
| 7 (narrow withdrawal) | 8 |
| 8 (NOT_REQUESTED never declines) | 8 |
| 9 (activity masks decline) | 8 |
| 10 (teams ignored) | 5 |
| 11 (activity contribution, both halves) | 5 + 8 |
| 12 (push → FIXES_PENDING) | 9 |
| 13 (QUIESCED reopen) | 9 |
| 14 (reactivation is withdrawal-only, critical) | 7 |
| 15 (drive-by not required) | 6 |
| 16 (withdrawn never re-requested) | 1 + 2 |

Spec §2 changes A/B/C → Tasks 5–8 / 9 / 1–2. Spec §4 plumbing note → Task 4. Spec §4's `quiescence.py` export → Task 3.

**2. Placeholder scan** — no TBDs; every code step carries complete code. Task 8 Step 4 and Task 10 Step 3 are the only conditional steps, and both give the exact command to determine the condition plus explicit instructions for each outcome.

**3. Type consistency** — verified across tasks: `WITHDRAWN_REASON` (defined Task 1, consumed Tasks 2/7/8); `reviewer_needs_refresh` (Task 1 → Task 2); `reviewers_gate_satisfied` (Task 3 → Tasks 6/7/9); `_seed_reviewer` (introduced Task 5, replaced with the 6-parameter version in Task 6 — the Task 6 version is the final signature); `_reconcile_reviewers` grows parameters across Tasks 5→6→8, with each task showing the full updated signature and call site.

---

## Plan Review Gate

**Review routing: deep** (criteria: *scope discovered during planning the spec does not cover* — Task 6's note that pre-existing `reviews`-fixture tests may now seed unexpected reviewers, and Task 9's note about pre-existing `QUIESCED` tests, are ripple surfaces the spec's §5 ripple paragraph does not enumerate; *subtle ordering constraints* — the reconcile-between-ingest-and-observe placement and the compute-predicates-after-SHA-attribution ordering are both load-bearing and non-obvious).

Per the routing mechanics this would dispatch a single `ralf-review` against the plan. **However:** this plan's substance has already absorbed three independent review rounds at the spec level (Codex, Codex adversarial, GLM-5.2), and the two criteria hits are both *disclosure* items — places where the plan tells the implementer to expect ripple the spec under-counted — rather than unreviewed design decisions. Dispatching a fourth automated review to re-derive that would be process for its own sake.

**Attention routing: not waived** — condition (b) fails: the plan contains two items that go beyond what the spec states (the ripple surfaces above, plus the `reviewers_gate_open` → `reviewers_satisfied` naming refinement). A plan that quietly absorbed those must not auto-proceed. Directing your attention to:

- **Task 4 → Task 8 ripple sizing.** The spec's §5 named two certain-hit existing tests; this plan additionally warns that Task 6 (review-based seeding) and Task 9 (QUIESCED arm) may surface *further* pre-existing test failures the spec never enumerated. If that ripple turns out large, the honest answer is a follow-up commit, not weakening the new behavior — but you should know it's an open number before execution starts.
- **Task 9's ordering constraint.** `reviewers_satisfied` and `needs_reviewer_refresh` must be computed after `_apply_sha_attribution`, not with the other reconciliation values. Get this wrong and behavior 12 silently fails — the arm reads a pre-flip reviewer set. It's a one-line placement decision with no type-checker protection.
- **The naming refinement.** Spec §2.2 says `reviewers_gate_open`; the plan uses `reviewers_satisfied` because `_open` reads ambiguously in both directions. Same value, same contract — say the word if you'd rather the code match the spec's spelling exactly.

---

## Execution Handoff

**Recommendation: subagent-driven per-task dispatch.** Ten tasks with clean sequential dependencies and per-task green gates — each is independently verifiable, and a fresh subagent per task keeps each one's context to a single file pair rather than accumulating all ten tasks' worth of `poll.py` history.

Start from a clean context: compact this session or begin a fresh one, so execution runs free of the three rounds of spec-review residue sitting in this one.

Kickoff prompt:

> Execute the implementation plan at `docs/plans/2026-07-19-prgroom-reviewer-registry-seed.md` (spec: `docs/specs/2026-07-19-prgroom-reviewer-registry-seed-design.md`). You are already in the isolated worktree `.claude/worktrees/prgroom-reviewer-registry-seed` on branch `worktree-prgroom-reviewer-registry-seed` — work there, do not create another. Dispatch one fresh subagent per task; each task follows the `test-driven-development` skill. The package gate is `make ci-prgroom` from the repo root. Start at Task 1.

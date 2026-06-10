# prgroom `_poll` Read Path Implementation Plan (8.9a)

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the read-only `_poll` lifecycle internal — fetch a PR's review state via the gh adapter, ingest review items + reviewers into `PRGroomingState`, apply round/attribution/phase semantics per §3.2/§3.4/§4.1 — and wire the `poll` CLI verb through the lock wrapper. No GitHub writes.

**Architecture:** A pure-ish free function `poll_pr(state, *, ref, gh, deps, config)` (the lock-assuming internal: reads no disk, receives in-memory state, returns the mutated state) lives in `src/prgroom/lifecycle/poll.py`. It assembles the gh read via the injected `GhClient`, applies the §3.4 round/attribution rules and §3.2 phase transitions, reuses the existing `flip_stale_required_reviews` predicate and `evaluate_reviewer_timeouts`, and never mutates GitHub. The `poll` CLI verb in `cli.py` resolves the store + gh adapter, parses the PR ref, then runs `read → poll_pr → write` under `with_lock`, rendering errors via `handle_cli_error`.

**Tech Stack:** Python 3.11+, typer CLI, `gh` subprocess via `GhClient` Protocol, `CommandRunner` boundary, pytest + coverage (`make ci-prgroom`, keep 100%).

---

## Scope (8.9a — the bead's FIRST acceptance bullet ONLY)

IN: `_poll` read path + bootstrap/attribution/phase/reviewer-flip + gh error-code mapping; the `poll` CLI verb wired through the lock wrapper. Read-only.

OUT (later beads): `_cluster`, `_fix` (8.9b); `_push`, `_rereview`, `_resolve` (8.9c); the `_run` aggregator (8.10); the agent-dispatch arm; the `status` verb (8.11).

## What `_poll` reads (the gh read contract, c4-l3-lifecycle `_poll` component + §4.1)

Per cycle, `_poll` issues these gh reads via the injected `GhClient` (all read-only):

1. `gh.head_ref_oid(ref)` → current remote HEAD SHA. **Drives** bootstrap / attribution / push detection.
2. PR resource: `gh.rest("GET", f"repos/{owner}/{repo}/pulls/{number}")` → `{state, merged_at, ...}`. **Drives** the PR-closed-via-merge → `merged` transition. A 404 here (`GhNotFoundError`) is mapped to `RUNTIME_GH_TERMINAL` by this verb (the PR/repo vanished mid-run; the startup-precondition owner for `PRECONDITION_REPO_UNREACHABLE` is out of 8.9a scope, so the read path treats a 404 as terminal).
3. Issue comments: `gh.rest("GET", f"repos/{owner}/{repo}/issues/{number}/comments")` → `issue_comment` items + reviewer engagement.
4. Reviews: `gh.rest("GET", f"repos/{owner}/{repo}/pulls/{number}/reviews")` → `review_summary` items + reviewer engagement (a submitted review lands the reviewer in `review_found`).
5. Review (inline) comments: `gh.rest("GET", f"repos/{owner}/{repo}/pulls/{number}/comments")` → `review_thread` items + reviewer engagement.
6. CI rollup: `gh.rest("GET", f"repos/{owner}/{repo}/commits/{head_sha}/status")` → combined-status `state` mapped to `success | pending | failure | absent` for `quiescence.ci_state`.

`_poll` then: appends only NEW items (natural key `(kind, gh_id)` — never re-append an item already in state), flips reviewer status on observed engagement (sets `last_review_at`, `status=in_progress` on first engagement), calls `evaluate_reviewer_timeouts`, updates `quiescence.ci_state` + `last_activity_at`, and resolves the next phase per the §3.2 poll row.

## §3.4 round + attribution rules (the heart of the bullet)

Given `new_head = gh.head_ref_oid(ref)`:

- **Empty HEAD** (`new_head == ""`): leave `round=0`, `last_poll_sha=""`, no phase change. (Uncommon but legal: PR opened with no commits.)
- **Bootstrap** (`state.last_poll_sha == ""` AND non-empty HEAD): `round = max(round, 1)`; `last_poll_sha = new_head`; transition phase out of `idle` per the poll-from-`idle` row. NOT subject to attribution. Do **not** flip reviewers here (bootstrap is the anchor, not an observed push).
- **Unchanged SHA** (`state.last_poll_sha != ""` AND `new_head == state.last_poll_sha`): idempotent — no round bump, `last_pushed_head_sha`/reviewers untouched. Still ingest items/reviewers/CI (a reviewer may have engaged without a push) and resolve phase.
- **CLI's own push** (`new_head != last_poll_sha` AND `new_head == state.last_pushed_head_sha`): `last_poll_sha = new_head`, NO round bump, reviewers **untouched** (`_push` already flipped them).
- **External push** (`new_head != last_poll_sha` AND `new_head != state.last_pushed_head_sha`): `round += 1`; `last_poll_sha = new_head`; leave `last_pushed_head_sha` untouched; **mirror `_push`'s reviewer flip** via `flip_stale_required_reviews(state.reviewers)`.

## Phase transitions (§3.2 poll row, by current phase)

- PR observed closed-via-merge → `MERGED` (from any non-terminal phase; takes precedence).
- from `IDLE`: first push observed (non-empty HEAD via bootstrap) → `AWAITING_REVIEW`; if ALSO a reviewer item already filed → `FIXES_PENDING` (direct edge); empty HEAD → no-op (stay `IDLE`).
- from `AWAITING_REVIEW`: new reviewer item observed → `FIXES_PENDING`; external push (SHA changed) → round++, stay `AWAITING_REVIEW`; else no-op.
- from `FIXES_PENDING`: new item observed → stay (item appended); external push → round++, stay; else no-op.
- from `QUIESCED`: new item → `FIXES_PENDING`; external push → `AWAITING_REVIEW` (round++); else no-op.
- from `HUMAN_GATED`: new item → `FIXES_PENDING`; external push → `FIXES_PENDING` (round++); else no-op.
- from `MERGED`: terminal; no-op.

"New reviewer item observed" = at least one item with a `(kind, gh_id)` not previously in `state.items` was ingested this poll.

## Error-code mapping (read-only)

`gh.rest`/`gh.head_ref_oid` already raise `PrgroomError` tagged `RUNTIME_GH_TRANSIENT` (5xx/rate-limit/timeout) or `RUNTIME_GH_TERMINAL` (other 4xx, missing binary), and `gh.graphql` raises `RUNTIME_GRAPHQL_FAILED`. `_poll` lets those propagate **unchanged** — it does not re-wrap. The only adapter signal `_poll` must translate is `GhNotFoundError` (a typed non-`PrgroomError` 404): map it to `RUNTIME_GH_TERMINAL`. `_poll` issues no GraphQL in the read path; `RUNTIME_GRAPHQL_FAILED` is exercised only insofar as a future GraphQL read could surface it — 8.9a uses REST only, so the mapping is verified by letting an injected `RUNTIME_GRAPHQL_FAILED` propagate if a gh call raises it.

---

## File Structure

- **Create** `src/prgroom/lifecycle/poll.py` — `poll_pr` (the lock-assuming read internal) + private helpers for item ingestion, reviewer engagement, CI mapping, attribution, phase resolution.
- **Modify** `src/prgroom/lifecycle/__init__.py` — export `poll_pr`.
- **Modify** `src/prgroom/prsession/pr_ref.py` — add `PRRef.parse(text)` classmethod (PR ref string → `PRRef`) raising `PreconditionError(PRECONDITION_BAD_PR_REF)` on malformed input. (Needed by the CLI verb; the repo has no parser yet.)
- **Modify** `src/prgroom/cli.py` — replace the `poll` skeleton with a real verb that resolves store + gh, parses the ref, runs `read → poll_pr → write` under `with_lock`, renders errors via `handle_cli_error`.
- **Create** `tests/unit/test_lifecycle_poll.py` — attribution/bootstrap/phase/reviewer-flip + error-mapping unit tests against InMemoryStore + RecordedRunner-backed `GhCli`.
- **Create** `tests/unit/test_pr_ref_parse.py` — `PRRef.parse` happy + malformed cases.
- **Modify** `tests/unit/test_cli_poll.py` (new) — CLI-level wiring test (lock acquired, error rendered, ref parsed) via `CliRunner` with a fake gh.
- **Create** `tests/fixtures/gh/poll_*.json` — recorded gh REST responses for the read endpoints.

---

### Task 1: `PRRef.parse` — PR ref string parser

**Files:**
- Modify: `src/prgroom/prsession/pr_ref.py`
- Test: `tests/unit/test_pr_ref_parse.py`

Accepts `123`, `owner/repo#123`, and full URL `https://github.com/owner/repo/pull/123`. A bare number is only resolvable when an `owner/repo` default is supplied (CLI passes the current-repo default in a later bead; for 8.9a the bare-number form requires an explicit default, else raises). Malformed → `PreconditionError(PRECONDITION_BAD_PR_REF)`.

- [ ] **Step 1: Write the failing test** (`tests/unit/test_pr_ref_parse.py`)

```python
from __future__ import annotations

import pytest

from prgroom.errors import ErrorCode, PreconditionError
from prgroom.prsession.pr_ref import PRRef


def test_parse_owner_repo_hash_number() -> None:
    assert PRRef.parse("octo/demo#7") == PRRef(owner="octo", repo="demo", number=7)


def test_parse_full_url() -> None:
    assert PRRef.parse("https://github.com/octo/demo/pull/7") == PRRef(
        owner="octo", repo="demo", number=7
    )


def test_parse_bare_number_with_default() -> None:
    assert PRRef.parse("7", default_repo=("octo", "demo")) == PRRef(
        owner="octo", repo="demo", number=7
    )


def test_parse_bare_number_without_default_is_bad_ref() -> None:
    with pytest.raises(PreconditionError) as exc:
        PRRef.parse("7")
    assert exc.value.code is ErrorCode.PRECONDITION_BAD_PR_REF


@pytest.mark.parametrize("bad", ["", "not-a-ref", "octo/demo", "octo/demo#abc", "octo#7"])
def test_parse_malformed_raises_bad_pr_ref(bad: str) -> None:
    with pytest.raises(PreconditionError) as exc:
        PRRef.parse(bad)
    assert exc.value.code is ErrorCode.PRECONDITION_BAD_PR_REF
```

- [ ] **Step 2:** Run `cd packages/prgroom && uv run pytest tests/unit/test_pr_ref_parse.py -q` — expect FAIL (`parse` AttributeError).

- [ ] **Step 3: Implement `PRRef.parse`** — regex match the three forms; raise `PreconditionError(PRECONDITION_BAD_PR_REF, detail=text)` otherwise. (Import `PreconditionError`/`ErrorCode` lazily inside the method to avoid a cycle: `pr_ref` is imported by `errors`.)

- [ ] **Step 4:** Run the test — expect PASS.

- [ ] **Step 5:** Commit `feat(prgroom): PRRef.parse for CLI ref strings (8.9a)`.

> **Cycle note:** `errors.py` imports `PRRef` (for `lock_held_error`), so `pr_ref.py` must NOT import `errors` at module top. Do the import inside `parse`.

---

### Task 2: gh REST fixtures for the read path

**Files:**
- Create: `tests/fixtures/gh/poll_pr_open.json`, `poll_pr_merged.json`, `poll_issue_comments.json`, `poll_reviews.json`, `poll_review_comments.json`, `poll_status_success.json`, `poll_empty_list.json`

- [ ] **Step 1:** Write fixtures reproducing real `gh api` shapes:
  - `poll_pr_open.json`: `{"state": "open", "merged_at": null}`
  - `poll_pr_merged.json`: `{"state": "closed", "merged_at": "2026-06-09T10:00:00Z"}`
  - `poll_issue_comments.json`: array with one comment `{"id": 11, "user": {"login": "copilot"}, "body": "top-level note", "created_at": "2026-06-09T11:00:00Z"}`
  - `poll_reviews.json`: array with one review `{"id": 21, "user": {"login": "copilot"}, "state": "CHANGES_REQUESTED", "body": "please fix", "submitted_at": "2026-06-09T11:05:00Z"}`
  - `poll_review_comments.json`: array with one inline comment `{"id": 31, "user": {"login": "copilot"}, "body": "inline nit", "created_at": "2026-06-09T11:06:00Z", "pull_request_review_id": 21}`
  - `poll_status_success.json`: `{"state": "success"}`
  - `poll_empty_list.json`: `[]`

- [ ] **Step 2:** Commit `test(prgroom): recorded gh fixtures for poll read path (8.9a)`.

---

### Task 3: `poll_pr` — bootstrap + attribution + SHA semantics

**Files:**
- Create: `src/prgroom/lifecycle/poll.py`
- Modify: `src/prgroom/lifecycle/__init__.py`
- Test: `tests/unit/test_lifecycle_poll.py`

Signature:

```python
def poll_pr(
    state: PRGroomingState,
    *,
    ref: PRRef,
    gh: GhClient,
    deps: Deps,
    config: PrgroomConfig,
) -> PRGroomingState:
    """Caller must hold the per-ref lock (see lock()). Read-only over gh (§3.2/§3.4/§4.1)."""
```

It mutates a copy of `state` and returns it; the caller (`run` later, or the CLI verb now) owns `store.write`.

- [ ] **Step 1: Write failing tests** for the SHA/round/attribution branches (against a `GhCli(RecordedRunner([...]))` queuing head-oid + pr + 4 lists + status in the order `poll_pr` calls them). Cover:
  - bootstrap non-empty HEAD from `IDLE` no items → `round` 0→1, `last_poll_sha` set, phase `AWAITING_REVIEW`.
  - bootstrap empty HEAD → `round` stays 0, `last_poll_sha` stays "", phase stays `IDLE`.
  - unchanged SHA → no round bump, reviewers untouched, phase unchanged when no new item.
  - CLI's own push (`new_head == last_pushed_head_sha`) → `last_poll_sha` advances, NO round bump, a required `review_found` reviewer is NOT flipped.
  - external push (`new_head != last_pushed_head_sha`) → `round += 1`, required `review_found` reviewer flipped to `not_requested`.

- [ ] **Step 2:** Run the test file — expect FAIL (module missing).

- [ ] **Step 3: Implement** the SHA/round/attribution core in `poll_pr` (defer item/CI ingestion stubs to return-as-is for now; this task pins the SHA math). Use `dataclasses.replace`/in-place mutation on a `copy.deepcopy(state)` so the caller's object is untouched. Reuse `flip_stale_required_reviews` for the external-push flip. Export `poll_pr` from `lifecycle/__init__.py`.

- [ ] **Step 4:** Run — expect PASS.

- [ ] **Step 5:** Commit `feat(prgroom): _poll SHA/round/attribution core (8.9a)`.

---

### Task 4: `poll_pr` — item ingestion + reviewer engagement + CI + phase resolution

**Files:**
- Modify: `src/prgroom/lifecycle/poll.py`
- Test: `tests/unit/test_lifecycle_poll.py`

- [ ] **Step 1: Write failing tests:**
  - new reviewer item observed from `AWAITING_REVIEW` → phase `FIXES_PENDING`; item appended with correct `kind`/`identity.gh_id`/`author`/`body_excerpt` (first 200 chars)/`seen_at`.
  - duplicate poll (same gh ids already in `state.items`) appends nothing and does NOT re-trigger the new-item phase edge.
  - reviewer engagement: a `requested` required reviewer whose login authored a review → `status=in_progress`, `last_review_at` set; a submitted review keeps engagement (status not regressed).
  - `evaluate_reviewer_timeouts` invoked: a `requested` reviewer past `review_start_timeout` (frozen clock advanced via a second `FrozenClock`) → `declined`/`timeout-no-start`.
  - CI rollup `success` → `quiescence.ci_state == "success"`; combined-status absent (404 on the status endpoint mapped to `absent`) → `"absent"`.
  - PR observed merged → phase `MERGED` regardless of items.
  - `idle → fixes-pending` direct edge: bootstrap non-empty HEAD AND a reviewer item present → `FIXES_PENDING`.
  - `last_activity_at` advances to `deps.clock.now()` when any new item/engagement/CI change observed.

- [ ] **Step 2:** Run — expect FAIL.

- [ ] **Step 3: Implement** ingestion helpers: `_ingest_issue_comments`, `_ingest_reviews`, `_ingest_review_comments` (each returns new `ReviewItem`s keyed by `(kind, gh_id)`, skipping ids already present), `_observe_engagement` (flip reviewer status + `last_review_at` for items authored by a known reviewer login after `last_request_at`), `_ci_state` (map combined-status `state`; a `GhNotFoundError` on the status endpoint → `"absent"`), and `_resolve_poll_phase` (the §3.2 poll-row cascade keyed on current phase + `merged?` + `new_item?` + `external_push?`). Call `evaluate_reviewer_timeouts(state, now=..., review_start_timeout=config.review_start_timeout, review_finish_timeout=config.review_finish_timeout)`. Stamp `last_polled_at = now`; advance `last_activity_at = now` on any observed mutation.

- [ ] **Step 4:** Run — expect PASS.

- [ ] **Step 5:** Commit `feat(prgroom): _poll item/reviewer/CI ingestion + phase resolution (8.9a)`.

---

### Task 5: `poll_pr` — gh error-code mapping

**Files:**
- Modify: `tests/unit/test_lifecycle_poll.py` (add error cases)
- Possibly modify: `src/prgroom/lifecycle/poll.py` (only the 404→terminal map)

- [ ] **Step 1: Write failing tests:**
  - a transient gh failure (recorded 503 on the reviews list) propagates `RUNTIME_GH_TRANSIENT` unchanged from `poll_pr`.
  - a terminal gh failure (recorded 401 on head-oid) propagates `RUNTIME_GH_TERMINAL`.
  - a `GhNotFoundError` on the PR resource (`pulls/{n}` 404) is mapped by `poll_pr` to `RUNTIME_GH_TERMINAL` (PR vanished mid-run).
  - an injected `RUNTIME_GRAPHQL_FAILED` (a fake gh whose call raises it) propagates unchanged.

- [ ] **Step 2:** Run — expect FAIL (the 404→terminal map likely not yet wrapped on the PR-resource read).

- [ ] **Step 3: Implement** the `GhNotFoundError → PrgroomError(RUNTIME_GH_TERMINAL)` wrap around the PR-resource read only (the CI-status 404 is `absent`, not an error — keep those distinct). Let all `PrgroomError`s propagate untouched.

- [ ] **Step 4:** Run — expect PASS.

- [ ] **Step 5:** Commit `feat(prgroom): _poll maps gh 404 on PR resource to terminal (8.9a)`.

---

### Task 6: Wire the `poll` CLI verb

**Files:**
- Modify: `src/prgroom/cli.py`
- Test: `tests/unit/test_cli_poll.py` (new)

The verb: resolve store via `resolve_store` (already done in the root callback — refactor so the resolved store + a gh adapter are available to the verb), parse the ref via `PRRef.parse`, then under `with_lock(store, ref, _poll)` run `state = store.read(ref)` (bootstrap on `StateNotFoundError`), `state = poll_pr(state, ref=ref, gh=gh, deps=Deps.system(), config=PrgroomConfig.load())`, `store.write(ref, state)`. Render any `PrgroomError` via `handle_cli_error`. Poll is a **locked** verb (not the status carve-out).

- [ ] **Step 1: Write failing tests** (`CliRunner` with a seam to inject a fake gh + InMemoryStore — pass them via a module-level factory the test monkeypatches, or a typer context object). Cover: a malformed ref exits 2 with the rendered `PRECONDITION_BAD_PR_REF` block; a successful poll exits 0 and writes state; a transient gh error exits 75; the verb acquires the lock (a pre-held lock → exit 75 `PRECONDITION_LOCK_HELD`).

- [ ] **Step 2:** Run — expect FAIL.

- [ ] **Step 3: Implement** the verb + a small wiring seam (`_build_gh()` returning `GhCli(SubprocessRunner())` by default, monkeypatchable in tests; store resolution reused from the root callback). Replace `_skeleton("poll")`.

- [ ] **Step 4:** Run — expect PASS.

- [ ] **Step 5:** Commit `feat(prgroom): wire poll CLI verb through the lock wrapper (8.9a)`.

---

### Task 7: Full gate

- [ ] `make ci-prgroom` green from the worktree root; coverage at 100% (suite floor is 90% but the suite sits at 100% — keep it).
- [ ] `quality-reviewer` → address; `simplify` → address; `verify-checklist` with evidence.
- [ ] Confirm no `graphify-out/` staged; commit on the branch only (no PR/merge/push-to-main).

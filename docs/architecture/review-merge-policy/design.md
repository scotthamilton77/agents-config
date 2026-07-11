# Review / Merge Policy — design

Evergreen contract for the two-axis PR review/merge policy: what reviews a
repo expects (Axis 1), who is authorized to merge (Axis 2), and the
no-blocker eligibility floor that sits between them. See
[index.md](index.md) for orientation and consumers.

## Core model

A PR's fate is governed by two independent axes:

- **Axis 1 — Review expectation**: what reviews do we expect, and how long do
  we wait for them? This, and only this, drives the poll / comment-resolution
  cycle.
- **Axis 2 — Merge authorization**: once a PR is *eligible*, who is allowed to
  press merge?

Between them sits one derived concept:

- **Eligibility** — is the PR free of *blocking* conditions (unresolved
  threads, red CI, stale head)? A no-blocker safety floor for **every** merge
  path. Eligibility deliberately does **not** assert that any review positively
  happened — that positive requirement belongs to the merge-rule (Axis 2).
  This split is load-bearing: it lets an explicit human merge proceed on a repo
  whose expected bot never showed (no blocker present), while still preventing
  *autonomous* merge there (the bot-quiescence rule's positive requirement is
  unmet). Eligibility is **not** authorization.

**A merge happens iff the PR is `eligible` AND the action is `authorized`.**
Axis 1 and the eligibility predicate decide the former; Axis 2 decides the
latter. Keeping them separate is what removes the overloading of the old
`[review-requirements]` keys. This invariant is absolute for every automatic
and instructed path. The **only** exception is an explicit, separately-named
human **force-merge** override (see Consumers below) — a deliberate, logged
action that bypasses the eligibility gate; it is never the default behavior
of any Axis-2 value.

## Axis 1 — Review expectation

Drives polling. The cycle is ON **iff** `bot-review-expected` **or**
`human-approvers-required > 0`. If nothing is expected, there is no polling.

| Setting | Meaning |
|---|---|
| `bot-review-expected` (bool) | Expect a bot reviewer. Poll until the bot quiesces (reviewed, then inactive for the timeout). |
| `bot-reviewers` (list) | The **trusted** bot identities whose review satisfies the bot-review fact — matched by **exact** login / app identity, not substring. Defaults to Copilot's identity. A review from a bot not on this list does not count. This is the trust boundary for `bot-quiescence` autonomous merge; a substring match (as the legacy script does with `test("copilot"; "i")`) is insufficient. |
| `bot-inactivity-timeout` | Bot silence that counts as "bot is done" (reuses prgroom's review-finish-timeout concept). |
| `human-approvers-required` (int) | How many human approvals to wait for. |
| `human-review-timeout` | How long to wait for slow humans before giving up. Empty = wait indefinitely (interactive); autonomous runs park the molecule rather than block on it — pending a future pipelining capability that would let other work advance in the meantime. |

A timeout means "stop waiting," not "treat the review as satisfied." A bot
that never reviewed, or humans who never approved, do **not** become
satisfied by their timeout elapsing — the wait simply ends and the PR is
handed off / parked. Absence never authorizes a merge.

## Axis 2 — Merge authorization

Once eligible, who may merge?

| Value | Meaning |
|---|---|
| `never` | The agent never merges — not even on an in-session instruction. A human merges in the GitHub UI (max control / audit-trail repos). |
| `explicit` *(default)* | The agent merges only on an explicit in-session human instruction ("merge it" / "ship it"). This is today's global merge-authorization law, unchanged. |
| `rule-based` | The agent merges autonomously when the selected **merge-rule** holds. Requires a `merge-rule` value. |

### Merge-rule vocabulary (used only when `merge-authorization = rule-based`)

Every rule applies **on top of** the eligibility floor (no blockers — see
Eligibility predicate). The eligibility floor asserts *nothing bad*; the rule
asserts the *positive* thing that authorizes an autonomous merge. Each
positive fact is bound to the current head (see Freshness invariant):

| Rule | Authorizes merge when… (all also require eligibility) |
|---|---|
| `bot-quiescence` | A **trusted** bot (`bot-reviewers`, exact identity) **actually completed a clean review at the current head** (`commit_id == headRefOid`; fail closed if `commit_id` absent). A bot that timed out, never showed, or reviewed a stale head does **not** satisfy this — the "real review" floor is structural to the rule. |
| `human-approvals` | **≥ `human-approvers-required` distinct current non-bot approvers** at the current head — reduce to one entry per non-bot login (latest review by submission order wins), count logins whose latest state is `APPROVED` with `commit_id == headRefOid`. `human-approvers-required` must be ≥ 1 for this rule (a zero-approval rule is vacuously true; the resolver rejects it). |
| `agent-ruling` | An independent, cross-model AI judge (`merge-guard/judge_merge.py`) renders a merge go/no-go verdict over `base..head`, gated by trusted out-of-band provenance and a structural protected-path scan. Merge authorizes **iff** `verdict == "go"`; every other outcome fails closed. Non-vacuity is a **gate** invariant (a real review always runs), not a resolver check. |

`merge-rule` takes a single value for now. It is shaped as a scalar the config
parser treats as one selection, so a future rule engine (boolean combinations
/ expressions — TBD) can extend the field without a breaking rename.

### AI reviewer vs. AI merge-judge — do not conflate

Two distinct roles an AI can play, deliberately on different axes:

- **AI reviewer** — a bot that leaves *comments to address*. This is an Axis-1
  reviewer; `bot-review-expected` already generalizes beyond Copilot to any
  bot review (including a codex/RALF review bot).
- **AI merge-judge** — `agent-ruling`, an agent that renders a *merge
  verdict*. This is an Axis-2 authorization source, invoked at the merge gate.

Same technology family, different jobs. The cross-model principle (the judge
should not be the same model that wrote the code) lives with `agent-ruling`.

### Safety property: no zero-review auto-merge is possible

The zero-review auto-merge failure mode — a repo auto-merging with no review at
all — is **structurally impossible**, not merely discouraged. Autonomous merge
requires `merge-authorization = rule-based` *and* a `merge-rule`, and every
implemented rule requires a *real* review to have occurred. For
`human-approvals` and `bot-quiescence`, the resolver's validation enforces this
so a rule cannot be vacuously satisfied: `human-approvals` is rejected unless
`human_approvers_required >= 1` (a zero-approval rule would be trivially true);
`bot-quiescence` is rejected unless a trusted `bot-reviewers` identity is
configured and `bot-review-expected` is true, and it counts only an *actual*
clean review from that identity (a no-show/timeout never satisfies it). For
`agent-ruling`, non-vacuity is enforced at the **gate**, not the resolver: the
harness (`merge-guard/judge_merge.py`) always performs a real, cross-model,
provenance-verified review bound to the current head and base, and merge
authorizes **iff** the verdict is an affirmative `go` — `no-go`, `abstain`, and
every error path fail closed. The resolver validates only the judge's *config*
(backend, model family, effort, attempt budget); it is the gate, together with
provenance and the protected-path scan, that enforces a real independent
review happened against the exact code that will land. A repo that expects no
reviewers therefore has **no satisfiable rule** and cannot auto-merge — it
falls through to handoff. No rule authorizes on nothing. The zero-review merge
path is closed by construction.

## Eligibility predicate

Eligibility is the **no-blocker safety floor**: the AND of the "nothing bad"
facts below, each independently sourced and evaluated **live at merge time**.
It asserts no unresolved feedback, no red CI, no stale head — **not** that any
review positively occurred (that is the merge-rule's job, Axis 2). This floor
applies to every merge path; the positive review facts (a bot reviewed clean,
N humans approved) live in the rules that need them.

prgroom's rolled-up `auto_merge_eligible` boolean
(`docs/architecture/prgroom/design.md` §4.5) is **never** consumed wholesale —
two of its four components are unsuitable here: `phase_is_quiesced` embeds the
reviewer-quiescence wait, which is currently unseeded — prgroom never
populates `state.reviewers`, so the gate evaluates vacuously true — and
`human_review_satisfied` is a *positive* authorization
fact (binary, no notion of `N > 1`) that belongs to the human-approvals rule,
not to a blocker floor.

| Blocker fact (all must be clear) | Source |
|---|---|
| No expected review still in flight | **Always** a live, timestamp-based check, independent of any session's polling state, mirroring Axis 1's own wait definition: if `bot-review-expected`, block unless a qualifying bot review has arrived at the current head **or** `bot-inactivity-timeout` has elapsed since the bot was requested/last active; if `human-approvers-required > 0`, block unless enough distinct current approvals have arrived **or** `human-review-timeout` has elapsed (unset timeout = block indefinitely — an interactive wait is exactly as long as the human takes). Vacuously clear when Axis 1 has nothing expected. Without this row, a review that simply hasn't happened *yet* is indistinguishable, to every other row below, from one that concluded with nothing to report — both read as "no blocker" purely because nothing has been reported, not because the window has closed. Same "don't race ahead of a pending signal" principle as CI-green's `Pending` treatment, applied to the review wait itself. |
| No active requested-changes verdict | **Always** a live GitHub query, evaluated across **all** of a reviewer's reviews regardless of commit. For each reviewer (bot or human), a `CHANGES_REQUESTED` review is active and blocks **all** non-force merge paths until it is **dismissed** or **superseded by an `APPROVED` review from that same reviewer** — a later `COMMENTED` review does **not** clear it (GitHub does not treat a comment-only review as changing a reviewer's decision, so "most recent review wins" is the wrong reduction here). Deliberately **not** head-scoped: GitHub does not clear a requested-changes verdict on a new push either — only dismissal or a superseding approval does — so binding this to the current head (as the Freshness invariant does for *positive* facts) would let a stale negative verdict silently drop off the floor the moment the author pushes again. This is independent of thread resolution — a requested-changes verdict blocks even if no inline threads remain. |
| No unresolved review threads (bot or human) | **Always** a live GitHub query at merge time. prgroom state is **never** a substitute — a thread opened after prgroom last quiesced is absent from state yet unresolved on GitHub. |
| No untriaged non-thread reviewer feedback (`review_summary` / `issue_comment`, bot or human, excluding the delivery agent's own recorded replies) | **Always** a live query at merge time: fetch every `review_summary` and `issue_comment` item currently visible on the PR (the same reviewer-item fetch `wait-for-pr-comments` Phase 3 performs), excluding items whose exact comment ID was **durably recorded, at post time, as one of the agent's own replies** — never excluded by author login. The delivery agent frequently posts through the same GitHub account as its human operator (no dedicated bot identity is assumed), so filtering by login would also hide a genuine manual comment from that same human; only a specifically recorded reply ID is safe to exclude. A reply is not incoming feedback, and without this exclusion the agent's own reply would immediately re-trip the check it just cleared. Require each remaining item to already carry a terminal, non-blocking disposition (fixed / already-addressed / skipped / deferred / won't-fix) from a **durably recorded** completed triage pass, matched by the item's own stable identity and unioned across the PR's full push history, not looked up by current head (see Consumers for how `wait-for-pr-comments`' retained inventories support this) — the retained-inventory union is the only implemented durable source today. (A per-item prgroom disposition as an alternative clearance source is design-reserved and not yet implemented — `check-merge-eligibility.sh` never queries prgroom for individual item state, only its two aggregate rollup booleans, see the next two rows.) Deliberately **not** head-scoped, for the same reason as the requested-changes row above: an `issue_comment` carries no commit reference at all, and a `review_summary`'s feedback does not become moot just because the author pushed again — only an actual triage decision clears it (an `already_addressed` disposition already covers the case where a later commit happens to resolve it). An item absent from every durable record, never triaged, or recorded `escalated`/`failed` is a blocker; an empty current set is vacuously clear. Threads and non-thread items are disjoint GitHub objects, so the thread check above does not cover this, and it must never be delegated to prgroom's `no_blocker_items` alone (next row) — an item prgroom has not yet polled carries no disposition and does not trip that field. |
| No internal blocker items | prgroom's `no_blocker_items` when prgroom state exists (no item disposition `ESCALATED`/`FAILED`) — an **additional** internal-blocker source, never a replacement for the live thread or non-thread-feedback checks above. It proves only that nothing was actively escalated or failed; an item prgroom has not yet polled carries `disposition = None` and passes this check silently, so it can never stand in for the live non-thread-feedback check. n/a without prgroom. |
| No terminal lifecycle error | prgroom's `last_error_clear` when prgroom state exists; else n/a. |
| Required CI checks green | **Always** a direct check — not part of prgroom's contract. New gate added to `check-merge-eligibility.sh`. |
| Head unchanged since evaluation | Enforced via `--match-head-commit` at the merge call (see Freshness invariant). |

Only the two internal facts are prgroom-sourced (and only when available); the
rest are verified live/directly, so the design does not depend on that
reviewer-state seeding gap being closed.

## Freshness invariant

Neither `check-merge-eligibility.sh` nor `poll-copilot-review.sh` tracks head
SHA — this is surface this policy introduces.

1. **Review identity** (bot-review, approver count): fetch the PR's current
   `headRefOid`. A bot review or human approval counts **only** if its
   `commit_id` equals that head. There is **no timestamp fallback** — a review
   pending on an old diff can be *submitted* after a push while carrying a
   *stale* `commit_id`, so `submitted_at` cannot distinguish it. If a review's
   `commit_id` is unavailable, **fail closed** (it does not count). This
   head-binding governs **positive** facts only (a review counting *for*
   authorization). Negative/outstanding facts — an active `CHANGES_REQUESTED`
   verdict, an untriaged `review_summary` or `issue_comment` — are evaluated
   regardless of commit; see the eligibility floor rows for why staleness
   cuts the opposite way for those.
2. **Recompute live**: `merge-guard` evaluates the full predicate
   synchronously immediately before merging — never from a cached earlier
   read — so new unresolved threads / blockers that appear after an earlier
   "looks clean" read are caught.
3. **Bind the merge to the checked head**: the merge is issued as
   `gh pr merge --squash --match-head-commit <headRefOid>` (the SHA the
   predicate was evaluated against) — `merge-guard` always squash-merges.
   GitHub rejects the merge if the head changed in the final window;
   `merge-guard` re-evaluates from scratch on rejection rather than retrying
   blind.

## Machine-checkable predicates

The two authorization-boundary predicates are defined exactly so implementers
cannot pick unsafe defaults.

**CI-green** (eligibility floor):

- *Required set* = the branch-protection required status checks for the
  target branch, fetched independently from branch protection. Each entry
  carries a context **name** and, where branch protection pins one, an
  expected **source** (the specific GitHub App the check must come from) —
  GitHub's own trust boundary against a different integration posting a
  same-named status. **Never derived from** `statusCheckRollup` — the rollup
  lists only contexts that have actually reported, so filtering *it* down to
  "the required ones" silently omits any required context that has not
  started yet, which is exactly the race this gate exists to prevent. If
  branch protection defines **no** required checks, the required set is
  empty.
- *Green* iff every required entry has a matching `statusCheckRollup` entry
  that concluded `SUCCESS`, matched by context name **and**, when that entry
  pins a source, by the same source — a same-named `SUCCESS` from a
  different integration does **not** satisfy a source-pinned requirement.
  Name alone is not a trust boundary here any more than a bot login substring
  is one for `bot-reviewers` (see Axis 1); an entry with no source pin
  matches any source, by design. `SKIPPED` and `NEUTRAL` count as passing
  (GitHub itself permits merge). `FAILURE` / `ERROR` / `CANCELLED` /
  `TIMED_OUT` / `ACTION_REQUIRED` → not green (blocker).
- *Pending* — a required entry with **no matching (name-and-source) entry in
  the rollup at all**, or with a matching entry that has no concluded status
  yet (`QUEUED` / `IN_PROGRESS` / `PENDING`) → **not green**. A required check
  that has never started is the highest-risk case (its triggering workflow
  may not even be configured for this event) and must fail closed exactly
  like one still running — this is what prevents an autonomous merge from
  racing ahead of checks that haven't reported for the current head.
- *Empty required set (no CI configured)* → vacuously green. Safety for the
  autonomous path then rests entirely on the merge-rule's positive review
  (bot/human/agent), which is always required regardless — so "no CI" never
  *by itself* enables an unreviewed merge. Same treatment for `explicit` and
  `rule-based`; the difference is only that `explicit` also needs the human
  instruction.

**bot clean-review** (the `bot-quiescence` positive fact):

- Consider reviews from a trusted `bot-reviewers` identity **at the current
  head** (`commit_id == headRefOid`), excluding `DISMISSED` reviews.
- Take that identity's latest such review by `submitted_at`.
- *Clean* iff the latest state is `APPROVED` or `COMMENTED`. Review state
  alone certifies only that the bot reviewed and did not request changes — it
  never certifies that the review's content was triaged. Whether the review's
  summary body or any inline comments still carry outstanding feedback is a
  PR-wide fact the eligibility floor's untriaged-feedback blockers already own
  (see Eligibility predicate) and that every merge path, including this rule,
  sits on top of; this predicate does not duplicate that check. An `APPROVED`
  review is therefore no more automatically clean than a `COMMENTED` one — a
  bot can attach substantive summary feedback to either state.
  - `CHANGES_REQUESTED` → not clean (and independently a floor blocker for
    every path, regardless of this rule).
- No qualifying current-head review from a trusted identity → not satisfied.
- This predicate relies on the eligibility floor's triage-completeness facts;
  it does not add a parallel comment-classification mechanism.

**bot-quiescence retry and escape hatch** (behavior once the positive fact
above is not yet satisfied — never a blocker itself, and distinct from the
eligibility-bypass override in Consumers):

- A bot that has not yet produced a qualifying clean review at the current
  head gets **at most one** re-review ask per head: merge-guard calls
  `request-rereview.sh` plus the re-review poll helpers directly, never by
  re-invoking the full `wait-for-pr-comments` skill — that skill skips its own
  re-request phase when there is no untriaged feedback to process, so it
  would silently no-op on exactly this residual. merge-guard then re-evaluates
  the predicate above against the unchanged head; a clean re-review now
  satisfies the rule and merges.
- Two facts govern the ask: `polling.rereview_round_count`, a persisted count
  of *silent* re-review asks on the current head only (rounds where the bot
  actually responded are not counted), and `facts.bot_review_cap_exhausted`, a
  boolean that gates every decision below. `bot_review_cap_exhausted` is set
  true by either of two independent triggers — a chatty bot that keeps
  re-reviewing past its existing `round >= 6` cap, or a silent bot that
  reaches the one-ask `rereview_round_count` cap — with no unified count
  across the two.
- `check-merge-eligibility.sh` reads `bot_review_cap_exhausted` from the
  single inventory file whose name embeds the PR's *current* head SHA, never
  by globbing across a PR's retained inventories. A stale `exhausted = true`
  recorded against a superseded head can therefore never leak onto a fresh
  one — a genuinely new fix commit gets a fresh inventory and the count
  restarts at zero. Absent, unreadable, or field-missing inventory data all
  resolve to `false`: this fact is fail-closed in every failure mode.
- Once the ask is spent and the bot has stayed silent, an opt-in
  `allow-force-after-bot-timeout` key (default `false`, valid only when
  `merge-rule = bot-quiescence`) unlocks a scoped force-merge. It is reachable
  only when eligibility is clean, the rule is still unmet, the ask is spent,
  the config key is set, and a fresh in-session human instruction names the
  bot-quiescence blocker — all five simultaneously, never a standing grant.
  Because eligibility already holds when this fires, it bypasses only the
  unmet rule, not the eligibility floor; it is not a second instance of the
  eligibility-bypass override described in Consumers.
- This scoped force-merge performs its own terminal merge and never enters
  the `--admin` bypass ladder described in Consumers: that ladder remains
  reserved for merges authorized through the rule and explicit-instruction
  paths above, not for a merge reached via this bypass. A GitHub rejection of
  the scoped force-merge ends in hand-off, never an escalation to a bypass
  the human did not authorize for it.

**admin-bypass availability** (never a blocker — informs *how* Step 5 issues
an already-authorized merge, not *whether* one is eligible):

- A repo's own GitHub branch protection is enforced through a **ruleset**
  (`GET /repos/{owner}/{repo}/rules/branches/{branch}`), independent of this
  policy's Axis 1 `human-approvers-required`. When that endpoint returns a
  `pull_request` rule with `required_approving_review_count > 0` for the
  target branch, GitHub itself will refuse a plain merge unless a qualifying
  approval exists — and neither a bot review (Copilot's state is never
  `APPROVED`) nor the PR author's own approval (self-approval is not
  possible) can satisfy it. This rule is **left in place** — it is exactly
  what protects the branch from every contributor who is not the repo owner
  (or an equivalently trusted identity) acting through this agent.
- Each matching rule carries a `ruleset_id`. `GET
  /repos/{owner}/{repo}/rulesets/{ruleset_id}` returns
  `current_user_can_bypass` (`always` | `pull_requests_only` | `none`) —
  GitHub's own, pre-computed answer to "can the identity that authenticated
  this `gh` call bypass this specific ruleset," never re-derived from
  `bypass_actors` locally (role-to-actor-id mapping is GitHub's to resolve,
  not this script's).
- *Bypassable* iff **every** `pull_request` rule covering the branch resolves
  `current_user_can_bypass` to `always` or `pull_requests_only` — one
  non-bypassable ruleset among several fails the whole predicate closed.
  Either value is sufficient for a PR merge (a "pull request only" bypass
  grant already covers merging a PR); `always` additionally covers direct
  pushes, irrelevant here.
- *Not applicable* (`review_rule_active = false`) when no `pull_request` rule
  with a positive required-approving-review count targets the branch — the
  fact carries no opinion, since there is nothing for `--admin` to bypass.
- A fetch failure on this fact never aborts eligibility. Because
  `admin_bypass` gates no entry in `blockers[]`, denying a merge that may not
  even need `--admin` over a transient GitHub/API error would be wrong. The
  branch-rules list fetch (a non-404 failure) degrades to the inert "no
  rulesets" state (`review_rule_active = false`); an individual ruleset detail
  fetch failure degrades to non-bypassable (`current_actor_can_bypass = false`,
  the fail-closed default for the `--admin` decision) and continues. Both warn
  on stderr; neither silently assumes "bypassable."
- This predicate certifies only that the `pull_request` rule(s) are
  bypassable — `current_user_can_bypass` is reported **per ruleset**, and a
  ruleset commonly bundles unrelated rule types (this repo's own ruleset also
  carries `deletion`, `non_fast_forward`, `required_linear_history`,
  `copilot_code_review` alongside `pull_request`, all sharing one bypass
  grant). `gh pr merge --admin` is a **blanket** bypass of every rule in that
  ruleset the identity is entitled to bypass, not a scalpel on the review
  rule alone — see Consumers for why that scope must be named explicitly
  before it is exercised.
- This predicate never authorizes anything by itself. It only tells
  merge-guard whether a GitHub-side rejection *of an already-authorized
  merge* may be resolved with `--admin` — see Consumers.

## Resolver contract

```
resolve_policy(
    project_config: ProjectReviewMergeConfig,   # parsed [review-expectations] + [merge-policy]
    bead_labels: list[str],                      # per-bead overrides
) -> ReviewMergePolicy

ReviewMergePolicy = {
    # Axis 1
    bot_review_expected: bool,
    bot_reviewers: list[str],          # trusted bot identities (exact match)
    bot_inactivity_timeout_seconds: int,
    human_approvers_required: int,
    human_review_timeout_seconds: int | None,
    # Axis 2
    merge_authorization: "never" | "explicit" | "rule-based",
    merge_rule: "bot-quiescence" | "human-approvals" | "agent-ruling" | None,  # required iff rule-based
    # Axis 2 — agent-ruling judge config (inert unless merge_rule = agent-ruling)
    judge_backend: str,                # "codex" (only implemented backend)
    judge_model: str,                  # e.g. "gpt-5.6-terra"; family must be derivable
    judge_effort: str,                 # none|minimal|low|medium|high|xhigh
    judge_timeout_seconds: int,
    judge_max_attempts: int,           # >= 1
    # Optional App-attested approver (mechanism, not authorization; None = absent)
    approver: {type: "github-app", app_id: int, key_path_env: str} | None,
}
```

- Outside-world inputs (config, labels) are arguments — no module globals.
- Output is a typed value, not an untyped dict, at the boundary.
- Process exit codes (the CLI wrapper around `resolve_policy`): `0` —
  resolved, policy JSON on stdout; `1` — invalid config/labels (a raised
  policy error; message on stderr, never a silent fallback); `2` —
  unexpected/environment error (missing/old Python, unreadable config path,
  or any other non-policy failure; a concise one-line message, never a raw
  traceback).
- Value-domain validation (every field checked before use, all modes):
  - `human_approvers_required` must be an integer `>= 0`. A negative value is
    rejected outright — it is meaningless and, unchecked, could disable human
    waiting or vacuously satisfy a count comparison. Override labels that don't
    parse to a non-negative integer (`review-exit-human-approvers-<n>`) are
    likewise rejected.
  - `merge_authorization` must be one of the three enum values;
    `merge_rule` (when present) one of the vocabulary values.
- Invalid combinations fail loud (resolver error, never a silent fallback to
  merging or to a different rule):
  - `rule-based` without a `merge-rule`, or `merge-rule` set while not
    `rule-based`.
  - `merge-rule = human-approvals` with `human_approvers_required < 1` — a
    zero-approval rule is vacuously true and would authorize an unreviewed
    merge. The rule requires at least one required approver.
  - `merge-rule = bot-quiescence` with no trusted bot in `bot-reviewers` (no
    identity could satisfy the rule) or with `bot-review-expected = false`.
  - `merge-rule = agent-ruling` with `judge-backend` not in the implemented
    set (`codex` only), a `judge-model` whose family cannot be derived, an
    invalid `judge-effort` enum value, or `judge-max-attempts < 1`.
  - Any `judge-*` key present while `merge-rule` is not `agent-ruling`.
  - `[merge-policy.approver]` present with an unknown `type` (only
    `"github-app"` is implemented), a missing or non-integer `app-id`, an
    empty `key-path-env`, or any unrecognized key.

### Resolution precedence

`per-bead label` > project config > built-in default.

Per-bead override labels (consumed here; *authored* at brainstorm time by the
brainstorm-bead workflow's policy-knob step):

- `review-exit-copilot-only` → `bot_review_expected = true` **regardless** of
  project config (its purpose is to wait for the bot; it must not degrade to
  no-review), and `human_approvers_required = 0`.
- `review-exit-human-approvers-<n>` → `human_approvers_required = n`.
  Mutually exclusive with `review-exit-copilot-only`; both present → resolver
  error.

Built-in defaults (section/key absent):

- `bot-review-expected = true` (most repos run Copilot). With the no-blocker
  eligibility floor, this default never *deadlocks* a bot-less repo: the
  "no expected review still in flight" blocker clears once
  `bot-inactivity-timeout` elapses (an absent bot never reviews, so the wait
  always resolves by timing out), and only then can an `explicit` merge
  proceed on instruction — a *bounded wait*, not immediate eligibility. A
  bot-less repo sets this `false` to skip that wait entirely rather than let
  it elapse. (Auto-detecting bot presence per-PR is a possible future
  refinement.)
- `bot-reviewers = ["Copilot", "copilot-pull-request-reviewer[bot]"]` — two
  exact literals covering the two identities GitHub surfaces Copilot's
  reviewer as, depending on the API; still no substring matching.
- `bot-inactivity-timeout = "20m"`.
- `human-approvers-required = 0`.
- `human-review-timeout` unset (wait indefinitely).
- `merge-authorization = "explicit"` — the safe, backward-compatible default:
  identical to today's "merge only on explicit instruction" law.

## Config schema

`[review-expectations]` (Axis 1):

| Key | Type | Default |
|---|---|---|
| `bot-review-expected` | bool | `true` |
| `bot-reviewers` | list[str] | `["Copilot", "copilot-pull-request-reviewer[bot]"]` |
| `bot-inactivity-timeout` | duration string (`"20m"`) \| int (seconds) | `"20m"` |
| `human-approvers-required` | int | `0` |
| `human-review-timeout` | duration string (`"20m"`) \| int (seconds) \| unset | unset (wait indefinitely) |

`[merge-policy]` (Axis 2):

| Key | Type | Default |
|---|---|---|
| `merge-authorization` | `"never"` \| `"explicit"` \| `"rule-based"` | `"explicit"` |
| `merge-rule` | `"bot-quiescence"` \| `"human-approvals"` \| `"agent-ruling"` \| unset | unset (required iff `merge-authorization = "rule-based"`) |
| `judge-backend` | `"codex"` | `"codex"` |
| `judge-model` | str | `"gpt-5.6-terra"` |
| `judge-effort` | `"none"` \| `"minimal"` \| `"low"` \| `"medium"` \| `"high"` \| `"xhigh"` | `"high"` |
| `judge-timeout` | duration string | `"15m"` |
| `judge-max-attempts` | int | `2` |

`[merge-policy.approver]` (optional sub-table — presence enables the
approve-then-merge path in merge-guard Step 5; absence preserves prior
behavior exactly):

| Key | Type | Default |
|---|---|---|
| `type` | `"github-app"` | — (required) |
| `app-id` | int | — (required) |
| `key-path-env` | str (env var naming the PEM path) | `"MERGE_GUARD_APPROVER_KEY_PATH"` |

The approver is orthogonal to `merge-authorization`: it is mechanism for
satisfying GitHub's required-review rule on an **already-authorized** merge
(rule-based rule held, or explicit human instruction), never an
authorization source. Key material never appears in config — only the name
of the environment variable that points to it.
Spec: `docs/specs/2026-07-11-merge-approver-app-design.md`.

An unrecognized key in either section is a resolver error (exit 1) — the
resolver never silently ignores a typo'd or stale key.

Per-bead override labels (consumed by the resolver; independent of the TOML
keys above):

- `review-exit-copilot-only`
- `review-exit-human-approvers-<n>`

## Consumers

**merge-guard** — the enforcement point. Computes the eligibility predicate
live, then applies Axis 2: `never` refuses every merge attempt including an
in-session instruction; `explicit` merges iff eligible **and** the human gave
an in-session instruction, failing closed on ineligibility even when
instructed; `rule-based` merges iff eligible **and** the selected `merge-rule`
holds. The one eligibility-bypass path is an explicit, separately-named human
**force-merge** override, valid only in `explicit` mode, on a fresh
in-session instruction naming the ineligibility being overridden — logged,
and never available to `never`, `rule-based`, or any autonomous path. Every
merge is issued with `--match-head-commit`.

A GitHub repository ruleset requiring an approving review (the mechanism that
protects a public repo's `main` from every contributor) is a **separate**
gate this policy does not own and does not weaken — it stays configured
exactly as the repo owner set it. Neither a bot review nor the PR author's
own approval can satisfy it, so an already-authorized merge (eligible **and**
Axis 2 satisfied) can still be refused by GitHub itself. When that happens,
merge-guard consults `facts.admin_bypass`: if the authenticated identity
already holds a standing GitHub bypass grant on that rule
(`current_user_can_bypass` of `always` or `pull_requests_only`), it may
retry once with `--admin`, announcing that it did so and why; otherwise it
fails closed and hands off. This is **not** a third eligibility-bypass path
alongside force-merge — it never overrides anything this policy's own
eligibility floor asserts, and it only ever fires after Axis 2 has already
authorized the merge on its own terms. It exists because GitHub's merge
endpoint requires a bypass to be exercised explicitly per merge even for an
identity permanently entitled to it; `--admin` is that explicit exercise, not
a new privilege the agent invents.

`--admin` is **not** a scalpel on the review rule alone — it is GitHub's
blanket bypass of every rule in the covering ruleset the identity is entitled
to bypass, since `current_user_can_bypass` is computed per ruleset, not per
rule. `facts.admin_bypass` only certifies the `pull_request` rule(s) are
bypassable; it says nothing about any other rule type sharing that ruleset
(or a different one) that GitHub's rejection message did not name. This is
why merge-guard must read and quote GitHub's actual rejection text and
confirm it names the approving-review requirement specifically before
retrying — an inferred reason is not enough grounds to invoke a blanket
bypass.

**wait-for-pr-comments** — calls the resolver at entry and runs the
poll/resolve cycle per Axis 1; skips polling when nothing is expected; on
timeout emits a terminal "awaiting human review" / "parked" status rather than
blocking. Retains its completed per-head inventory instead of deleting it on
success, since the eligibility floor's non-thread-feedback check needs a
durable record — possibly consulted in a later session — that a given
`review_summary` / `issue_comment` was already triaged. The eligibility check
globs every retained inventory for the PR (`<owner>-<repo>-<n>-*.json`) and
unions their `complete`-state items by stable identity; `review_summary` items
gain a `review_id` field for this purpose (`issue_comment` already has
`issue_comment_id`). Ordinary >30-day pruning remains sufficient hygiene once
a PR is merged or closed.

**reply-and-resolve-pr-threads** — records the exact comment ID `gh pr
comment` returns for every reply it posts into the same retained inventory,
never the posting account's login. No dedicated bot identity is assumed: the
agent commonly posts through its human operator's own GitHub account, so a
login-based filter would also hide that same human's genuine manual comments.
Only a specifically recorded ID is safe for the eligibility check to exclude.

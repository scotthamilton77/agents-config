# Spec: merge-guard bot-quiescence retry + scoped force-merge

- **Date:** 2026-07-03
- **Status:** draft
- **Bead:** agents-config-9njsd (P0, feature)
- **Related (not blocking):** agents-config-xvmf8 (agent-ruling merge-judge) —
  touches the same `merge-guard/SKILL.md` Step 4 rule table and
  `resolve_policy.py` `MERGE_POLICY_KEYS`/`validate()` via a different rule
  (`agent-ruling`). Coordinate merge order / rebase; not a dependency.

## Problem

A `rule-based` repo running `merge-rule = bot-quiescence` has no recovery path
when the trusted bot reviewer (e.g. Copilot) never re-reviews a fix head. The
`bot-quiescence` rule holds only when `facts.bot_clean_review_at_head == true`;
a bot that goes silent leaves that fact false forever, and the merge-guard
`rule-based` branch simply reports blocked and stops. Force-merge is
deliberately unavailable in `rule-based` mode, so there is no escape hatch —
the human must `--admin` merge outside the agent's authority.

Surfaced on PR #213: a fix-commit push closed a bot review comment via a
hand-rolled GraphQL reply that bypassed `wait-for-pr-comments` Phase 6
entirely, so the trusted bot was **never asked** to re-review the fix head.
The rule stayed unsatisfiable and a human had to `--admin` merge manually.

## Rejected alternative (do not build)

**Treating bot timeout / silence as implicit approval.** This converts
bot-quiescence from a *positive attestation* ("a trusted reviewer looked and
found nothing") into "looked and found nothing, **or** never looked" — a
fail-open branch in a system whose invariant everywhere else is fail-closed,
and it makes the bot *declining to review* the exact condition that grants a
free merge. The rule stays fail-closed: a bot that never reviewed is never
treated as approval. Every merge below is either a genuine clean re-review
(rule satisfied) or an explicit human-authorized *bypass* (rule still unmet,
human on record) — never silence promoted to attestation.

## Design overview

Three coordinated parts.

1. **Close the process hole** (root cause of #213): a fix-commit push on a
   bot-quiescence repo MUST route the re-review request through Phase 6 /
   `request-rereview.sh`, never a bare reply+resolve. A bare reply leaves the
   head unreviewed and silently defeats the retry loop. Enforced as prose + a
   Red Flag.

2. **Bounded auto-retry backstop** (unchanged rule semantics): when merge-guard
   is reached with the head unreviewed and the one proper re-review ask has not
   yet been spent (`facts.bot_review_cap_exhausted == false`), merge-guard
   issues that ask **once** by calling the Phase-6 re-request primitive
   directly — `request-rereview.sh` plus the re-review poll helpers — then
   re-runs the eligibility check against the unchanged head. A clean re-review
   satisfies the rule and merges. It calls the primitive directly rather than
   invoking the full `wait-for-pr-comments` skill because that skill **skips its
   re-request phase when there is no feedback to process**
   (`wait-for-pr-comments/SKILL.md:177-178`: a bot poll timeout with no comments
   jumps straight to Phase 7) — the exact #213 residual (floor-clean, threads
   already resolved, bot silent). Because the backstop only fires when the floor
   is clean, there is by definition no untriaged feedback to process, so the
   direct ask is all it needs — and it mechanically fires regardless of feedback
   state.

3. **Scoped force-merge** (opt-in, reachable only after the ask is exhausted): a
   new default-false `[merge-policy]` key unlocks a force-merge sub-branch that
   requires a fresh, named human instruction — identical gating to
   explicit-mode force-merge, restricted to the bot-quiescence blocker, and
   explicitly **not** chained into Step 5's `--admin` blanket bypass.

### The exhaustion model — one boolean fact, two independent triggers

The bead's original phrasing ("mark exhausted when Phase 6 hits its hard cap,
`round >= 6`") covers only the *chatty-bot* case. Phase 6's `round >= 6` cap
fires **only when a re-review arrives** (`wait-for-pr-comments/SKILL.md:402`);
when the bot goes **silent**, Phase 6 exits via `no_rereview_started`
(`:411`) without advancing the round counter. The #213 failure is silence, so
a round-arrival-only trigger would never fire on the incident it targets.

Resolution — **one boolean fact, `bot_review_cap_exhausted`, set true by
either of two independent triggers:**

- **Silent trigger (the #213-relevant one).** A persisted counter
  `polling.rereview_round_count` counts *silent re-review asks on the current
  head only*: it is incremented by exactly 1 each time a Phase 6 re-review
  request on the current head exits silent (`no_rereview_started`). When it
  reaches the **silent cap** (`SILENT_REREQUEST_CAP = 1`),
  `bot_review_cap_exhausted` is set true. `rereview_round_count` counts silent
  asks and nothing else — it does **not** track arriving-review rounds.
- **Chatty trigger.** When Phase 6's existing in-memory `round` counter hits
  its `round >= 6` cap (bot keeps re-reviewing; `SKILL.md:402`),
  `bot_review_cap_exhausted` is additionally set true. This trigger reads the
  existing in-memory `round`; it does **not** touch `rereview_round_count`.
  (The existing cap-exceeded ESCALATE behavior is unchanged; this only adds the
  persisted flag.)

The two triggers are distinct mechanisms for distinct pathologies (a dead bot
vs. an over-chatty bot) that happen to share one output boolean. There is no
unified count across them — do not sum the silent count and the in-memory
round.

**Reset is keyed to head lineage, for free.** The inventory filename embeds
`head_sha_after_push`
(`~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<head_sha_after_push>.json`,
`wait-for-pr-comments/SKILL.md:705`), so a genuinely new fix commit → new
inventory file → `rereview_round_count` back to 0 (the bot gets its ask afresh
on new work), while re-poking an *unchanged* silent head reuses the same file
and accumulates. Phase 6 seeds its working silent-count from the prior
inventory for the same head.

### Why "one ask" holds across the whole flow (silent cap = 1)

Decision locked with Scott: the bot is asked to re-review **once, properly**;
if it stays silent past `bot_inactivity_timeout_seconds`, the ask is spent and
the cap is exhausted. Re-poking a bot that already ignored a proper request
rarely helps, and a low cap minimizes the human's wait before the escape hatch
unlocks.

The single Phase 6 ask can be issued from either of two places, and it is
still **one** ask because both increment the same head-keyed counter:

- **Disciplined completion-gate flow.** `wait-for-pr-comments` runs before
  merge-guard. If it pushed a fix, its own Phase 6 re-requests the bot; on
  silence it increments `rereview_round_count` to 1 and sets
  `bot_review_cap_exhausted`. By the time merge-guard runs Step 3 the fact is
  already true, so merge-guard's auto-retry backstop is correctly skipped and
  control goes straight to the cap-exhausted sub-branch (force-merge or
  handoff). This is intended, not a dead branch.
- **Backstop paths.** merge-guard is reached with the head unreviewed and the
  ask *not yet spent* (`bot_review_cap_exhausted == false`): a direct
  merge-guard invocation with no preceding `wait-for-pr-comments` re-request,
  or the #213 case where the fix push bypassed Phase 6 so the bot was never
  asked. Here merge-guard issues the one ask by calling `request-rereview.sh` +
  the re-review poll helpers directly (not the full skill — see Design overview
  part 2), incrementing and persisting the silent counter itself. On silence
  the cap exhausts and the next Step-3 re-run routes to the cap-exhausted
  sub-branch.

In the normal path exactly one re-review ask fires per head; the count is
bounded at **two** only under a persisted-write failure (the disciplined-flow
ask persists nothing, so merge-guard's backstop, reading `exhausted == false`,
asks again) — still bounded, still ending in hand-off, never fail-open.
`SILENT_REREQUEST_CAP` is a Phase 6 / backstop constant (a one-line change if
ever made configurable — deliberately not a config key in v1; YAGNI).

**Termination is guarded independently of persistence.** merge-guard issues
**at most one** re-review ask per merge-guard invocation, then re-runs Step 3
exactly once and, if still not satisfied, hands off — it never loops on the
flag. A `bot_review_cap_exhausted` that failed to
persist (e.g. an inventory write error) therefore fails **toward hand-off**,
never toward an unbounded retry. The persisted flag is a legibility/skip
optimization for the disciplined flow, not the sole loop bound.

## Config schema (`[merge-policy]`, Axis 2)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `allow-force-after-bot-timeout` | bool | `false` | When `true` **and** `merge-rule = bot-quiescence`, unlocks the scoped force-merge sub-branch after the retry ask is exhausted. Meaningless (and rejected by the resolver) with any other rule. Existing repos get zero behavior change unless they opt in. |

## Resolver changes (`resolve_policy.py`)

1. **`MERGE_POLICY_KEYS`** (currently line 71):

   ```python
   MERGE_POLICY_KEYS = {"merge-authorization", "merge-rule"}
   ```

   →

   ```python
   MERGE_POLICY_KEYS = {"merge-authorization", "merge-rule", "allow-force-after-bot-timeout"}
   ```

2. **`ReviewMergePolicy` dataclass** — add field
   `allow_force_after_bot_timeout: bool = False` (snake_case, matching
   `merge_authorization` / `merge_rule`), with the same default in the
   module's default-policy constructor.

3. **`resolve_policy()`** — read the key with the existing typed accessor
   (mirrors how bool keys are read):
   `_typed(merge, "allow-force-after-bot-timeout", bool, False)`, threading the
   value into the `ReviewMergePolicy(...)` construction.

4. **`validate()`** — add a coupling check alongside the existing
   bot-quiescence block (after line 165), mirroring its shape:

   ```python
   if policy.allow_force_after_bot_timeout and policy.merge_rule != "bot-quiescence":
       raise PolicyError(
           "allow-force-after-bot-timeout is only valid with merge-rule=bot-quiescence")
   ```

   `validate()` never degrades — it raises. An `allow-force-after-bot-timeout`
   set under any other authorization/rule is a hard `PolicyError`.

## Eligibility facts (`check-merge-eligibility.sh`)

Add a new fact **`facts.bot_review_cap_exhausted`** (bool). It is
**complementary** to the existing GitHub-API-derived `review_wait.bot`
(emitted by `set_fact review_wait` at `:385`; the `timed_out` decision is at
`:356`): `review_wait.bot` reports the live bot-wait state from the API; the
new fact reports whether the persisted one-ask budget is spent.

**Read it from the single head-exact inventory file, never the glob-all.** The
untriaged-feedback scan deliberately globs every head's file
(`find … -name "${OWNER}-${REPO}-${PR}-*.json"`, `:413-414`) because it unions
triage state across pushes. This fact must **not** reuse that pattern: read
only the inventory whose `head_sha_after_push` equals the PR's current
`HEAD_OID` (`:125`) — i.e. the single path
`${HOME}/.claude/state/pr-inventory/${OWNER}-${REPO}-${PR}-${HEAD_OID}.json`.
A stale `exhausted=true` from a superseded head must never leak onto a fresh
head; head-lineage reset (above) depends entirely on this exact-match read.

Fail-closed defaulting (force-merge stays locked unless the budget is provably
spent *for this head*):

- Current-head inventory present with the field → emit its boolean value.
- Present without the field (older writer) → emit `false`.
- Current-head inventory absent → emit `false`.
- Current-head inventory unreadable/malformed → emit `false` (a malformed file
  resolves to `false`, unlike the untriaged scan's `|| continue` skip which
  fails closed by *keeping items untriaged*; for a boolean, only `false` is
  fail-closed).

The fact is additive; every existing fact, blocker, and the eligibility floor
(exit 0 ⟺ `blockers == []`, `:477`) are unchanged.

## Inventory schema + Phase 6 (`wait-for-pr-comments`)

### Schema — additive at `schema_version: 1` (NO bump)

Add two fields under `polling`:

```jsonc
"polling": {
  "copilot_status": "review_found" | "timeout" | "not_requested",
  "rereview_round_count": 0,           // NEW: int, silent-ask count on current head, default 0
  "bot_review_cap_exhausted": false    // NEW: bool, default false
}
```

**Do not bump `schema_version`.** `schema_version: 2` is reserved for
`agents-config-58m` (`wait-for-pr-comments/SKILL.md:766`), and Guard 0
(`validate-inventory.sh:71`, documented at `wait-for-pr-comments/SKILL.md:886`)
and `reply-and-resolve-pr-threads/SKILL.md:322` both hard-assert
`schema_version == 1` — a bump would reject every current inventory and break
~20 tests that hardcode v1. `validate-inventory.sh` performs **no** strict
key-check on `polling` (verified), so two additive optional fields are
backward-compatible: existing consumers read specific paths and ignore the new
keys. Unlike the deferred `copilot_review_submitted_at` (a field with no
consumer, correctly parked for v2), these two are **actively consumed in this
PR** by `check-merge-eligibility.sh`, so they belong at v1 now.

**Coordination breadcrumb:** when `agents-config-58m` eventually bumps to
`schema_version: 2`, whoever does it folds `rereview_round_count` and
`bot_review_cap_exhausted` into the v2 schema doc alongside the re-added
`copilot_review_submitted_at`. That is a documentation merge, not a breaking
change.

### Population site

The two new fields are written into the **`POLLING_FILE` object that Phase 6/7
assembles** before calling `build-inventory-body.sh` — that helper passes
`polling` through verbatim (`build-inventory-body.sh:55`,
`polling: $polling[0]`), and `write-inventory.sh` only mutates
`.crash_recovery`. So **neither helper script needs a change**; the Phase 6/7
construction of `POLLING_FILE` must include `rereview_round_count` and
`bot_review_cap_exhausted` (defaults 0 / false). `validate-inventory.sh`
requires no change (additive, non-strict `polling`); if a positive check is
wanted it is a *type* check (int ≥ 0 / bool), never a version bump.

### Phase 6 behavior

1. **Seed** the working silent-count from the prior inventory for the same head
   on entry, so a merge-guard-driven re-invocation on an unchanged head
   accumulates rather than resets.
2. **On the silent exit path** (`no_rereview_started`): increment
   `rereview_round_count` by 1; if it reaches `SILENT_REREQUEST_CAP` (= 1), set
   `bot_review_cap_exhausted = true`. Persist both via the normal Phase 7
   write (into `POLLING_FILE`).
3. **On the existing `round >= 6` chatty cap** (`:402`): additionally set
   `bot_review_cap_exhausted = true`. This reads the in-memory `round`; it does
   not modify `rereview_round_count`.
4. **`PushNotification`** fires once, at the false → true transition of
   `bot_review_cap_exhausted`, so the human is told the retry window closed and
   need not babysit it.

## Gate wiring (`merge-guard/SKILL.md` Step 4, `rule-based` branch)

Replace the current "rule not satisfied" bullet (lines 124–127):

```
- Rule not (yet) satisfied or blocked → report status and stop. NO
  force-merge in this mode. A timed-out bot (`review_wait.bot ==
  "timed_out"`) never satisfies the rule — hand off to the human with the
  facts.
```

with a retry/escape decision bound to concrete machine signals. All predicates
below are exact facts, not prose judgment:

- **floor-clean** ⟺ `check-merge-eligibility.sh` returned exit 0 with
  `blockers == []`.
- **rule-unmet** ⟺ `facts.bot_clean_review_at_head == false`.
- **ask-spent** ⟺ `facts.bot_review_cap_exhausted == true`.

```
- Rule not (yet) satisfied → branch:
  - **Not floor-clean** (any blocker beyond the unmet bot-quiescence rule):
    report blockers and stop. Fail closed; no retry, no force-merge.
  - **floor-clean AND rule-unmet AND NOT ask-spent**: issue ONE re-review ask
    on the current head by calling `request-rereview.sh` + the re-review poll
    helpers directly (never a bare reply+resolve; **not** the full
    `wait-for-pr-comments` skill, which skips its re-request phase on a
    no-feedback head — `SKILL.md:177-178`). Increment + persist the silent
    counter. Re-run Step 3 against the unchanged head exactly once. A clean
    re-review now satisfies the rule → merge (Step 5). Otherwise (bot silent →
    ask now spent, or the flag failed to persist): do NOT ask again — fall
    through to hand-off. merge-guard issues at most one re-review ask per
    invocation.
  - **floor-clean AND rule-unmet AND ask-spent AND force-merge available**:
    reachable ONLY when ALL of — floor-clean, rule-unmet, ask-spent,
    `policy.allow_force_after_bot_timeout == true`, and a FRESH in-session
    human instruction using the words "force merge" AND naming the
    bot-quiescence blocker (identical gating to explicit-mode force-merge —
    never a standing grant, never inferred). Merge (Step 5), logging the
    bypassed blocker + the instruction text into the merge commit context / PR
    comment (same directive as the explicit-mode force-merge log).
    **This scoped force-merge uses its own terminal merge and does NOT enter
    Step 5's `--admin` rejection ladder.** It merges with
    `gh pr merge <n> --squash --match-head-commit <head_ref_oid>` and treats
    ANY GitHub rejection as hand-off — it never consults `admin_bypass`, never
    retries with `--admin`. The force-merge instruction authorized bypassing
    *this policy's* bot-quiescence gate, not GitHub's (blanket, per-ruleset)
    `--admin` bypass. (The Step 5 guard below gates the `--admin` ladder to
    normal-authorization entries, so this cannot slip through even as prose.)
  - **floor-clean AND rule-unmet AND ask-spent AND force-merge NOT available**
    (repo hasn't set `allow-force-after-bot-timeout`, or no fresh named
    instruction): report status and hand off. NO autonomous force-merge. A bot
    that never reviewed is never treated as approval.
```

## Step 5 guard (`merge-guard/SKILL.md`, `--admin` ladder)

The `--admin` rejection ladder (`:150-173`) is currently reachable from any
Step-5 entry. Add a guard so it is reachable **only for merges authorized
through normal eligibility** (explicit-mode named force-merge, or a rule-based
rule that actually held). A merge entered via the scoped bot-timeout
force-merge sub-branch does **not** enter this ladder — its terminal merge
treats any GitHub rejection as hand-off. This makes the no-`--admin`-chaining
rule **structural** (co-located with the `--admin` decision), not a
cross-section prose dependency the reader must remember. Concretely: the
`--admin` retry row (`:155`) gains a precondition that the merge was authorized
by the normal path, not the bot-timeout force-merge.

## Decision Matrix additions

The existing 5-column matrix (`Axis 2 | Eligible | Rule holds | Human
instructed | Action`, `merge-guard/SKILL.md:177`) stays intact for the
`never`/`explicit` rows. Replace only the three `rule-based` rows (currently
lines 183–185) with a dedicated rule-based sub-table that adds the two new
axes:

| Axis 2 | Floor clean (eligible) | Rule holds | Ask spent | Force opted-in + fresh named instruction | Action |
|---|---|---|---|---|---|
| rule-based | yes | yes | n/a | n/a | **Merge autonomously** |
| rule-based | yes | no | no | n/a | Issue one re-review ask (`request-rereview.sh` + poll), re-check |
| rule-based | yes | no | yes | yes | **Force-merge** (logged; no `--admin` chaining) |
| rule-based | yes | no | yes | no | Report; hand off (no force-merge) |
| rule-based | no | any | any | any | Report blockers (no force-merge, no retry) |

## Red Flags additions

| Thought | Reality |
|---------|---------|
| "I'll just reply to the bot's comment and resolve the thread" (bot-quiescence repo) | A hand-rolled reply+resolve leaves the head **unreviewed** and defeats the retry loop — the #213 bug. Route every fix-commit push through Phase 6 / `request-rereview.sh` so the bot is actually re-requested. |
| "The bot timed out, just force it" | Force-merge in rule-based needs ALL of: `allow-force-after-bot-timeout = true`, ask spent (`bot_review_cap_exhausted`), the floor clean so bot-quiescence is the *sole* remaining blocker, and a fresh in-session instruction naming it. Not implicit, not a standing grant. |
| "Bot never reviewed — good enough, that's basically approval" | No. Silence is not attestation. The rule is fail-closed; the only exits are a clean re-review or a human-authorized scoped force-merge. |
| "Force-merge got rejected by GitHub, just add `--admin`" | A scoped bot-quiescence force-merge does **not** auto-escalate to `--admin` — that is a blanket per-ruleset bypass the human did not authorize. Hand off; `--admin` is reachable only via its own separate gate. |

## Design-doc amendment (`docs/architecture/review-merge-policy/design.md`)

Amend the bot-quiescence rule's lifecycle to document: the bounded auto-retry
backstop (at most one ask per head), the `rereview_round_count` (silent-ask
count) / `bot_review_cap_exhausted` facts and their two triggers, the
head-exact read, and the opt-in `allow-force-after-bot-timeout` escape hatch
with its full machine-explicit gating and its explicit non-chaining into
`--admin`. Does not touch the agent-ruling paragraphs that
`agents-config-xvmf8` amends.

## Test plan

- **`resolve_policy.py`** — unit tests mirroring the existing bot-quiescence
  key-coupling tests:
  - `allow-force-after-bot-timeout = true` with `merge-rule = bot-quiescence`
    → accepted.
  - `= true` with `merge-rule = human-approvals`, `agent-ruling`, or with
    `merge-authorization` ≠ `rule-based` → `PolicyError`.
  - key absent → field defaults `False`, no error.
  - type-mismatch (non-bool) → `PolicyError` (via `_typed`).
- **`check-merge-eligibility.sh`** (`check-merge-eligibility_test.sh`) —
  coverage for the new head-exact fact read:
  - current-head inventory present-true → fact true.
  - present-false / field-absent / inventory-absent / malformed → fact false.
  - **stale-head guard**: a prior-head inventory with `exhausted=true` present
    while the current-head inventory is absent → fact **false** (the glob-all
    leak the head-exact read must prevent).
- **`wait-for-pr-comments`** helpers — `build-inventory-body_test.sh` /
  `write-inventory_test.sh`: the two new `polling` fields pass through with
  correct defaults and `validate-inventory.sh` still accepts (schema_version
  stays 1). A Phase-6 unit covering: silent exit increments
  `rereview_round_count` and sets `exhausted` at the silent cap; count seeds
  from a prior same-head inventory; a new head starts at 0.
- **SKILL.md prose** — verify Decision-Matrix sub-table ↔ Step-4 branch ↔
  Red-Flags are internally consistent (no contradiction; the old
  `review_wait.bot == "timed_out"` hand-off is fully superseded; no `--admin`
  chaining from scoped force-merge).

## Coordination with agents-config-xvmf8

Same files, disjoint rows/keys:

- `merge-guard/SKILL.md` Step 4 rule table: xvmf8 replaces the `agent-ruling`
  row; this spec extends the `bot-quiescence` path. Adjacent edits → expect a
  routine **textual** merge conflict, not a semantic one.
- `resolve_policy.py`: xvmf8 adds judge keys to `MERGE_POLICY_KEYS` + a
  `validate()` coupling; this spec adds `allow-force-after-bot-timeout` the
  same way. Both follow the existing key-coupling pattern — resolve by keeping
  both.

Rebase against whichever lands first. This spec deliberately mirrors xvmf8's
subsection skeleton (Config schema → Resolver → Eligibility/Gate wiring →
Decision Matrix / Red Flags → Design-doc → Test plan) to make that rebase
mechanical.

## Decisions locked (with Scott)

- Silent re-request cap = **1** (ask once properly; silence → exhausted). One
  Phase 6 ask total per head, whether issued inside `wait-for-pr-comments` or
  by merge-guard's backstop.
- Scoped force-merge (part c) is **in scope** for this spec/PR, dormant behind
  default-false `allow-force-after-bot-timeout`.
- **`PushNotification`** on cap-hit: **yes**.
- Inventory schema: **additive at v1, no bump** (corrected during spec drafting
  from the initially-presented v2 bump — v2 is reserved for `agents-config-58m`
  and a bump breaks Guard 0 across two skills).

## Hardening decisions (from adversarial spec review)

These closed conditional fail-open / robustness gaps found reviewing the first
draft:

- **Head-exact read, fail-closed** — the `bot_review_cap_exhausted` read is a
  single HEAD_OID-keyed file, never the glob-all; absent/malformed → `false`.
  Prevents a stale `exhausted=true` from a prior head unlocking force-merge on
  never-retried new work.
- **In-process retry ceiling** — merge-guard issues at most one re-review ask
  per invocation and fails toward hand-off, so a flag that fails to persist
  cannot cause unbounded re-invocation.
- **Backstop reaches the ask directly** — the backstop calls
  `request-rereview.sh` + poll helpers, not the full `wait-for-pr-comments`
  skill (which skips its re-request phase on a no-feedback head), so the ask
  mechanically fires in the #213 residual instead of silently no-op'ing.
- **No `--admin` chaining** — a scoped bot-quiescence force-merge uses its own
  terminal merge (any rejection → hand-off), and the Step 5 `--admin` ladder is
  guarded to normal-authorization entries, so it cannot escalate into the
  blanket per-ruleset bypass.
- **Machine-explicit force-merge precondition** — floor-clean ⟺ exit 0 /
  `blockers == []`, rule-unmet ⟺ `bot_clean_review_at_head == false`,
  ask-spent ⟺ `bot_review_cap_exhausted == true`; not LLM prose judgment.
- **Counter semantics** — `rereview_round_count` is the silent-ask count only
  (cap 1); the chatty `round >= 6` trigger uses the existing in-memory `round`.
  Two triggers, one boolean, no unified count.

## Out of scope

- Making `SILENT_REREQUEST_CAP` a config key (constant in v1; trivial to
  promote later).
- Any change to the `human-approvals` or `agent-ruling` rules.
- Parallelizing the retry across multiple bots (bot-quiescence is single
  trusted-bot today).

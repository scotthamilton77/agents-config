---
name: merge-guard
description: >
  Pre-merge enforcement point for the repo's review/merge policy. Resolves the
  policy (resolve_policy.py), computes the live eligibility floor + review
  facts (check-merge-eligibility.sh), then applies the merge-authorization
  axis: never / explicit (default) / rule-based. Invoke proactively before
  any `gh pr merge`, `git merge`, or merge action.
model: sonnet[1m]
effort: low
---

# Merge Guard

Enforces the two-axis review/merge policy at the merge boundary. A merge
happens **iff the PR is eligible (no blockers) AND the action is authorized
(Axis 2)**. Contract: `docs/architecture/review-merge-policy/design.md`.

**Triggers:** any action that merges a PR — `gh pr merge`, merge buttons,
`git merge` of a PR branch.

**Don't use when:** merging local branches unrelated to a PR.

## The Process

### Step 1: Determine PR context

Identify `owner`, `repo`, PR number (explicit argument, conversation context,
or `gh pr view --json number,url`), and the repo root.

### Step 2: Resolve the policy

```bash
POLICY_JSON=$(python3 "${CLAUDE_SKILL_DIR}/resolve_policy.py" \
  --project-config "<repo-root>/project-config.toml" \
  --labels "<comma-separated bead labels, or empty>")
```

- Labels: when working a bead, `bd label list <bead-id> --json | jq -r 'join(",")'`;
  otherwise pass `--labels ""`.
- Resolver exit 1 = invalid policy config. **Stop. Report the error verbatim.
  Do not merge, do not fall back to defaults** — a repo that misconfigured its
  merge policy must not get a silently different one.
- python3 (>= 3.11) missing, or the resolver crashes/errors for any reason
  other than a reported `PolicyError` → **never** silently substitute the
  built-in default. Check whether `<repo-root>/project-config.toml` has a
  `[merge-policy]` section (e.g. `grep -q '^\[merge-policy\]' project-config.toml`):
  - **Section present** → the repo configured a real policy this step could
    not resolve. **Refuse any agent-side merge and hand off to the human**,
    naming the degradation verbatim (e.g. "python3 unavailable — could not
    resolve this repo's configured `[merge-policy]`; merge by hand"). Falling
    back to `explicit` here would silently re-enable agent merges a
    configured `never` policy forbids.
  - **Section absent** → no policy is configured at all; fall back to the
    built-in default policy (`explicit`) and say so — that is exactly
    today's law, the safe floor.

### Step 3: Run the eligibility check

```bash
${CLAUDE_SKILL_DIR}/check-merge-eligibility.sh \
  --owner <owner> --repo <repo> --pr <n> --policy-json "$POLICY_JSON"
```

| Exit | Meaning |
|------|---------|
| 0 | Eligible — no blockers; facts populated |
| 1 | Blocked — every reason in `.blockers[]` |
| 3 | Error — unknown state. Report it. **Do not merge.** |

The JSON carries: `head_ref_oid` (the SHA every fact was computed against),
`blockers[]` (`{code, details}`), `facts` (`bot_clean_review_at_head`,
`distinct_current_approvers`, `ci_state`, `review_wait`, `admin_bypass`, ...),
and `merge_command_hint`.

`facts.admin_bypass` (`{review_rule_active, required_approving_review_count,
current_actor_can_bypass}`) is never a blocker — it never affects eligibility.
It exists solely for Step 5, to decide whether a GitHub-side review-count
rejection may be retried with `--admin`.

### Step 4: Apply Axis 2 (`merge_authorization` from the policy JSON)

**`never`** — the agent never merges, not even on an in-session instruction.
If the user says "merge it", refuse with: this repo's policy is human-manual
merge; share the eligibility summary so they can merge in the GitHub UI.
Force-merge is NOT available.

**`explicit`** (default) — merge iff **eligible AND the human gave an explicit
in-session instruction**. Authorized phrases: "go ahead and merge", "merge
it", "ship it", "yes merge". "ok"/"sure" are not sufficient.
- Eligible + no instruction → present the summary and wait:
  > "PR #N is eligible to merge — no blockers. `review_wait`: <facts>. Ready
  > when you are. Just say the word."
  When the merge word arrives later, **re-run Step 3 before merging** — do
  not merge off the earlier summary. `--match-head-commit` at Step 5 only
  catches a moved head; a new `CHANGES_REQUESTED` verdict, thread, or
  comment on the *same* head can land during the wait and would otherwise
  slip through unnoticed.
- Instructed + blocked → **fail closed.** Report every `blockers[]` entry and
  offer:
  > 1. **Wait** — invoke `wait-for-pr-comments` (poll, classify, fix, push,
  >    reply, resolve), then re-run this guard.
  > 2. **Force merge** — see below.
- **Force-merge (the ONE eligibility-bypass path):** valid only in `explicit`
  mode, only on a fresh in-session instruction that (a) uses the words "force
  merge" and (b) names the blocker being overridden (e.g. "force merge past
  the pending Copilot review"). A bare "force merge" → ask which blocker they
  are overriding, then proceed and log both the blockers bypassed and the
  instruction into the merge commit context / PR comment. Never available to
  `never`, `rule-based`, or any autonomous path.

**`rule-based`** — merge autonomously iff **eligible AND the configured
`merge_rule` holds** (evaluated from `facts`):

| Rule | Holds when |
|------|-----------|
| `bot-quiescence` | `facts.bot_clean_review_at_head == true` (a trusted `bot-reviewers` identity actually reviewed the current head clean) |
| `human-approvals` | `facts.distinct_current_approvers >= human_approvers_required` |
| `agent-ruling` | Never (design-reserved) — the resolver already rejects it; if somehow reached, report "not implemented" and hand off |

- Rule holds + eligible → merge now (Step 5). Announce what authorized it:
  > "Merging PR #N under rule-based policy (`bot-quiescence`): Copilot
  > reviewed head <sha> clean, no blockers."
- Rule not (yet) satisfied → branch on concrete machine signals, never prose
  judgment. All predicates below are exact facts:
  - **floor-clean** ⟺ `check-merge-eligibility.sh` returned exit 0 with
    `blockers == []`.
  - **rule-unmet** ⟺ `facts.bot_clean_review_at_head == false`.
  - **ask-spent** ⟺ `facts.bot_review_cap_exhausted == true`.

  Branches:
  - **Not floor-clean** (any blocker beyond the unmet bot-quiescence rule):
    report blockers and stop. Fail closed; no retry, no force-merge.
  - **floor-clean AND rule-unmet AND NOT ask-spent**: issue ONE re-review ask
    on the current head by calling `request-rereview.sh` + the re-review poll
    helpers directly (never a bare reply+resolve; **not** the full
    `wait-for-pr-comments` skill, which skips its re-request phase on a
    no-feedback head — `wait-for-pr-comments/SKILL.md:177-178`). Increment +
    persist the silent counter. Re-run Step 3 against the unchanged head
    exactly once. A clean re-review now satisfies the rule → merge (Step 5).
    Otherwise (bot silent → ask now spent, or the flag failed to persist): do
    NOT ask again — fall through to hand-off. merge-guard issues at most one
    re-review ask per invocation.
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

### Step 5: Merge, bound to the checked head

```bash
gh pr merge <n> --squash --match-head-commit "<head_ref_oid from the JSON>"
```

- Use `merge_command_hint` from the JSON — it already carries the SHA.
- GitHub rejects the merge if the head moved since evaluation → **re-run from
  Step 3** against the new head. Never retry blind.
- `gh pr merge` can exit 0 while printing a rejection. Confirm:
  `gh pr view <n> --json state` (expect `MERGED`).

**If GitHub itself rejects the merge**, capture and read its actual rejection
text first — never infer the reason from context. Only proceed down this
path if that text specifically names the approving-review requirement (a
"review required" / base-branch-policy refusal naming reviews — not a
stale-head rejection, not a CI failure, not some other rule). If the text
names anything else, or you're not sure, treat it as an unknown rejection:
re-run Step 3, do not consult `admin_bypass`, do not use `--admin`.

Once the rejection is confirmed to be the approving-review requirement,
consult `facts.admin_bypass`:

| `facts.admin_bypass` | Action |
|---|---|
| `review_rule_active == false` | This wasn't a review-count rejection — something else is wrong. Re-run Step 3 from scratch; never retry blind. |
| `current_actor_can_bypass == true` | GitHub already grants the authenticated identity a standing bypass on this rule (the ruleset's `current_user_can_bypass` is `always` or `pull_requests_only`). Retry once: `gh pr merge <n> --squash --admin --match-head-commit "<head_ref_oid>"`. Announce plainly that `--admin` was used, quote the rejection text that justified it, and note why — the identity holds a pre-existing GitHub bypass grant, and eligibility + authorization were already confirmed independently of it. This is a deliberate, logged exercise of a grant a human configured, never a new override. |
| `current_actor_can_bypass == false` | The identity has no bypass grant. **Fail closed** — do not retry with `--admin`. Report the rejection and hand off to a human who either holds the bypass grant or can adjust the ruleset. |

**Precondition — reachable only via normal authorization.** This `--admin`
ladder is reachable ONLY for merges authorized through normal eligibility:
`explicit`-mode named force-merge, or a `rule-based` rule that actually held.
A merge entered via the Step 4 scoped bot-timeout force-merge sub-branch does
**not** enter this ladder — it performs its own terminal merge and stops
there, success or failure, with no `--admin` retry. Co-located here,
deliberately, so this guard can't be missed or accidentally wired to the
other path.

This `--admin` retry is **not** the force-merge override above — force-merge
bypasses *this policy's own* eligibility floor on explicit human instruction;
this retry bypasses nothing this guard controls, and every blocker this
guard's own eligibility floor asserts still fully applies. But `--admin`
itself is **not scoped to the review rule** — GitHub computes
`current_user_can_bypass` per *ruleset*, not per rule, so `--admin` blanket-
bypasses every rule in that ruleset the identity is entitled to bypass (this
repo's own ruleset, for example, bundles `deletion`, `non_fast_forward`,
`required_linear_history`, and `copilot_code_review` alongside
`pull_request` under one bypass grant). `facts.admin_bypass` certifies only
that the `pull_request` rule(s) are bypassable — it says nothing about any
other rule sharing that ruleset. That is exactly why the rejection text must
be read and confirmed first: `--admin` should only ever be reached to answer
a rejection it was actually confirmed to address. It is unreachable in
`never` mode (Step 5 never runs there) and available, once normal
authorization already succeeded, in both `explicit` and `rule-based` modes.

## Decision Matrix

| Axis 2 | Eligible | Rule holds | Human instructed | Action |
|---|---|---|---|---|
| never | any | n/a | any (even "merge it") | Refuse; human merges in UI |
| explicit | yes | n/a | no | Summarize; wait for the word |
| explicit | yes | n/a | yes | **Merge** |
| explicit | no | n/a | yes | **Fail closed**; offer wait / named force-merge |

`rule-based` carries two extra axes (ask spent, force opted-in) that don't
apply to `never`/`explicit`, so it gets its own sub-table:

### `rule-based` sub-table

| Axis 2 | Floor clean (eligible) | Rule holds | Ask spent | Force opted-in + fresh named instruction | Action |
|---|---|---|---|---|---|
| rule-based | yes | yes | n/a | n/a | **Merge autonomously** |
| rule-based | yes | no | no | n/a | Issue one re-review ask (`request-rereview.sh` + poll), re-check |
| rule-based | yes | no | yes | yes | **Force-merge** (logged; no `--admin` chaining) |
| rule-based | yes | no | yes | no | Report; hand off (no force-merge) |
| rule-based | no | any | any | any | Report blockers (no force-merge, no retry) |

## Red Flags

| Thought | Reality |
|---------|---------|
| "Copilot is slow, just merge" | The in-flight blocker exists precisely for this. Wait or get a named force-merge. |
| "The user said 'ok', close enough" | Not an authorized phrase. Ask plainly. |
| "auto_merge_eligible was true" | prgroom's rollup is never consumed. Only this guard's own gates count. |
| "The rule held five minutes ago" | Facts bind to `head_ref_oid`. Re-run Step 3; merge with `--match-head-commit`. |
| "It's blocked but rule-based says merge" | Rule-based NEVER bypasses the floor. Eligible AND rule — both. |
| "The script errored, probably fine" | Exit 3 = unknown state. Do not merge. Report. |
| "`gh pr merge` exited 0, so it merged" | It can exit 0 on rejection. Confirm state == MERGED. |
| "GitHub's review rule blocked it, just add `--admin`" | Only if `facts.admin_bypass.current_actor_can_bypass == true` **and** you've read the rejection text and confirmed it names the review requirement. If false, or you didn't check the text, hand off — don't force it. |
| "`--admin` only bypasses the review rule" | It's a blanket ruleset bypass. `facts.admin_bypass` only certifies the `pull_request` rule(s) are bypassable, not every rule in the ruleset. |
| "I'll just reply to the bot's comment and resolve the thread" (bot-quiescence repo) | A hand-rolled reply+resolve leaves the head **unreviewed** and defeats the retry loop — the #213 bug. Route every fix-commit push through Phase 6 / `request-rereview.sh` so the bot is actually re-requested. |
| "The bot timed out, just force it" | Force-merge in rule-based needs ALL of: `allow-force-after-bot-timeout = true`, ask spent (`bot_review_cap_exhausted`), the floor clean so bot-quiescence is the *sole* remaining blocker, and a fresh in-session instruction naming it. Not implicit, not a standing grant. |
| "Bot never reviewed — good enough, that's basically approval" | No. Silence is not attestation. The rule is fail-closed; the only exits are a clean re-review or a human-authorized scoped force-merge. |
| "Force-merge got rejected by GitHub, just add `--admin`" | A scoped bot-quiescence force-merge does **not** auto-escalate to `--admin` — that is a blanket per-ruleset bypass the human did not authorize. Hand off; `--admin` is reachable only via its own separate gate. |

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

Fetch and retain the live SHAs every later step binds to:

```bash
gh pr view <n> --repo <owner>/<repo> --json headRefOid,baseRefOid,baseRefName
```

`head_ref_oid`, `base_ref_oid`, and `base_ref` from this call are the trusted
values — never a bare `HEAD` that a stale local checkout could resolve
differently.

### Step 2: Resolve the policy

Read `project-config.toml` from the **base** ref fetched at Step 1, never the
working tree or head — reading from head would let a PR that edits
`[merge-policy]` define the rule that merges it. Base-resolution closes that
hole (and is double-locked by the protected-path gate at Step 4, which
independently abstains on any diff touching `project-config.toml`). A base ref
with no `project-config.toml` file resolves to the built-in defaults (the
`explicit` floor); a base ref that cannot be resolved — or whose config blob is
present but unreadable — fails closed instead of guessing at a policy, so a
transient read failure never silently downgrades a stricter configured policy.

```bash
TMP_BASE_CFG=$(mktemp)
trap 'rm -f "$TMP_BASE_CFG"' EXIT
if git show "<base_ref_oid>:project-config.toml" > "$TMP_BASE_CFG" 2>/dev/null; then
  :                                       # captured the base config
elif ! git cat-file -e "<base_ref_oid>^{commit}" 2>/dev/null; then
  echo "cannot resolve base ref <base_ref_oid> — merge by hand" >&2
  exit 3                                   # base ref unresolvable → fail closed, hand off
elif ! git cat-file -e "<base_ref_oid>:project-config.toml" 2>/dev/null; then
  : > "$TMP_BASE_CFG"                      # commit valid, project-config.toml truly absent → resolver emits defaults
else
  echo "base project-config.toml present but unreadable — merge by hand" >&2
  exit 3                                   # present-but-unreadable → fail closed, never downgrade a stricter policy
fi
POLICY_JSON=$(python3 "${CLAUDE_SKILL_DIR}/resolve_policy.py" \
  --project-config "$TMP_BASE_CFG" \
  --labels "<comma-separated bead labels, or empty>")
```

- Labels: when working a bead, `bd label list <bead-id> --json | jq -r 'join(",")'`;
  otherwise pass `--labels ""`.
- Resolver exit 1 = invalid policy config. **Stop. Report the error verbatim.
  Do not merge, do not fall back to defaults** — a repo that misconfigured its
  merge policy must not get a silently different one.
- python3 (>= 3.11) missing, or the resolver crashes/errors for any reason
  other than a reported `PolicyError` → **never** silently substitute the
  built-in default. Check whether the **base** copy fetched above
  (`$TMP_BASE_CFG`) has a `[merge-policy]` section (e.g.
  `grep -q '^\[merge-policy\]' "$TMP_BASE_CFG"`) — grep the base, never the
  working tree, so a PR cannot flip this branch by editing its own config:
  - **Section present** → the base configured a real policy this step could
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

The JSON carries: `head_ref_oid` and `base_ref_oid` (the SHAs every fact was
computed against — Step 5 re-confirms both are still current), `blockers[]`
(`{code, details}`), `facts` (`bot_clean_review_at_head`,
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
| `bot-quiescence` | `facts.bot_clean_review_at_head == true` (a trusted `bot-reviewers` identity actually reviewed the current head clean — either a submitted clean review or a clean `+1` reaction; `facts.bot_clean_signal_source` (`"review"`/`"reaction"`) records which) |
| `human-approvals` | `facts.distinct_current_approvers >= human_approvers_required` |
| `agent-ruling` | `judge_merge.py` returns `verdict == "go"` (bound to `head_ref_oid` + `base_ref_oid`). Hand off on any non-`go`: a `no-go` surfaces `summary` + `merge_blocking_findings` (its `abstain_reason` is null), while `abstain`/error surface `abstain_reason` (their `summary`/`merge_blocking_findings` are empty). NO retry, NO re-run to shop a pass — a `no-go` is recorded terminal for that (head, base, diff), and the per-PR/base attempt budget caps re-rolls. |

Unlike `bot-quiescence`/`human-approvals` (read straight from Step 3's
`facts`), `agent-ruling` requires actually invoking the judge:

```bash
python3 "${CLAUDE_SKILL_DIR}/judge_merge.py" \
  --owner <owner> --repo <repo> --pr <n> \
  --head-ref-oid <head_ref_oid> --base-ref-oid <base_ref_oid> --base-ref <base_ref> \
  --policy-json "$POLICY_JSON"
```

The rule holds iff the emitted `verdict == "go"`.

- Rule holds + eligible → merge now (Step 5). Announce what authorized it,
  branching on `facts.bot_clean_signal_source`:
  > "Merging PR #N under rule-based policy (`bot-quiescence`): Copilot
  > reviewed head <sha> clean, no blockers."

  When `facts.bot_clean_signal_source == "reaction"`, the announcement must
  also cite the reaction's `id` and `created_at` from `facts.bot_clean_reaction`
  alongside the head SHA — a reaction leaves no timeline history to audit after
  the fact, so this is load-bearing, not decorative:
  > "Merging PR #N under rule-based policy (`bot-quiescence`): Codex reacted
  > `+1` clean on head <sha> (reaction id <id>, <created_at>), no blockers."
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
    on the current head by calling `request-rereview.sh` + `poll-copilot-review.sh`
    directly (never a bare reply+resolve; **not** the full
    `wait-for-pr-comments` skill, whose Phase 2 timeout-exit path jumps
    straight to inventory-write with empty items on a no-feedback head,
    skipping its Phase 6 re-request entirely). Capture a timestamp
    (`ASK_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)`) BEFORE calling
    `request-rereview.sh`, then pass `--bot-reviewers
    "$(jq -c '.bot_reviewers' <<<"$POLICY_JSON")"` — the same resolved
    allowlist Step 3 already used — to BOTH the request and the poll, plus
    `--since-timestamp "$ASK_TS"` and `--timeout-seconds
    "$(jq -r '.bot_inactivity_timeout_seconds' <<<"$POLICY_JSON")"` to the
    poll. Without `--since-timestamp`, an older `COMMENTED` review from a
    prior head (already fixed, already rejected by Step 3 on `commit_id`
    mismatch) reads as this ask's response and never spends the silent
    counter — the ask never truly ends, and every later invocation issues
    another one indefinitely. Without `--timeout-seconds` bound to the
    resolved policy, the poll falls back to its own 600-second default
    instead of the policy's configured `bot_inactivity_timeout_seconds`
    (1200s by default) — a bot that responds between 10 and 20 minutes then
    reads as silent and wrongly spends the budget. This dispatches to every
    trusted identity (including comment-triggered ones like Codex, which
    never responds to a bare reviewer-request event), bounded to exactly
    this ask's window — though `request-rereview.sh`'s own contract exits 0
    once AT LEAST ONE dispatch succeeds (never per-identity), so a partial
    failure (e.g. Copilot's reviewer-add succeeds, Codex's issue-comment
    fails) is indistinguishable at this call site from full dispatch; the
    identity that was never actually asked then reads as a timed-out silent
    bot rather than an undelivered ask. Accepted here — closing it requires
    `request-rereview.sh` itself to expose per-identity outcome, which is
    outside this caller-edit's scope and affects its other caller (Phase 6
    in `wait-for-pr-comments`) too. Branch on the poll's `completion_kind`,
    not on whether a review object arrived:
    - `"review"` or `"clean_reaction"` — the ask reached a reviewer and it
      responded, whichever way. This is NOT silence; do not touch the silent
      counter. Re-run Step 3 against the unchanged head exactly once. A
      genuinely clean pass now satisfies the rule (either
      `bot_clean_review_at_head` path) → merge (Step 5). A findings-bearing
      review still leaves the rule unmet → fall through to hand-off.
    - `"timeout"` — the ask was genuinely silent. THIS is what increments +
      persists the silent counter (ask-spent), never the other two kinds.
      Fall through to hand-off.

    merge-guard issues at most one re-review ask per invocation.
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

Immediately before merging, re-run the **full Step 3 eligibility floor** — not
merely a head/base currency check. Require exit 0, `head_ref_oid` **and**
`base_ref_oid` unchanged since Step 1, and zero blockers. Any new same-head
blocker (a fresh `CHANGES_REQUESTED`, thread, or comment that landed during a
wait or the judge's run) → terminal hand-off, never a blind retry. This is the
same discipline `explicit` mode already applies after a wait (Step 4), carried
through to every path — most importantly `agent-ruling`'s minutes-long judge
window, where review state has the most time to shift underneath it.

**Pre-merge approval (only when the policy carries an approver).** If
`POLICY_JSON.approver` is non-null AND
`gh pr view <n> --json reviewDecision -q .reviewDecision` reads
`REVIEW_REQUIRED`, satisfy the review requirement with the App attestation
before merging:

    KEY_ENV="<policy.approver.key_path_env>"           # e.g. MERGE_GUARD_APPROVER_KEY_PATH
    if [ -z "${!KEY_ENV:-}" ]; then
      echo "approver configured but \$$KEY_ENV is unset — merge by hand" >&2
      exit 3                                            # fail loud; hand off
    fi
    python3 "${CLAUDE_SKILL_DIR}/approve_pr.py" \
      --repo <owner>/<repo> --pr <n> \
      --head-sha "<head_ref_oid from the re-cleared floor JSON>" \
      --app-id <policy.approver.app_id> \
      --key-path "${!KEY_ENV}" \
      --facts '<compact JSON: {"rule": <merge_rule>, "bot_clean_review_at_head": ..., "ci_state": ...} from facts>'

- Exit 0 → re-read `gh pr view <n> --json reviewDecision -q .reviewDecision`.
  `APPROVED` → proceed to the plain merge below (the script is idempotent: an
  existing App approval at this head is a no-op). Still `REVIEW_REQUIRED` →
  **HALT and hand off**: the App's approval did not satisfy the rule — a
  design assumption is falsified; report it, do not merge, do not `--admin`.
- Exit 1 (head moved) → re-run from Step 3 against the new head. Never
  retry blind.
- Exit 2 (key/mint/API failure) → **HALT. Report the script's stderr
  verbatim and hand off to the human.** Never retry silently, never fall
  back to `--admin`. The approver failing is a hand-off, not a bypass
  ticket.
- `reviewDecision` already `APPROVED` (or null — no review requirement) →
  skip this step entirely.

The approver is **mechanism, not authorization**: it never runs unless
Axis 2 already authorized the merge (a rule that held, or an explicit
in-session instruction) and the floor re-cleared. Under `never` it is
unreachable. The review it posts states what it attests and that it is not
a human review.

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
| `current_actor_can_bypass == true` **and the merge was human-instructed in-session** (explicit-mode merge word or named force-merge) | GitHub already grants the authenticated identity a standing bypass on this rule. Retry once: `gh pr merge <n> --squash --admin --match-head-commit "<head_ref_oid>"`. Announce plainly that `--admin` was used, quote the rejection text that justified it, and note why — the identity holds a pre-existing GitHub bypass grant, and eligibility + authorization were already confirmed independently of it. |
| `current_actor_can_bypass == true` **and the merge is autonomous** (`rule-based`, no in-session human instruction) | **Fail closed — `--admin` is never an autonomous path** (the auto-mode classifier blocks unsupervised `--admin`, and policy agrees). Hand off to the human, or configure `[merge-policy.approver]` so autonomous merges satisfy the review rule instead of bypassing it. |
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
apply to `never`/`explicit`, so it gets its own sub-table. The force-merge
axes are bot-quiescence-only: `agent-ruling` cannot opt into force (the
resolver rejects `allow-force-after-bot-timeout` outside `bot-quiescence`),
so those rows never apply to it — its non-`go` outcomes fail closed.

### `rule-based` sub-table

| Axis 2 | Floor clean (eligible) | Rule holds | Ask spent | Force opted-in + fresh named instruction | Action |
|---|---|---|---|---|---|
| rule-based | yes | yes | n/a | n/a | **Merge autonomously** |
| rule-based (`agent-ruling`) | yes | judge `verdict == "go"` | n/a | n/a | **Merge autonomously** — only after Step 5's full-floor re-clear |
| rule-based (`agent-ruling`) | yes | judge ≠ `"go"` (no-go / abstain) | n/a | n/a | Fail closed; hand off (no force-merge) |
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
| "The judge said no-go, just run it again" | A `no-go` is terminal for that (head, base, diff); re-running to shop a pass is verdict-shopping. Hand off. |
| "I'll just reply to the bot's comment and resolve the thread" (bot-quiescence repo) | A hand-rolled reply+resolve leaves the head **unreviewed** and defeats the retry loop — the #213 bug. Route every fix-commit push through Phase 6 / `request-rereview.sh` so the bot is actually re-requested. |
| "The bot timed out, just force it" | Force-merge in rule-based needs ALL of: `allow-force-after-bot-timeout = true`, ask spent (`bot_review_cap_exhausted`), the floor clean so bot-quiescence is the *sole* remaining blocker, and a fresh in-session instruction naming it. Not implicit, not a standing grant. |
| "Bot never reviewed — good enough, that's basically approval" | No. Silence is not attestation. The rule is fail-closed; the only exits are a clean re-review or a human-authorized scoped force-merge. |
| "Force-merge got rejected by GitHub, just add `--admin`" | A scoped bot-quiescence force-merge does **not** auto-escalate to `--admin` — that is a blanket per-ruleset bypass the human did not authorize. Hand off; `--admin` is reachable only via its own separate gate. |
| "approve_pr.py failed, fall back to `--admin`" | No. The approver's fail-loud contract IS the design: exit != 0 → hand off to the human. `--admin` never launders an approver failure. |
| "Rule held, GitHub wants a review, I hold a bypass — `--admin` it" | Autonomous `--admin` is dead — the auto-mode classifier blocks unsupervised `--admin`. The approver path exists precisely for this; if it isn't configured, hand off. |

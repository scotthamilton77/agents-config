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
`explicit` floor); a base ref that cannot be resolved at all fails closed
instead of guessing at a policy.

```bash
TMP_BASE_CFG=$(mktemp)
if git show "<base_ref_oid>:project-config.toml" > "$TMP_BASE_CFG" 2>/dev/null; then
  :                                       # captured the base config
elif git cat-file -e "<base_ref_oid>^{commit}" 2>/dev/null; then
  : > "$TMP_BASE_CFG"                      # base commit valid, no project-config.toml → resolver emits defaults
else
  echo "cannot resolve base ref <base_ref_oid> — merge by hand" >&2
  exit 3                                   # base ref unresolvable → fail closed, hand off
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
| `bot-quiescence` | `facts.bot_clean_review_at_head == true` (a trusted `bot-reviewers` identity actually reviewed the current head clean) |
| `human-approvals` | `facts.distinct_current_approvers >= human_approvers_required` |
| `agent-ruling` | `judge_merge.py` returns `verdict == "go"` (bound to `head_ref_oid` + `base_ref_oid`). `no-go`/`abstain`/error → report `abstain_reason` and hand off. NO retry, NO re-run to shop a pass — a `no-go` is recorded terminal for that (head, base, diff), and the per-PR/base attempt budget caps re-rolls. |

Unlike `bot-quiescence`/`human-approvals` (read straight from Step 3's
`facts`), `agent-ruling` requires actually invoking the judge:

```bash
python3 "${CLAUDE_SKILL_DIR}/judge_merge.py" \
  --owner <owner> --repo <repo> --pr <n> \
  --head-ref-oid <head_ref_oid> --base-ref-oid <base_ref_oid> --base-ref <base_ref> \
  --policy-json "$POLICY_JSON"
```

The rule holds iff the emitted `verdict == "go"`.

- Rule holds + eligible → merge now (Step 5). Announce what authorized it:
  > "Merging PR #N under rule-based policy (`bot-quiescence`): Copilot
  > reviewed head <sha> clean, no blockers."
- Rule not (yet) satisfied or blocked → report status and stop. NO
  force-merge in this mode. A timed-out bot (`review_wait.bot ==
  "timed_out"`) never satisfies the rule — hand off to the human with the
  facts.

### Step 5: Merge, bound to the checked head

Immediately before merging, re-run the **full Step 3 eligibility floor** — not
merely a head/base currency check. Require exit 0, `head_ref_oid` **and**
`base_ref_oid` unchanged since Step 1, and zero blockers. Any new same-head
blocker (a fresh `CHANGES_REQUESTED`, thread, or comment that landed during a
wait or the judge's run) → terminal hand-off, never a blind retry. This is the
same discipline `explicit` mode already applies after a wait (Step 4), carried
through to every path — most importantly `agent-ruling`'s minutes-long judge
window, where review state has the most time to shift underneath it.

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
| rule-based | yes | yes | n/a | **Merge autonomously** |
| rule-based (`agent-ruling`) | yes | judge `verdict == "go"` | n/a | **Merge autonomously** — only after Step 5's full-floor re-clear |
| rule-based | yes | no | any | Report; wait or hand off (no force-merge) |
| rule-based | no | any | any | Report blockers (no force-merge) |

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

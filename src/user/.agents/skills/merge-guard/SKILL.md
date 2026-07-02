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
- python3 (>= 3.11) unavailable → treat as the built-in default policy
  (`explicit`) and say so: that is exactly today's law, the safe floor.

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
`distinct_current_approvers`, `ci_state`, `review_wait`, ...), and
`merge_command_hint`.

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
- Rule not (yet) satisfied or blocked → report status and stop. NO
  force-merge in this mode. A timed-out bot (`review_wait.bot ==
  "timed_out"`) never satisfies the rule — hand off to the human with the
  facts.

### Step 5: Merge, bound to the checked head

```bash
gh pr merge <n> --squash --match-head-commit "<head_ref_oid from the JSON>"
```

- Use `merge_command_hint` from the JSON — it already carries the SHA.
- GitHub rejects the merge if the head moved since evaluation → **re-run from
  Step 3** against the new head. Never retry blind.
- `gh pr merge` can exit 0 while printing a rejection. Confirm:
  `gh pr view <n> --json state` (expect `MERGED`).

## Decision Matrix

| Axis 2 | Eligible | Rule holds | Human instructed | Action |
|---|---|---|---|---|
| never | any | n/a | any (even "merge it") | Refuse; human merges in UI |
| explicit | yes | n/a | no | Summarize; wait for the word |
| explicit | yes | n/a | yes | **Merge** |
| explicit | no | n/a | yes | **Fail closed**; offer wait / named force-merge |
| rule-based | yes | yes | n/a | **Merge autonomously** |
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

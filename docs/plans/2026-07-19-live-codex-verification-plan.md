# Live Codex-Awareness Verification Implementation Plan

> **For agentic workers:** This is an execution plan for a live test exercise
> against the real GitHub API and a real Codex reviewer — there is no new
> source code to write. Each task performs real actions (branch, PR, bot
> trigger, poll, eligibility check, merge/close) and captures real evidence.
> Work one task at a time, in order within a plan section; A1/A2a/A2b/B1/B2/B3
> are independent of each other and may run in parallel across separate
> subagents/worktrees if convenient. Steps use checkbox (`- [ ]`) syntax for
> tracking.
>
> **Constraint on parallel dispatch:** any step that invokes a fan-out skill
> via the Skill tool (Task 2 Step 4's `wait-for-pr-comments`, and every Plan
> A task's merge step below, which invokes `merge-guard`) must run in the
> top-level orchestrator, never inside a nested subagent — a subagent cannot
> reliably await children it spawns, so nesting these stalls silently.

**Goal:** Prove, against real GitHub state and a real Codex review, that the
reaction-based clean-pass path, the `review_summary` ratchet, and the poll
helpers' codex-awareness hold outside fixture-land — per
`docs/specs/2026-07-19-live-codex-verification-design.md`.

**Architecture:** Six independent scenarios (A1, A2a, A2b, B1, B2, B3), each
its own PR against `scotthamilton77/agents-config`. Plan A's three PRs merge
for real via the actual `merge-guard` skill; Plan B's three PRs are opened as
drafts, checked for eligibility directly via `check-merge-eligibility.sh`,
and closed — the merge action is a hard "never" for Plan B, enforced as a
constraint in every Plan B task below, not a per-scenario judgment call.

**Tech Stack:** `gh` CLI, the repo's own `merge-guard` and
`wait-for-pr-comments` shell/Python scripts (invoked directly, not
re-implemented), `jq` for evidence assertions.

---

## File Structure

No new source files. Files touched:

- **Scratch docs** (one per scenario, created on each scenario's branch,
  merged to `main` only for A1/A2a/A2b): `docs/architecture/live-codex-verification-scratch-a1.md`,
  `...-a2a.md`, `...-a2b.md`, `...-b1.md`, `...-b2.md`, `...-b3.md`.
- **Evidence capture** (local only, never committed):
  `/tmp/live-codex-verification-evidence/<scenario>/` — one directory per
  scenario holding the raw `gh api` JSON responses, poll-helper JSON output,
  and `check-merge-eligibility.sh` verdict JSON captured during that
  scenario's run.
- **Final report** (local only, never committed):
  `/tmp/live-codex-verification-evidence/report.md` — written in Task 8,
  handed to the user as a deliverable file, not merged into the repo.
- **Cleanup commit** (Task 7): deletes the three scratch docs A1/A2a/A2b
  left on `main`.

## Shared Setup (run once, before Task 1)

- [ ] **Step 1: Confirm repo identity and pin script/tooling paths**

```bash
cd /Users/scott/src/projects/agents-config/.claude/worktrees/live-codex-verification
git remote -v   # expect origin -> scotthamilton77/agents-config
OWNER=scotthamilton77
REPO=agents-config
MERGE_GUARD_DIR="$(pwd)/src/user/.agents/skills/merge-guard"
WFPC_DIR="$(pwd)/src/user/.agents/skills/wait-for-pr-comments"
EVID=/tmp/live-codex-verification-evidence
mkdir -p "$EVID"/{a1,a2a,a2b,b1,b2,b3}
echo "OWNER=$OWNER REPO=$REPO MERGE_GUARD_DIR=$MERGE_GUARD_DIR WFPC_DIR=$WFPC_DIR EVID=$EVID"
```
Expected: remote shows `scotthamilton77/agents-config`; all four directories/vars print without error. Keep these exported for every later task in this session — every command below assumes them.

- [ ] **Step 2: Resolve the real merge policy once (used by every Plan A task)**

```bash
python3 "$MERGE_GUARD_DIR/resolve_policy.py" --project-config project-config.toml > "$EVID/policy.json"
cat "$EVID/policy.json"
```
Expected: JSON with `"merge_authorization": "rule-based"`, `"merge_rule": "bot-quiescence"`, `"bot_reviewers"` including `"chatgpt-codex-connector[bot]"`, and a non-null `"approver"` object (`{"type": "github-app", "app_id": ..., "key_path_env": "MERGE_GUARD_APPROVER_KEY_PATH"}`). This is the real, live-resolved policy — not a hand-written fixture. (`resolve_policy.py` requires `python3 >= 3.11` for `tomllib`; if the session's default `python3` is older, invoke it via whatever the repo's own tooling uses to pin a compatible interpreter, e.g. `uv run python3`.)

- [ ] **Step 3: Confirm the App-approver key is present (precondition for Plan A's "merge fires for real" claim)**

```bash
KEY_PATH_ENV=$(jq -r '.approver.key_path_env' "$EVID/policy.json")
KEY_PATH="${!KEY_PATH_ENV:-}"
if [ -n "$KEY_PATH" ] && [ -r "$KEY_PATH" ]; then
  echo "approver key present and readable at $KEY_PATH"
else
  echo "WARNING: $KEY_PATH_ENV is unset or unreadable — merge-guard will fail closed to a human handoff on every Plan A merge attempt (approve_pr.py has no key to attest with)."
fi
```
Expected: "approver key present and readable." If the warning prints
instead, Plan A's three merge steps (Task 1/2/3) will each stop short of an
autonomous merge and hand off to a human — that's expected merge-guard
behavior given the missing key, not a bug in this plan, but it means "merge
fires for real" cannot be demonstrated until the key is available. Record
this in the final report as a precondition failure, not a scenario failure,
if it occurs.

---

## Task 1: Scenario A1 — Clean-first-pass merge

**Files:** Create `docs/architecture/live-codex-verification-scratch-a1.md` (merges to `main`).

- [ ] **Step 1: Branch, scratch doc, PR**

```bash
git checkout main && git pull --ff-only
git checkout -b live-verify-a1
cat > docs/architecture/live-codex-verification-scratch-a1.md <<'EOF'
# Live Codex Verification Scratch — A1

This file exists only to give scenario A1 (clean-first-pass merge) of
docs/specs/2026-07-19-live-codex-verification-design.md a real, trivial diff
to open a PR against. It is deleted by that plan's Task 7 cleanup once all
of A1/A2a/A2b have merged.
EOF
git add docs/architecture/live-codex-verification-scratch-a1.md
git commit -m "test(live-verify): a1 clean-first-pass scratch doc"
git push -u origin live-verify-a1
gh pr create --title "test(live-verify): A1 clean-first-pass merge" \
  --body "Live codex-awareness verification, scenario A1. See docs/specs/2026-07-19-live-codex-verification-design.md." \
  --base main --head live-verify-a1 | tee "$EVID/a1/pr-url.txt"
A1_PR=$(gh pr view live-verify-a1 --json number --jq .number)
echo "A1_PR=$A1_PR"
```
Expected: a real PR number printed and saved as `$A1_PR`. (`$EVID/a1` already
exists from Shared Setup Step 1 — no fallback/double-create needed.)

- [ ] **Step 2: Trigger `@codex review` (bare comment)**

```bash
A1_AFTER=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh pr comment "$A1_PR" --repo "$OWNER/$REPO" --body "@codex review"
```
Expected: comment posted, exit 0. Capture `$A1_AFTER` *before* posting so a
fast eyes-reaction landing between the comment and the poll-start call below
isn't missed.

- [ ] **Step 3: Wait for the start signal, then completion, via the real poll helpers**

```bash
"$WFPC_DIR/poll-copilot-rereview-start.sh" \
  --owner "$OWNER" --repo "$REPO" --pr "$A1_PR" \
  --after "$A1_AFTER" \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  | tee "$EVID/a1/start-signal.json"

"$WFPC_DIR/poll-copilot-review.sh" \
  --owner "$OWNER" --repo "$REPO" --pr "$A1_PR" \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  | tee "$EVID/a1/completion.json"
```
Expected: `start-signal.json` reports a real `"signal"` (`"event"` or
`"eyes_reaction"`); `completion.json` reports Codex's response landed. These
scripts block for real wall-clock minutes — that's expected, not an error.

- [ ] **Step 4: Capture the raw Codex artifacts as evidence**

```bash
gh api "repos/$OWNER/$REPO/issues/$A1_PR/comments" --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]")]' > "$EVID/a1/issue-comments.json"
gh api "repos/$OWNER/$REPO/issues/$A1_PR/reactions" --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]")]' > "$EVID/a1/reactions.json"
gh api "repos/$OWNER/$REPO/pulls/$A1_PR/reviews" --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]")]' > "$EVID/a1/reviews.json"
cat "$EVID/a1/issue-comments.json" "$EVID/a1/reactions.json" "$EVID/a1/reviews.json"
```
Expected (per the spec's empirical grounding — 8/8 historical PRs matched this): `reactions.json` contains a `+1` from `chatgpt-codex-connector[bot]`, `issue-comments.json` contains the `"Codex Review: Didn't find any major issues"` marker. If `reactions.json` is empty and only the marker comment is present, this falsifies the spec's empirical grounding — stop here, do not proceed to Step 5, and report that specific finding instead (do not loop retrying).

- [ ] **Step 5: Confirm the marker comment is exempted from `untriaged_feedback` AND the reaction drives eligibility**

```bash
"$MERGE_GUARD_DIR/check-merge-eligibility.sh" \
  --owner "$OWNER" --repo "$REPO" --pr "$A1_PR" \
  --policy-json "$(cat "$EVID/policy.json")" \
  > "$EVID/a1/verdict.json" && rc=0 || rc=$?
cat "$EVID/a1/verdict.json"
echo "exit code: $rc"
jq -r '.blockers[]?.code' "$EVID/a1/verdict.json"
jq -r '.facts.bot_clean_review_at_head, .facts.bot_clean_signal_source' "$EVID/a1/verdict.json"
```
Expected: exit code `0`; no `untriaged_feedback` blocker listed (the marker comment must not appear there); `bot_clean_review_at_head == true`; `bot_clean_signal_source == "reaction"`.

- [ ] **Step 6: Merge for real via the `merge-guard` skill (never a bare `gh pr merge`)**

Do **not** hand-roll the merge. This repo has a configured
`[merge-policy.approver]` (a GitHub App attestation, per `project-config.toml`
and `resolve_policy.py`'s output) — a bare `gh pr merge` on a review-required
branch with no approving review is rejected outright. Invoke the
`merge-guard` skill (Skill tool, top-level orchestrator per the constraint
above, not a nested subagent) against PR `$A1_PR`. It will: re-resolve the
policy, re-run `check-merge-eligibility.sh` immediately before merging (the
copy above is for evidence, not for merging off a stale read), apply Axis 2
(`rule-based`/`bot-quiescence` — holds because `bot_clean_review_at_head ==
true`), run `approve_pr.py`'s App attestation if `reviewDecision ==
REVIEW_REQUIRED`, then execute `gh pr merge --squash --match-head-commit`
itself and confirm `state == MERGED` via its own Step 5 contract.

```bash
gh pr view "$A1_PR" --json state,mergedAt --jq '{state, mergedAt}' | tee "$EVID/a1/merge-result.json"
```
Expected: `"state": "MERGED"` with a non-null `mergedAt` — captured *after*
the `merge-guard` skill invocation completes, as the evidence artifact for
this step (the skill call itself is the action; this is the verification).

- [ ] **Step 7: Confirm no stray state**

```bash
gh pr view "$A1_PR" --json headRefName --jq '.headRefName' | xargs -I{} git ls-remote --exit-code origin {}
```
Expected: non-zero exit (branch deleted — GitHub auto-deletes on merge if configured, or delete manually: `git push origin --delete live-verify-a1`). Record the final state (merged, branch gone, `ci` ruleset check green per `gh pr checks $A1_PR`) in `$EVID/a1/result.txt`.

---

## Task 2: Scenario A2a — Genuine findings, normal triage (independent of the ratchet)

**Files:** Create `docs/architecture/live-codex-verification-scratch-a2a.md` (merges to `main`).

- [ ] **Step 1: Branch, deliberately-imperfect scratch doc, PR**

```bash
git checkout main && git pull --ff-only
git checkout -b live-verify-a2a
cat > docs/architecture/live-codex-verification-scratch-a2a.md <<'EOF'
# Live Codex Verification Scratch — A2a

This scrach file exists to give scenario A2a of
docs/specs/2026-07-19-live-codex-verification-design.md a real diff likely
to draw a genuine Codex comment (note the deliberate typo above and the
inconsistent claim below: this file is both temporary and permanent).
It is deleted by that plan's Task 7 cleanup once A1/A2a/A2b have merged.
EOF
git add docs/architecture/live-codex-verification-scratch-a2a.md
git commit -m "test(live-verify): a2a genuine-findings scratch doc"
git push -u origin live-verify-a2a
gh pr create --title "test(live-verify): A2a genuine findings + normal triage" \
  --body "Live codex-awareness verification, scenario A2a. See docs/specs/2026-07-19-live-codex-verification-design.md." \
  --base main --head live-verify-a2a
A2A_PR=$(gh pr view live-verify-a2a --json number --jq .number)
mkdir -p "$EVID/a2a"
echo "A2A_PR=$A2A_PR"
```

- [ ] **Step 2: Trigger `@codex review`, wait, capture the review_summary**

```bash
A2A_AFTER=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh pr comment "$A2A_PR" --repo "$OWNER/$REPO" --body "@codex review"
"$WFPC_DIR/poll-copilot-rereview-start.sh" --owner "$OWNER" --repo "$REPO" --pr "$A2A_PR" \
  --after "$A2A_AFTER" --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  | tee "$EVID/a2a/start-signal.json"
"$WFPC_DIR/poll-copilot-review.sh" --owner "$OWNER" --repo "$REPO" --pr "$A2A_PR" \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' | tee "$EVID/a2a/completion.json"
gh api "repos/$OWNER/$REPO/pulls/$A2A_PR/reviews" --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]")]' > "$EVID/a2a/reviews.json"
cat "$EVID/a2a/reviews.json"
```
Expected: at least one review object with a non-empty `body` (genuine
findings). **Contingency:** if `reviews.json` is empty (Codex came back
clean), this round is inconclusive — push a second, more clearly flawed
edit to the same branch/PR and repeat Step 2 once before treating "Codex
found nothing" as a real result.

- [ ] **Step 3: Confirm the blocker, capture the finding's review_id**

```bash
"$MERGE_GUARD_DIR/check-merge-eligibility.sh" --owner "$OWNER" --repo "$REPO" --pr "$A2A_PR" \
  --policy-json "$(cat "$EVID/policy.json")" > "$EVID/a2a/verdict-before-triage.json" && rc=0 || rc=$?
cat "$EVID/a2a/verdict-before-triage.json"
echo "exit: $rc"
jq -r '.blockers[] | select(.code=="untriaged_feedback")' "$EVID/a2a/verdict-before-triage.json"
REVIEW_ID=$(jq -r '.[0].id' "$EVID/a2a/reviews.json")
echo "REVIEW_ID=$REVIEW_ID"
```
Expected: exit code `1`; `untriaged_feedback` blocker present, naming `$REVIEW_ID`.

- [ ] **Step 4: Run the normal triage/reply/resolve flow, giving the finding a terminal disposition**

Invoke the `wait-for-pr-comments` skill normally against PR `$A2A_PR` (Skill tool, not a hand-rolled script call — this is its designed entry point) and let it classify Codex's finding as FIX or SKIP, post the reply, and resolve the thread through its normal flow. Save its output:

```bash
# after the skill run completes, capture the resulting inventory state
ls -la ~/.claude/state/pr-inventory/ 2>/dev/null | tee "$EVID/a2a/post-triage-inventory-listing.txt"
```

- [ ] **Step 5: Confirm the blocker clears via the terminal-disposition path (the control case)**

```bash
"$MERGE_GUARD_DIR/check-merge-eligibility.sh" --owner "$OWNER" --repo "$REPO" --pr "$A2A_PR" \
  --policy-json "$(cat "$EVID/policy.json")" > "$EVID/a2a/verdict-after-triage.json" && rc=0 || rc=$?
cat "$EVID/a2a/verdict-after-triage.json"
echo "exit: $rc"
jq -r '.blockers[]?.code' "$EVID/a2a/verdict-after-triage.json"
```
Expected: exit code `0`, no blockers. This proves ordinary triage clears the blocker — **this is not ratchet evidence**, it's the control case A2b (Task 3) contrasts against.

- [ ] **Step 6: Merge for real via the `merge-guard` skill (never a bare `gh pr merge` — see Task 1 Step 6 for why)**

Invoke the `merge-guard` skill (top-level orchestrator, not a nested
subagent) against PR `$A2A_PR`, same as Task 1 Step 6.

```bash
gh pr view "$A2A_PR" --json state,mergedAt --jq '{state, mergedAt}' | tee "$EVID/a2a/merge-result.json"
```
Expected: `"state": "MERGED"`.

---

## Task 3: Scenario A2b — The ratchet itself (deterministic, decoupled from A2a)

**Files:** Create `docs/architecture/live-codex-verification-scratch-a2b.md` (merges to `main`). Separate PR from A2a — do not reuse A2a's finding.

- [ ] **Step 1: Branch, scratch doc (deliberately imperfect), PR**

```bash
git checkout main && git pull --ff-only
git checkout -b live-verify-a2b
cat > docs/architecture/live-codex-verification-scratch-a2b.md <<'EOF'
# Live Codex Verification Scratch — A2b

This file's porpose is to give scenario A2b of
docs/specs/2026-07-19-live-codex-verification-design.md a real diff likely
to draw a genuine Codex comment, whose finding is then deliberately left
untriaged to test the review_summary ratchet. Deleted by Task 7 cleanup.
EOF
git add docs/architecture/live-codex-verification-scratch-a2b.md
git commit -m "test(live-verify): a2b ratchet scratch doc"
git push -u origin live-verify-a2b
gh pr create --title "test(live-verify): A2b review_summary ratchet" \
  --body "Live codex-awareness verification, scenario A2b. See docs/specs/2026-07-19-live-codex-verification-design.md." \
  --base main --head live-verify-a2b
A2B_PR=$(gh pr view live-verify-a2b --json number --jq .number)
mkdir -p "$EVID/a2b"
echo "A2B_PR=$A2B_PR"
```

- [ ] **Step 2: Trigger `@codex review`, get a genuine finding, DO NOT triage it**

```bash
A2B_AFTER_R1=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh pr comment "$A2B_PR" --repo "$OWNER/$REPO" --body "@codex review"
"$WFPC_DIR/poll-copilot-rereview-start.sh" --owner "$OWNER" --repo "$REPO" --pr "$A2B_PR" \
  --after "$A2B_AFTER_R1" --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  | tee "$EVID/a2b/start-signal.json"
"$WFPC_DIR/poll-copilot-review.sh" --owner "$OWNER" --repo "$REPO" --pr "$A2B_PR" \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' | tee "$EVID/a2b/completion.json"
gh api "repos/$OWNER/$REPO/pulls/$A2B_PR/reviews" --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]")]' > "$EVID/a2b/reviews-round1.json"
cat "$EVID/a2b/reviews-round1.json"
```
Expected: a review object with findings. **Contingency:** same as A2a Step 2 — if clean, push a more clearly flawed edit and retry once. **Do not** invoke `wait-for-pr-comments`'s triage flow on this PR at all — leaving the finding stale is the point.

```bash
STALE_REVIEW_ID=$(jq -r '.[0].id' "$EVID/a2b/reviews-round1.json")
STALE_SUBMITTED_AT=$(jq -r '.[0].submitted_at' "$EVID/a2b/reviews-round1.json")
echo "STALE_REVIEW_ID=$STALE_REVIEW_ID STALE_SUBMITTED_AT=$STALE_SUBMITTED_AT"
```

- [ ] **Step 3: Push a fix commit, re-ask with the bare comment (no disposition table — abn9.44.4 exclusion), get a clean round via the reaction path specifically**

```bash
# actually remove the round-1 rough edge — "porpose" -> "purpose" — a real
# diff, not an empty commit, so round 2 has genuine grounds to come back clean.
# `sed -i ''` is BSD/macOS syntax (this worktree runs on Darwin); on GNU sed
# drop the empty '' argument.
sed -i '' 's/porpose/purpose/' docs/architecture/live-codex-verification-scratch-a2b.md
git add docs/architecture/live-codex-verification-scratch-a2b.md
git commit -m "fix(live-verify): address a2b round-1 finding"
git push
A2B_AFTER_R2=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh pr comment "$A2B_PR" --repo "$OWNER/$REPO" --body "@codex review"
"$WFPC_DIR/poll-copilot-rereview-start.sh" --owner "$OWNER" --repo "$REPO" --pr "$A2B_PR" \
  --after "$A2B_AFTER_R2" --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  | tee "$EVID/a2b/start-signal-round2.json"
"$WFPC_DIR/poll-copilot-review.sh" --owner "$OWNER" --repo "$REPO" --pr "$A2B_PR" \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' | tee "$EVID/a2b/completion-round2.json"
gh api "repos/$OWNER/$REPO/issues/$A2B_PR/reactions" --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]" and .content=="+1")]' > "$EVID/a2b/reactions-round2.json"
gh api "repos/$OWNER/$REPO/issues/$A2B_PR/reactions" --jq '[.[] | select(.user.login=="chatgpt-codex-connector[bot]" and .content=="eyes")]' > "$EVID/a2b/eyes-round2.json"
cat "$EVID/a2b/reactions-round2.json" "$EVID/a2b/eyes-round2.json"
```
Expected: a `+1` reaction present, `eyes-round2.json` empty (no lingering
`eyes`). If round 2 instead comes back as a clean *review* (no `+1`), the
ratchet cannot be exercised this round per the spec — repeat Step 3's
re-ask once; the ratchet only clears via the reaction path.

- [ ] **Step 4: Assert the ratchet, not the terminal-disposition path, cleared the blocker**

```bash
"$MERGE_GUARD_DIR/check-merge-eligibility.sh" --owner "$OWNER" --repo "$REPO" --pr "$A2B_PR" \
  --policy-json "$(cat "$EVID/policy.json")" > "$EVID/a2b/verdict.json" && rc=0 || rc=$?
cat "$EVID/a2b/verdict.json"
echo "exit: $rc"
jq -r '.facts.bot_clean_signal_source, .facts.bot_clean_review_at_head' "$EVID/a2b/verdict.json"
jq -r '.blockers[]?.code' "$EVID/a2b/verdict.json"
# confirm no terminal disposition was ever recorded for the stale review_id
grep -rl "$STALE_REVIEW_ID" ~/.claude/state/pr-inventory/ 2>/dev/null | tee "$EVID/a2b/inventory-grep-for-stale-review.txt"
REACTION_CREATED_AT=$(jq -r '.[0].created_at' "$EVID/a2b/reactions-round2.json")
echo "STALE_SUBMITTED_AT=$STALE_SUBMITTED_AT REACTION_CREATED_AT=$REACTION_CREATED_AT"
```
Expected: exit code `0`; no `untriaged_feedback` blocker; `bot_clean_signal_source == "reaction"`; the inventory grep finds **nothing** referencing `$STALE_REVIEW_ID` (no terminal disposition was ever recorded — the clearing happened purely via the ratchet's timestamp comparison); `$REACTION_CREATED_AT` is later than `$STALE_SUBMITTED_AT`. This four-part conjunction is the actual falsifiable ratchet claim — record all four values in the final report, not just the exit code.

- [ ] **Step 5: Merge for real via the `merge-guard` skill (never a bare `gh pr merge` — see Task 1 Step 6 for why)**

Invoke the `merge-guard` skill (top-level orchestrator, not a nested
subagent) against PR `$A2B_PR`, same as Task 1 Step 6.

```bash
gh pr view "$A2B_PR" --json state,mergedAt --jq '{state, mergedAt}' | tee "$EVID/a2b/merge-result.json"
```
Expected: `"state": "MERGED"`.

---

## Task 4: Scenario B1 — Human review blocks despite Codex-clean (live author-scoping)

**Constraint (hard rule, not a judgment call): this PR is opened as a draft, `check-merge-eligibility.sh` is invoked directly for its verdict, and `merge-guard`'s merge action is never invoked on it, even if the verdict comes back eligible.**

**Files:** Create `docs/architecture/live-codex-verification-scratch-b1.md` (never merges).

- [ ] **Step 1: Branch, scratch doc, draft PR**

```bash
git checkout main && git pull --ff-only
git checkout -b live-verify-b1
cat > docs/architecture/live-codex-verification-scratch-b1.md <<'EOF'
# Live Codex Verification Scratch — B1 (draft, never merges)

Scenario B1 of docs/specs/2026-07-19-live-codex-verification-design.md:
human-review-blocks-despite-Codex-clean. This PR is a draft and is closed
without merging once evidence is captured.
EOF
git add docs/architecture/live-codex-verification-scratch-b1.md
git commit -m "test(live-verify): b1 author-scoping scratch doc"
git push -u origin live-verify-b1
gh pr create --draft --title "test(live-verify): B1 author-scoping (draft, will not merge)" \
  --body "Live codex-awareness verification, scenario B1. Draft, never merges. See docs/specs/2026-07-19-live-codex-verification-design.md." \
  --base main --head live-verify-b1
B1_PR=$(gh pr view live-verify-b1 --json number --jq .number)
mkdir -p "$EVID/b1"
echo "B1_PR=$B1_PR"
```

- [ ] **Step 2: Trigger `@codex review`, wait for a clean reaction**

```bash
B1_AFTER=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh pr comment "$B1_PR" --repo "$OWNER/$REPO" --body "@codex review"
"$WFPC_DIR/poll-copilot-rereview-start.sh" --owner "$OWNER" --repo "$REPO" --pr "$B1_PR" \
  --after "$B1_AFTER" --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  | tee "$EVID/b1/start-signal.json"
"$WFPC_DIR/poll-copilot-review.sh" --owner "$OWNER" --repo "$REPO" --pr "$B1_PR" \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' | tee "$EVID/b1/completion.json"
```

- [ ] **Step 3: Leave a real human COMMENTED review with a findings body (not "Request changes")**

```bash
gh pr review "$B1_PR" --comment --body "Consider tightening the wording in the scratch doc's second sentence." 
gh api "repos/$OWNER/$REPO/pulls/$B1_PR/reviews" --jq '[.[] | select(.state=="COMMENTED" and (.body // "") != "")]' > "$EVID/b1/human-reviews.json"
HUMAN_REVIEW_ID=$(jq -r '[.[] | select(.user.login != "chatgpt-codex-connector[bot]")][0].id' "$EVID/b1/human-reviews.json")
echo "HUMAN_REVIEW_ID=$HUMAN_REVIEW_ID"
```
Expected: `gh pr review --comment` (not `--request-changes`) so this doesn't
trip the separate `requested_changes_active` blocker.

- [ ] **Step 4: Assert author-scoping — the human's finding blocks despite Codex's clean reaction**

```bash
"$MERGE_GUARD_DIR/check-merge-eligibility.sh" --owner "$OWNER" --repo "$REPO" --pr "$B1_PR" \
  --policy-json "$(cat "$EVID/policy.json")" > "$EVID/b1/verdict.json" && rc=0 || rc=$?
cat "$EVID/b1/verdict.json"
echo "exit: $rc"
jq -r '.blockers[] | select(.code=="untriaged_feedback")' "$EVID/b1/verdict.json"
jq -r '.facts.bot_clean_review_at_head, .facts.bot_clean_signal_source' "$EVID/b1/verdict.json"
```
Expected: exit code `1`; `untriaged_feedback` blocker naming `$HUMAN_REVIEW_ID` specifically; `bot_clean_review_at_head == true` and `bot_clean_signal_source == "reaction"` at the same time (`reaction_clean` is an internal shell variable in `check-merge-eligibility.sh`, never emitted in the verdict JSON — these two facts are the ones that actually carry "Codex's clean signal arrived via the reaction path") — proving Codex's clean signal never clears a different identity's finding.

- [ ] **Step 5: Close the PR — never merge**

No dismissal call: GitHub's review-dismissal endpoint only applies to
`APPROVED`/`CHANGES_REQUESTED` reviews, and Step 3 deliberately used
`--comment` (`COMMENTED` state, per the spec, to avoid the separate
`requested_changes_active` blocker) — a `COMMENTED` review has no
dismissable state, so a dismissal call would just 422. Closing the PR is
sufficient.

```bash
gh pr close "$B1_PR" --delete-branch
gh pr view "$B1_PR" --json state --jq '.state'
```
Expected: `"state": "CLOSED"`, branch deleted. **Never run `gh pr merge` on this PR.**

---

## Task 5: Scenario B2 — Trigger-comment exemption

**Constraint (hard rule): draft PR, eligibility-checked directly, never merge-guard-merged.**

**Files:** Create `docs/architecture/live-codex-verification-scratch-b2.md` (never merges).

- [ ] **Step 1: Branch, scratch doc, draft PR, trigger comment**

```bash
git checkout main && git pull --ff-only
git checkout -b live-verify-b2
cat > docs/architecture/live-codex-verification-scratch-b2.md <<'EOF'
# Live Codex Verification Scratch — B2 (draft, never merges)

Scenario B2: trigger-comment exemption. Confirms the bare "@codex review"
ask comment is never itself counted as blocking feedback.
EOF
git add docs/architecture/live-codex-verification-scratch-b2.md
git commit -m "test(live-verify): b2 trigger-comment scratch doc"
git push -u origin live-verify-b2
gh pr create --draft --title "test(live-verify): B2 trigger-comment exemption (draft, will not merge)" \
  --body "Live codex-awareness verification, scenario B2. Draft, never merges." \
  --base main --head live-verify-b2
B2_PR=$(gh pr view live-verify-b2 --json number --jq .number)
mkdir -p "$EVID/b2"
B2_AFTER=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh pr comment "$B2_PR" --repo "$OWNER/$REPO" --body "@codex review"
TRIGGER_COMMENT_ID=$(gh api "repos/$OWNER/$REPO/issues/$B2_PR/comments" --jq '[.[] | select(.body=="@codex review")][-1].id')
echo "B2_PR=$B2_PR TRIGGER_COMMENT_ID=$TRIGGER_COMMENT_ID"
```

- [ ] **Step 2: Wait for Codex, then assert the trigger comment itself never appears as an untriaged_feedback blocker**

```bash
"$WFPC_DIR/poll-copilot-rereview-start.sh" --owner "$OWNER" --repo "$REPO" --pr "$B2_PR" \
  --after "$B2_AFTER" --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  | tee "$EVID/b2/start-signal.json"
"$WFPC_DIR/poll-copilot-review.sh" --owner "$OWNER" --repo "$REPO" --pr "$B2_PR" \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' | tee "$EVID/b2/completion.json"
"$MERGE_GUARD_DIR/check-merge-eligibility.sh" --owner "$OWNER" --repo "$REPO" --pr "$B2_PR" \
  --policy-json "$(cat "$EVID/policy.json")" > "$EVID/b2/verdict.json" && rc=0 || rc=$?
cat "$EVID/b2/verdict.json"
echo "exit: $rc"
HAS_UNTRIAGED=$(jq '[.blockers[]? | select(.code=="untriaged_feedback")] | length > 0' "$EVID/b2/verdict.json")
NAMES_TRIGGER=$(jq -r --arg cid "$TRIGGER_COMMENT_ID" \
  '[.blockers[]? | select(.code=="untriaged_feedback") | .details | select(test("#" + $cid + "\\b"))] | length > 0' \
  "$EVID/b2/verdict.json")
echo "HAS_UNTRIAGED=$HAS_UNTRIAGED NAMES_TRIGGER=$NAMES_TRIGGER"
```
Expected: exit code `0` (clean pass expected on trivial content);
`NAMES_TRIGGER == false` regardless of `HAS_UNTRIAGED` — the trigger
comment must never appear in the `untriaged_feedback` details, whether or
not some other blocker exists. (`.details` is a string like `"untriaged
non-thread feedback ...: issue_comment #<id> by <author>"`, not an array —
match it with `test()`, not `contains([...])`, which type-errors against a
string.)

Caveat for the report: because the trigger comment here is authored by the
same identity running this test (PR author or the authenticated session),
`is_trigger_comment`'s exemption fires and the comment simply never gets
enumerated as a candidate blocker in the first place — `NAMES_TRIGGER ==
false` holds either way, so this scenario is spec-faithful but a
comparatively weak falsification test. Note this distinction in Task 8's
report rather than presenting it as an unqualified pass.

- [ ] **Step 3: Close without merging**

```bash
gh pr close "$B2_PR" --delete-branch
gh pr view "$B2_PR" --json state --jq '.state'
```
Expected: `"state": "CLOSED"`. **Never run `gh pr merge` on this PR.**

---

## Task 6: Scenario B3 — Codex-only start handshake

**Constraint (hard rule): draft PR, eligibility-checked directly, never merge-guard-merged.**

**Files:** Create `docs/architecture/live-codex-verification-scratch-b3.md` (never merges).

- [ ] **Step 1: Branch, scratch doc, draft PR**

```bash
git checkout main && git pull --ff-only
git checkout -b live-verify-b3
cat > docs/architecture/live-codex-verification-scratch-b3.md <<'EOF'
# Live Codex Verification Scratch — B3 (draft, never merges)

Scenario B3: Codex-only start handshake. Confirms poll-copilot-rereview-start.sh's
eyes-reaction path unblocks Phase 6 when only Codex (no Copilot) is
requested — the exact live case the #317->#337 defect broke.
EOF
git add docs/architecture/live-codex-verification-scratch-b3.md
git commit -m "test(live-verify): b3 codex-only handshake scratch doc"
git push -u origin live-verify-b3
gh pr create --draft --title "test(live-verify): B3 Codex-only start handshake (draft, will not merge)" \
  --body "Live codex-awareness verification, scenario B3. Draft, never merges." \
  --base main --head live-verify-b3
B3_PR=$(gh pr view live-verify-b3 --json number --jq .number)
mkdir -p "$EVID/b3"
echo "B3_PR=$B3_PR"
```

- [ ] **Step 2: Request re-review with a Codex-only allowlist (no Copilot identity), assert the eyes-reaction path fires**

```bash
B3_AFTER=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh pr comment "$B3_PR" --repo "$OWNER/$REPO" --body "@codex review"
"$WFPC_DIR/poll-copilot-rereview-start.sh" --owner "$OWNER" --repo "$REPO" --pr "$B3_PR" \
  --after "$B3_AFTER" \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  | tee "$EVID/b3/start-signal.json"
jq -r '.signal' "$EVID/b3/start-signal.json"
```
Expected: exit code `0`; `.signal == "eyes_reaction"` — this Codex-only
allowlist forces `HAS_COPILOT_CAPABLE_BOT=false` inside the script, so the
start signal can only come from the eyes-reaction path, never the
`copilot_work_started` event path. This is the exact assertion that
falsifies a regression of the #317->#337 fix.

- [ ] **Step 3: Close without merging**

```bash
"$WFPC_DIR/poll-copilot-review.sh" --owner "$OWNER" --repo "$REPO" --pr "$B3_PR" \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' | tee "$EVID/b3/completion.json"
gh pr close "$B3_PR" --delete-branch
gh pr view "$B3_PR" --json state --jq '.state'
```
Expected: `"state": "CLOSED"`. **Never run `gh pr merge` on this PR.**

---

## Task 7: Cleanup

**Files:** Delete the three scratch docs that landed on `main`.

- [ ] **Step 1: Remove the merged scratch docs via a small PR (expected path — this repo's ruleset requires an approving review, so a direct push to `main` will almost certainly be rejected)**

```bash
cd /Users/scott/src/projects/agents-config/.claude/worktrees/live-codex-verification
git checkout main && git pull --ff-only
git checkout -b live-verify-cleanup
git rm docs/architecture/live-codex-verification-scratch-a1.md \
       docs/architecture/live-codex-verification-scratch-a2a.md \
       docs/architecture/live-codex-verification-scratch-a2b.md
git commit -m "chore(live-verify): remove scratch docs from A1/A2a/A2b"
git push -u origin live-verify-cleanup
gh pr create --title "chore(live-verify): remove scratch docs" \
  --body "Housekeeping — removes the three scratch docs A1/A2a/A2b left on main. See docs/specs/2026-07-19-live-codex-verification-design.md Cleanup section." \
  --base main --head live-verify-cleanup
```
Trigger `@codex review`, wait, then merge this PR via the same `merge-guard`
skill delegation as Task 1/2/3 Step 6 (top-level orchestrator, not a nested
subagent) — it's a real PR like the others, not a special case.

If the App-approver key is unavailable (per Shared Setup Step 3) and this
PR needs a human merge instead, that's the same expected degradation noted
there — not a bug in this step. A direct `git push origin main` bypassing
the PR flow is the unlikely branch and should only be attempted if the
repo's ruleset is confirmed to allow it (it doesn't, per this repo's
configured `[merge-policy.approver]`).

- [ ] **Step 2: Confirm all six scenario branches are gone**

```bash
for b in live-verify-a1 live-verify-a2a live-verify-a2b live-verify-b1 live-verify-b2 live-verify-b3; do
  git ls-remote --exit-code origin "$b" && echo "STILL PRESENT: $b" || echo "gone: $b"
done
```
Expected: `gone:` for all six.

---

## Task 8: Final report

**Files:** `/tmp/live-codex-verification-evidence/report.md` (local deliverable, not committed).

- [ ] **Step 1: Assemble the report from captured evidence**

Write `/tmp/live-codex-verification-evidence/report.md` with one section per
scenario (A1, A2a, A2b, B1, B2, B3): expected vs. observed, pass/fail, and
the specific evidence file(s) from `$EVID/<scenario>/` that back the claim
— per the spec's Reporting section, A2b's section must cite the four-part
conjunction from Task 3 Step 4 (signal source, no blocker, no stale-review
inventory hit, timestamp ordering), not just the final exit code.

- [ ] **Step 2: Hand the report to the user**

Send `/tmp/live-codex-verification-evidence/report.md` as a deliverable file.

---

## Self-Review

**Spec coverage:** A1 (Task 1), A2a (Task 2), A2b (Task 3), B1 (Task 4), B2
(Task 5), B3 (Task 6), Cleanup (Task 7), Reporting (Task 8) — every scenario
and section in the spec has a task. The two carved-out bugs (abn9.44.3,
abn9.44.4) are not tasks here; they're separately tracked and this plan's
tasks route around them (A2b's re-ask stays bare-comment; no task asserts
CI-red blocking).

**Placeholder scan:** every step has a real command or a real `gh
pr review`/`gh api` call; no "TBD"/"handle appropriately" strings.

**Type/name consistency:** `$OWNER`, `$REPO`, `$MERGE_GUARD_DIR`, `$WFPC_DIR`,
`$EVID` are set once in Shared Setup and used identically in every later
task; `--policy-json "$(cat "$EVID/policy.json")"` and the
`--bot-reviewers '["chatgpt-codex-connector[bot]"]'` flag are used
consistently across all six scenarios (B3 only, per the spec, deliberately
excludes Copilot from that array); all six eligibility checks use the
`> file && rc=0 || rc=$?` capture, including the two scenarios that expect a
non-zero exit (A2a Step 3, B1 Step 4).

**Revision note (ralf-review cycle 2, PASS_WITH_RESERVATIONS):** fixed a
wrong fact name in Task 4/B1 (`.facts.reaction_clean` doesn't exist —
replaced with `.facts.bot_clean_review_at_head` + `.facts.bot_clean_signal_source`),
added a Shared-Setup precondition check for the App-approver key (Plan A's
merge claim is inconclusive, not failed, if it's absent), reordered Task 7's
cleanup to lead with a PR (a direct push to `main` will almost certainly be
rejected by this repo's ruleset), and folded in the platform/caveat/version
minors. This is the plan's final recorded verdict — not re-earned by a third
cycle.

## Review routing

**Routing criteria check:** the plan deviates from the spec? No — it executes A1/A2a/A2b/B1/B2/B3 exactly as specced, including the hard Plan-B no-merge rule. Scope discovered during planning the spec doesn't cover? No. Irreversible/migration steps? Yes — real PRs merge to `main` and a real cleanup commit removes files from `main`; this is genuinely hard to fully undo (though revertable). Large/subtle task-graph ordering? No — six independent scenarios, no cross-task ordering constraints beyond within-scenario steps.

**Review routing: deep (criteria: irreversible operations — real merges to `main` under standing autonomous-merge authority)**


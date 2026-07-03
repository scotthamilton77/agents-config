# merge-guard bot-quiescence retry + scoped force-merge — Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a `rule-based` / `bot-quiescence` repo a recovery path when the trusted bot never re-reviews a fix head — a bounded one-ask auto-retry backstop, and an opt-in human-authorized scoped force-merge after the ask is exhausted — without ever converting bot silence into implicit approval.

**Architecture:** Deterministic logic lives in code (a resolver key + a new counter helper + an eligibility fact read, all unit-tested); the safety-critical authorization decisions live in the `merge-guard` skill prose (Step 4 / Step 5 / Decision Matrix / Red Flags). One new boolean fact `bot_review_cap_exhausted` gates everything; it is set by a silent-ask counter (`rereview_round_count`, cap 1) or the existing chatty `round >= 6` cap, read head-exact and fail-closed. Force-merge uses its own terminal merge and never chains into Step 5's blanket `--admin` bypass.

**Tech Stack:** Python 3.11 stdlib (`resolve_policy.py`, `unittest` via CLI subprocess), Bash + `jq` (skill helpers + hand-rolled `assert()` smoke tests), Markdown skill files.

**Source spec:** `docs/specs/2026-07-03-merge-guard-bot-quiescence-retry.md` (committed on this branch). Where a task says "verbatim from the spec § X", the spec section is the authoritative replacement text — copy it exactly.

**Running tests:** These skill tests are **not** in GitHub CI (`make ci` covers only `packages/`). They run via `project-config.toml`'s `[gates].test` sweep or directly. Per-file: `bash <path>_test.sh`. Python suite: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh` (shim) or `python3 …/resolve_policy_test.py -v`. Full sweep:
```bash
find src/user/.agents/skills src/user/.claude/hooks -name '*_test.sh' -print0 | sort -z | \
  xargs -0 -I{} sh -c 'echo "[TEST] $1"; bash "$1" || exit 1' _ {}
```

**Coordination (not a blocker) — agents-config-xvmf8:** touches the same `resolve_policy.py` `MERGE_POLICY_KEYS` set and `merge-guard/SKILL.md` Step-4 rule table via the `agent-ruling` rule. Expect a **textual** merge conflict on those two spots (adjacent set members / table rows), never semantic. Resolve by keeping both. Rebase against whichever lands first.

**File structure:**

| File | Responsibility | Task |
|---|---|---|
| `src/user/.agents/skills/merge-guard/resolve_policy.py` | Add `allow-force-after-bot-timeout` config key (dataclass field, default, validate coupling) | 1 |
| `src/user/.agents/skills/merge-guard/resolve_policy_test.py` | CLI tests for the new key | 1 |
| `src/user/.agents/skills/wait-for-pr-comments/compute-rereview-polling.sh` | **NEW** pure helper: silent-ask counter arithmetic → `{rereview_round_count, bot_review_cap_exhausted}` | 2 |
| `src/user/.agents/skills/wait-for-pr-comments/compute-rereview-polling_test.sh` | **NEW** unit tests for the helper | 2 |
| `src/user/.agents/skills/merge-guard/check-merge-eligibility.sh` | Add `facts.bot_review_cap_exhausted` head-exact, fail-closed read | 3 |
| `src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh` | Tests incl. stale-head guard | 3 |
| `src/user/.agents/skills/wait-for-pr-comments/build-inventory-body_test.sh`, `validate-inventory_test.sh` | Regression: new `polling` fields pass through at v1 | 4 |
| `src/user/.agents/skills/wait-for-pr-comments/SKILL.md` | Phase 6 wiring (seed → helper → POLLING_FILE), schema doc, PushNotification | 5 |
| `src/user/.agents/skills/merge-guard/SKILL.md` | Step 4 branch, Step 5 `--admin` guard, Decision Matrix, Red Flags | 6 |
| `docs/architecture/review-merge-policy/design.md` | Bot-quiescence lifecycle amendment | 7 |

---

## Task 1: `resolve_policy.py` — `allow-force-after-bot-timeout` config key

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/resolve_policy.py` (dataclass ~41-51, `DEFAULTS` ~54-62, `MERGE_POLICY_KEYS` line 71, `resolve_policy()` construction ~188-196, `validate()` after line 165)
- Test: `src/user/.agents/skills/merge-guard/resolve_policy_test.py`

Tests mirror the existing subprocess/CLI style (`unittest`, assert exit code + stderr substring; `asdict` auto-serializes the new field to stdout for the accept/default cases).

- [ ] **Step 1: Write the failing tests**

Append to `resolve_policy_test.py` (inside the same `TestCase` class that holds `test_bot_quiescence_requires_trusted_bot`; use the existing `self._resolve` helper and `json` — already imported by the harness for stdout parsing, else add `import json` at top):

```python
def test_allow_force_after_bot_timeout_ok_with_bot_quiescence(self):
    code, out, _ = self._resolve(
        '[review-expectations]\nbot-review-expected = true\nbot-reviewers = ["Copilot"]\n'
        '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "bot-quiescence"\n'
        'allow-force-after-bot-timeout = true\n')
    self.assertEqual(code, 0)
    self.assertTrue(json.loads(out)["allow_force_after_bot_timeout"])

def test_allow_force_after_bot_timeout_default_false(self):
    code, out, _ = self._resolve(
        '[review-expectations]\nbot-review-expected = true\nbot-reviewers = ["Copilot"]\n'
        '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "bot-quiescence"\n')
    self.assertEqual(code, 0)
    self.assertFalse(json.loads(out)["allow_force_after_bot_timeout"])

def test_allow_force_after_bot_timeout_rejected_with_human_approvals(self):
    code, _, err = self._resolve(
        '[review-expectations]\nhuman-approvers-required = 1\n'
        '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "human-approvals"\n'
        'allow-force-after-bot-timeout = true\n')
    self.assertEqual(code, 1)
    self.assertIn("allow-force-after-bot-timeout", err)

def test_allow_force_after_bot_timeout_rejected_under_explicit(self):
    code, _, err = self._resolve(
        '[merge-policy]\nmerge-authorization = "explicit"\n'
        'allow-force-after-bot-timeout = true\n')
    self.assertEqual(code, 1)
    self.assertIn("allow-force-after-bot-timeout", err)

def test_allow_force_after_bot_timeout_type_mismatch(self):
    code, _, err = self._resolve(
        '[review-expectations]\nbot-review-expected = true\nbot-reviewers = ["Copilot"]\n'
        '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "bot-quiescence"\n'
        'allow-force-after-bot-timeout = "yes"\n')
    self.assertEqual(code, 1)
    self.assertIn("boolean", err)
```

> Note: confirm the `_resolve` helper returns `(code, stdout, stderr)`. The research excerpt shows `code, _, err = self._resolve(...)`, so it returns a 3-tuple `(code, out, err)`. If your local copy returns 2 values, adjust the unpacking.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 src/user/.agents/skills/merge-guard/resolve_policy_test.py -v 2>&1 | grep allow_force`
Expected: the 5 new tests FAIL — `test_..._ok...` fails on `KeyError: 'allow_force_after_bot_timeout'` (field not serialized) and the `_rejected_` tests fail because no `PolicyError` is raised yet (exit 0, `[merge-policy]: unknown key(s) allow-force-after-bot-timeout` may appear from `_check_keys` — that is a DIFFERENT rejection than the coupling we want, so the substring `allow-force-after-bot-timeout` might coincidentally match; treat the tests as authoritative only after Step 3 adds the key to `MERGE_POLICY_KEYS`).

- [ ] **Step 3: Implement**

In `resolve_policy.py`:

1. `MERGE_POLICY_KEYS` (line 71):
```python
MERGE_POLICY_KEYS = {"merge-authorization", "merge-rule", "allow-force-after-bot-timeout"}
```

2. `ReviewMergePolicy` dataclass — add after `merge_rule` (line 51):
```python
    merge_rule: str | None    # "bot-quiescence" | "human-approvals" | "agent-ruling"
    allow_force_after_bot_timeout: bool  # opt-in escape hatch, bot-quiescence only
```

3. `DEFAULTS` (after line 61 `merge_rule=None,`):
```python
    merge_rule=None,
    allow_force_after_bot_timeout=False,
```

4. `resolve_policy()` construction (after line 195 `merge_rule=...`):
```python
        merge_rule=_typed(merge, "merge-rule", str, DEFAULTS.merge_rule),
        allow_force_after_bot_timeout=_typed(
            merge, "allow-force-after-bot-timeout", bool,
            DEFAULTS.allow_force_after_bot_timeout),
```

5. `validate()` — add after the bot-quiescence block (after line 165):
```python
    if policy.allow_force_after_bot_timeout and policy.merge_rule != "bot-quiescence":
        raise PolicyError(
            "allow-force-after-bot-timeout is only valid with merge-rule=bot-quiescence")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 src/user/.agents/skills/merge-guard/resolve_policy_test.py -v`
Expected: `OK`, all tests pass (original 28 + 5 new = 33).

- [ ] **Step 5: Run the shim (what the gate discovers) and commit**

Run: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh`
Expected: `OK`, exit 0.
```bash
git add src/user/.agents/skills/merge-guard/resolve_policy.py src/user/.agents/skills/merge-guard/resolve_policy_test.py
git commit -m "feat(merge-guard): add allow-force-after-bot-timeout policy key (9njsd)"
```

---

## Task 2: `compute-rereview-polling.sh` — silent-ask counter helper (NEW)

**Files:**
- Create: `src/user/.agents/skills/wait-for-pr-comments/compute-rereview-polling.sh`
- Test: `src/user/.agents/skills/wait-for-pr-comments/compute-rereview-polling_test.sh`

**Why a new helper (deviation from the spec's "helpers need no change"):** research confirmed `POLLING_FILE` is assembled ad-hoc in LLM prose — there is no codified construction site. Per the repo's L0 "Code over Prose" law, the silent-ask arithmetic (seed → increment-on-silent → cap → monotonic-exhausted) is extracted into this pure, unit-tested helper rather than left in prose. It computes only the two new fields; the Phase-6 orchestrator (Task 5) merges its output into `POLLING_FILE`.

Contract:
- Inputs: `--prior-count <int>` (default 0), `--prior-exhausted <true|false>` (default false), `--event <silent|chatty-cap|none>` (required), `--silent-cap <int>` (default 1).
- Output (stdout): `{"rereview_round_count": <int>, "bot_review_cap_exhausted": <bool>}`.
- Logic: `new_count = prior_count + (event=="silent" ? 1 : 0)`; `exhausted = prior_exhausted OR (new_count >= silent_cap) OR (event=="chatty-cap")`.
- Exit: 0 success; 2 bad usage (unknown flag, missing `--event`, non-integer count/cap).

- [ ] **Step 1: Write the failing tests**

Create `compute-rereview-polling_test.sh` (mirror the hand-rolled `assert()` style used across the skill's `*_test.sh`):

```bash
#!/usr/bin/env bash
set -uo pipefail
SCRIPT="$(cd "$(dirname "$0")" && pwd)/compute-rereview-polling.sh"
FAIL=0
assert() { if eval "$2"; then echo "  ok: $1"; else echo "  FAIL: $1"; FAIL=1; fi; }

# first silent ask on a fresh head exhausts at cap 1
out=$("$SCRIPT" --prior-count 0 --prior-exhausted false --event silent)
assert "silent from 0 → count 1" "[ \"\$(jq '.rereview_round_count' <<<\"\$out\")\" = 1 ]"
assert "silent from 0 → exhausted true" "[ \"\$(jq '.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"

# a non-silent (arriving) cycle does not advance the silent count or exhaust
out=$("$SCRIPT" --prior-count 0 --prior-exhausted false --event none)
assert "none from 0 → count 0" "[ \"\$(jq '.rereview_round_count' <<<\"\$out\")\" = 0 ]"
assert "none from 0 → exhausted false" "[ \"\$(jq '.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"

# chatty cap exhausts without touching the silent count
out=$("$SCRIPT" --prior-count 0 --prior-exhausted false --event chatty-cap)
assert "chatty-cap → count 0" "[ \"\$(jq '.rereview_round_count' <<<\"\$out\")\" = 0 ]"
assert "chatty-cap → exhausted true" "[ \"\$(jq '.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"

# exhausted is monotonic on the same head
out=$("$SCRIPT" --prior-count 1 --prior-exhausted true --event none)
assert "prior-exhausted stays true" "[ \"\$(jq '.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"

# a higher explicit cap does not exhaust on the first silent ask
out=$("$SCRIPT" --prior-count 0 --prior-exhausted false --event silent --silent-cap 2)
assert "silent from 0, cap 2 → count 1" "[ \"\$(jq '.rereview_round_count' <<<\"\$out\")\" = 1 ]"
assert "silent from 0, cap 2 → not exhausted" "[ \"\$(jq '.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"

# bad usage
"$SCRIPT" --prior-count 0 >/dev/null 2>&1; assert "missing --event → exit 2" "[ \$? -eq 2 ]"
"$SCRIPT" --event silent --prior-count x >/dev/null 2>&1; assert "non-int count → exit 2" "[ \$? -eq 2 ]"

exit $FAIL
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash src/user/.agents/skills/wait-for-pr-comments/compute-rereview-polling_test.sh`
Expected: fails — script does not exist (`No such file or directory`), all asserts FAIL.

- [ ] **Step 3: Implement the helper**

Create `compute-rereview-polling.sh`:

```bash
#!/usr/bin/env bash
# Purpose: compute the two new inventory polling fields for the bot-quiescence
# re-review budget. Pure arithmetic — no file/network I/O; the caller reads
# prior values from the head-exact inventory and merges this output into
# POLLING_FILE.
#
# Inputs:
#   --prior-count <int>        prior rereview_round_count for THIS head (default 0)
#   --prior-exhausted <bool>   prior bot_review_cap_exhausted for THIS head (default false)
#   --event <silent|chatty-cap|none>   the cycle outcome being recorded (required)
#   --silent-cap <int>         silent-ask cap (default 1)
# Output (stdout): {"rereview_round_count": <int>, "bot_review_cap_exhausted": <bool>}
# Exit: 0 ok; 2 bad usage.
set -euo pipefail

prior_count=0
prior_exhausted=false
event=""
silent_cap=1

usage() { echo "usage: $(basename "$0") --event <silent|chatty-cap|none> [--prior-count N] [--prior-exhausted true|false] [--silent-cap N]" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --prior-count)     prior_count="${2:-}"; shift 2 ;;
    --prior-exhausted) prior_exhausted="${2:-}"; shift 2 ;;
    --event)           event="${2:-}"; shift 2 ;;
    --silent-cap)      silent_cap="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ "$event" =~ ^(silent|chatty-cap|none)$ ]] || usage
[[ "$prior_count" =~ ^[0-9]+$ ]] || usage
[[ "$silent_cap" =~ ^[0-9]+$ ]] || usage
[[ "$prior_exhausted" =~ ^(true|false)$ ]] || usage

new_count=$prior_count
[ "$event" = "silent" ] && new_count=$((prior_count + 1))

exhausted=$prior_exhausted
if [ "$exhausted" != "true" ]; then
  if [ "$new_count" -ge "$silent_cap" ] && [ "$event" = "silent" ]; then exhausted=true; fi
  if [ "$event" = "chatty-cap" ]; then exhausted=true; fi
fi

jq -nc --argjson c "$new_count" --argjson e "$exhausted" \
  '{rereview_round_count: $c, bot_review_cap_exhausted: $e}'
```

> Guard detail: `new_count >= silent_cap` is only allowed to exhaust when `event == silent`, so a `--prior-count` already at/above the cap paired with `event=none` does not spuriously flip exhausted (only the chatty-cap or prior-exhausted paths do). This keeps the silent trigger strictly tied to an actual silent ask.

- [ ] **Step 4: Run to verify it passes**

Run: `bash src/user/.agents/skills/wait-for-pr-comments/compute-rereview-polling_test.sh`
Expected: all `  ok:` lines, exit 0.

- [ ] **Step 5: Make executable and commit**

```bash
chmod +x src/user/.agents/skills/wait-for-pr-comments/compute-rereview-polling.sh
git add src/user/.agents/skills/wait-for-pr-comments/compute-rereview-polling.sh src/user/.agents/skills/wait-for-pr-comments/compute-rereview-polling_test.sh
git commit -m "feat(wait-for-pr-comments): add compute-rereview-polling counter helper (9njsd)"
```

---

## Task 3: `check-merge-eligibility.sh` — `facts.bot_review_cap_exhausted` head-exact read

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/check-merge-eligibility.sh` (add a fact after the `review_wait` `set_fact` at `:385`; read the single head-exact inventory, NOT the glob-all used by the untriaged scan at `:413-414`)
- Test: `src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh` (uses `$FAKE_HOME/.claude/state/pr-inventory`, `write_inv()`, `$HEAD_SHA`, `run_script`, `assert`)

- [ ] **Step 1: Write the failing tests**

Append a new test block to `check-merge-eligibility_test.sh` (reuse the harness's existing `write_inv`, `run_script`, `$HEAD_SHA`, `BASE_POLICY`, `assert`; owner/repo/pr are `o`/`r`/`1`):

```bash
# ── bot_review_cap_exhausted: head-exact, fail-closed ────────────────────────
# present-true on the current head
write_inv "o-r-1-${HEAD_SHA}.json" '{"schema_version":1,"pr":{},"polling":{"bot_review_cap_exhausted":true},"items":[]}'
out=$(run_script "$BASE_POLICY")
assert "cap exhausted true on current head → fact true" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"
rm -f "$FAKE_HOME/.claude/state/pr-inventory/o-r-1-${HEAD_SHA}.json"

# present-false
write_inv "o-r-1-${HEAD_SHA}.json" '{"schema_version":1,"pr":{},"polling":{"bot_review_cap_exhausted":false},"items":[]}'
out=$(run_script "$BASE_POLICY")
assert "cap exhausted false → fact false" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"
rm -f "$FAKE_HOME/.claude/state/pr-inventory/o-r-1-${HEAD_SHA}.json"

# field absent → false
write_inv "o-r-1-${HEAD_SHA}.json" '{"schema_version":1,"pr":{},"polling":{"copilot_status":"timeout"},"items":[]}'
out=$(run_script "$BASE_POLICY")
assert "field absent → fact false" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"
rm -f "$FAKE_HOME/.claude/state/pr-inventory/o-r-1-${HEAD_SHA}.json"

# inventory absent → false
out=$(run_script "$BASE_POLICY")
assert "inventory absent → fact false" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"

# malformed current-head inventory → false (fail-closed)
printf 'not json' > "$FAKE_HOME/.claude/state/pr-inventory/o-r-1-${HEAD_SHA}.json"
out=$(run_script "$BASE_POLICY")
assert "malformed current-head inventory → fact false" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"
rm -f "$FAKE_HOME/.claude/state/pr-inventory/o-r-1-${HEAD_SHA}.json"

# STALE-HEAD GUARD: a prior-head inventory with exhausted=true must NOT leak
# onto the current head when the current-head inventory is absent.
write_inv "o-r-1-deadbeefstalehead.json" '{"schema_version":1,"pr":{},"polling":{"bot_review_cap_exhausted":true},"items":[]}'
out=$(run_script "$BASE_POLICY")
assert "stale prior-head exhausted does NOT leak → fact false" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"
rm -f "$FAKE_HOME/.claude/state/pr-inventory/o-r-1-deadbeefstalehead.json"
```

> `write_inv` writes literal content into `$INV_DIR/$1`. If the harness's `write_inv` uses `jq -n` templating rather than raw content, write the malformed-case file directly with `printf` (as shown) instead of via `write_inv`.

- [ ] **Step 2: Run to verify it fails**

Run: `bash src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh 2>&1 | grep -i cap`
Expected: FAILs — `.facts.bot_review_cap_exhausted` is `null` (fact not emitted yet), so every equality assert fails.

- [ ] **Step 3: Implement the head-exact fail-closed read**

In `check-merge-eligibility.sh`, immediately after the `set_fact review_wait ...` line (`:385`), add:

```bash
# ── Fact: bot_review_cap_exhausted (head-exact, fail-closed) ─────────────────
# Read ONLY the inventory for the CURRENT head (filename embeds
# head_sha_after_push). Never the glob-all used by the untriaged scan below —
# a stale exhausted=true from a superseded head must not leak onto a fresh
# head. Absent/malformed/missing-field all resolve to false (force-merge stays
# locked unless the one-ask budget is provably spent for THIS head).
cap_inv="${HOME}/.claude/state/pr-inventory/${OWNER}-${REPO}-${PR}-${HEAD_OID}.json"
bot_cap_exhausted=false
if [[ -f "$cap_inv" ]]; then
    bot_cap_exhausted=$(jq -r '.polling.bot_review_cap_exhausted // false' "$cap_inv" 2>/dev/null) || bot_cap_exhausted=false
    [[ "$bot_cap_exhausted" == "true" ]] || bot_cap_exhausted=false
fi
set_fact bot_review_cap_exhausted "$(jq -n --argjson v "$bot_cap_exhausted" '$v')"
```

> `jq -r '… // false'` yields `false` for a missing field; the `2>/dev/null || …=false` and the explicit `!= true → false` normalization cover a malformed file and any non-`true` string. `set_fact` is the harness's existing fact emitter (same one used for `review_wait`).

- [ ] **Step 4: Run to verify it passes**

Run: `bash src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh`
Expected: all `  ok:` lines including the 6 new ones; exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/check-merge-eligibility.sh src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh
git commit -m "feat(merge-guard): emit head-exact bot_review_cap_exhausted fact (9njsd)"
```

---

## Task 4: Inventory pass-through regression — new `polling` fields survive at v1

**Files:**
- Test: `src/user/.agents/skills/wait-for-pr-comments/build-inventory-body_test.sh`, `src/user/.agents/skills/wait-for-pr-comments/validate-inventory_test.sh`

No production change — this locks in the spec's "additive at v1, no bump; helpers unchanged" claim so a future edit can't silently drop the fields or trip a validator.

- [ ] **Step 1: Write the failing/guard tests**

Append to `build-inventory-body_test.sh` (after the existing polling test; reuse its `$TMP`, `$SCRIPT`, `assert`):

```bash
# new bot-quiescence polling fields pass through verbatim at schema v1
POLLING2="$TMP/polling2.json"
ITEMS2="$TMP/items2.json"; PR2="$TMP/pr2.json"
echo '[]' >"$ITEMS2"
echo '{"number":1,"owner":"o","repo":"r","head_sha":"abc"}' >"$PR2"
echo '{"copilot_status":"timeout","rereview_round_count":1,"bot_review_cap_exhausted":true}' >"$POLLING2"
"$SCRIPT" --items "$ITEMS2" --pr "$PR2" --polling "$POLLING2" > "$TMP/out2.json" 2>&1
assert "rereview_round_count passes through" "jq -e '.polling.rereview_round_count == 1' '$TMP/out2.json' >/dev/null 2>&1"
assert "bot_review_cap_exhausted passes through" "jq -e '.polling.bot_review_cap_exhausted == true' '$TMP/out2.json' >/dev/null 2>&1"
assert "schema_version still 1" "jq -e '.schema_version == 1' '$TMP/out2.json' >/dev/null 2>&1"
```

Append to `validate-inventory_test.sh` (reuse its inventory-fixture + `--phase 0`/`--phase 2` pattern):

```bash
# inventory carrying the new polling fields still validates at v1
NEWPOLL="$TMP/newpoll-inv.json"
jq -n '{schema_version:1, pr:{number:1,owner:"o",repo:"r"},
        polling:{copilot_status:"timeout",rereview_round_count:1,bot_review_cap_exhausted:true},
        items:[]}' > "$NEWPOLL"
"$SCRIPT" --phase 0 --inventory "$NEWPOLL" 2>/dev/null
assert "phase 0 accepts new polling fields (exit 0)" "[ \$? -eq 0 ]"
```

- [ ] **Step 2: Run to verify current behavior**

Run: `bash src/user/.agents/skills/wait-for-pr-comments/build-inventory-body_test.sh && bash src/user/.agents/skills/wait-for-pr-comments/validate-inventory_test.sh`
Expected: **PASS already** — build-inventory-body passes `polling` through verbatim (`:55`) and validate-inventory does not strict-check `polling`. If either FAILS, that is a real regression risk the spec assumed away — stop and reconcile before proceeding.

- [ ] **Step 3: Commit**

```bash
git add src/user/.agents/skills/wait-for-pr-comments/build-inventory-body_test.sh src/user/.agents/skills/wait-for-pr-comments/validate-inventory_test.sh
git commit -m "test(wait-for-pr-comments): lock v1 pass-through of new polling fields (9njsd)"
```

---

## Task 5: `wait-for-pr-comments/SKILL.md` — Phase 6 wiring + schema doc

**Files:**
- Modify: `src/user/.agents/skills/wait-for-pr-comments/SKILL.md` — schema block (`:713-768`), Phase 6 (`:400-412`)

Prose skill file; no unit test. The verification step is a targeted read/grep confirming the edits are present and internally consistent.

- [ ] **Step 1: Amend the schema block**

In the `### Schema (schema_version: 1)` block (`:725-727`), extend the `polling` object exactly as the spec's *Inventory schema* section shows:
```jsonc
  "polling": {
    "copilot_status": "review_found" | "timeout" | "not_requested",
    "rereview_round_count": 0,           // silent-ask count on current head, default 0
    "bot_review_cap_exhausted": false    // default false
  },
```
Add, under **Notes** (near `:765-768`, beside the v2-reservation note), a one-line pointer: these two fields are additive at v1 (actively consumed by `check-merge-eligibility.sh`); when `agents-config-58m` bumps to v2 they fold into the v2 doc.

- [ ] **Step 2: Wire the counter into Phase 6**

In Phase 6 (`:400-412`), add the seed → compute → persist flow, verbatim in intent from the spec's *Phase 6 behavior* section:
- **On entry**, seed the prior silent count/exhausted from the head-exact inventory:
  `prior=$(jq -c '{c:(.polling.rereview_round_count // 0), e:(.polling.bot_review_cap_exhausted // false)}' "$HOME/.claude/state/pr-inventory/<owner>-<repo>-<n>-<head_sha_after_push>.json" 2>/dev/null || echo '{"c":0,"e":false}')`
- **On the silent exit path** (`no_rereview_started`), call the helper and merge into `POLLING_FILE`:
  `compute-rereview-polling.sh --prior-count <c> --prior-exhausted <e> --event silent` → merge its `{rereview_round_count, bot_review_cap_exhausted}` into `POLLING_FILE`.
- **On the existing `round >= 6` chatty cap**, call the helper with `--event chatty-cap` (does not advance the silent count) and merge.
- **PushNotification**: fire once on the `false → true` transition of `bot_review_cap_exhausted` (compare seeded `e` vs the helper's output), telling the human the retry window closed.

- [ ] **Step 3: Verify the edits are present and consistent**

Run:
```bash
grep -n "rereview_round_count\|bot_review_cap_exhausted\|compute-rereview-polling\|PushNotification" src/user/.agents/skills/wait-for-pr-comments/SKILL.md
```
Expected: hits in the schema block, Phase 6 silent path, chatty-cap path, and the PushNotification line. Read the surrounding Phase 6 prose to confirm the seed-compute-merge order is coherent and the head-exact path is used.

- [ ] **Step 4: Commit**

```bash
git add src/user/.agents/skills/wait-for-pr-comments/SKILL.md
git commit -m "feat(wait-for-pr-comments): persist rereview counter + cap-exhausted in Phase 6 (9njsd)"
```

---

## Task 6: `merge-guard/SKILL.md` — Step 4 branch, Step 5 guard, Decision Matrix, Red Flags

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/SKILL.md` — Step 4 rule-based "rule not satisfied" bullet (`:124-127`), Step 5 `--admin` row (`:155`), Decision Matrix rule-based rows (`:183-185`), Red Flags table (`:187-199`)

**Safety-critical prose.** The replacement text is authoritative in the spec — copy it verbatim from the cited sections. No unit test; verification is a targeted read + a self-consistency grep (Task 8 re-checks).

- [ ] **Step 1: Replace the Step 4 "rule not satisfied" bullet**

Find (`:124-127`):
```
- Rule not (yet) satisfied or blocked → report status and stop. NO
  force-merge in this mode. A timed-out bot (`review_wait.bot ==
  "timed_out"`) never satisfies the rule — hand off to the human with the
  facts.
```
Replace with the full branch from the spec's **§ Gate wiring (`merge-guard/SKILL.md` Step 4, `rule-based` branch)** — the three machine predicates (floor-clean / rule-unmet / ask-spent) plus the four sub-bullets (not-floor-clean → stop; not-ask-spent → issue ONE re-review ask via `request-rereview.sh` + poll helpers, re-run Step 3 once; ask-spent + force available → own terminal merge, no `--admin` ladder; ask-spent + force not available → hand off). Copy verbatim.

- [ ] **Step 2: Add the Step 5 `--admin` guard**

In the Step 5 `--admin` table, the `current_actor_can_bypass == true` row (`:155`) currently says "Retry once: `gh pr merge … --admin` …". Add the precondition from the spec's **§ Step 5 guard**: the `--admin` ladder is reachable **only for merges authorized through normal eligibility** (explicit-mode named force-merge, or a rule-based rule that actually held); a merge entered via the scoped bot-timeout force-merge sub-branch does not enter this ladder. Add one sentence to that row (or a note directly under the table) stating this, so the guard is co-located with the `--admin` decision.

- [ ] **Step 3: Replace the Decision Matrix rule-based rows**

Keep the 5-column matrix for `never`/`explicit`. Replace the three `rule-based` rows (`:183-185`) with the dedicated rule-based sub-table from the spec's **§ Decision Matrix additions** (columns: `Axis 2 | Floor clean | Rule holds | Ask spent | Force opted-in + fresh named instruction | Action`; 5 rows). Copy verbatim.

- [ ] **Step 4: Add the Red Flags rows**

Append the four rows from the spec's **§ Red Flags additions** (hand-rolled reply defeats the loop; "bot timed out, just force it"; "silence ≈ approval" → no; "force-merge rejected, add `--admin`" → no chaining) to the Red Flags table (`:187-199`). Copy verbatim.

- [ ] **Step 5: Verify presence + no dangling old model**

Run:
```bash
grep -n "bot_review_cap_exhausted\|request-rereview\|Ask spent\|does NOT enter Step 5\|floor-clean\|no bare reply" src/user/.agents/skills/merge-guard/SKILL.md
grep -n 'review_wait.bot ==\s*"timed_out"' src/user/.agents/skills/merge-guard/SKILL.md
```
Expected: first grep hits Step 4, Step 5 guard, Matrix, Red Flags. Second grep: the old `timed_out` hand-off bullet is **gone** from Step 4 (only the historical Red Flag reference, if any, remains). Read Step 4 + Decision Matrix together to confirm every matrix row maps to a Step-4 sub-bullet.

- [ ] **Step 6: Commit**

```bash
git add src/user/.agents/skills/merge-guard/SKILL.md
git commit -m "feat(merge-guard): bot-quiescence retry + scoped force-merge in Step 4/5 (9njsd)"
```

---

## Task 7: `design.md` — bot-quiescence lifecycle amendment

**Files:**
- Modify: `docs/architecture/review-merge-policy/design.md`

- [ ] **Step 1: Amend the bot-quiescence lifecycle**

Following the spec's **§ Design-doc amendment**, document in the bot-quiescence rule's lifecycle: the bounded auto-retry backstop (at most one ask per head, via `request-rereview.sh` directly), the `rereview_round_count` (silent-ask count) / `bot_review_cap_exhausted` facts and their two triggers, the head-exact fail-closed read, and the opt-in `allow-force-after-bot-timeout` escape hatch with its machine-explicit gating and its non-chaining into `--admin` (own terminal merge + Step 5 guard). Do not touch the `agent-ruling` paragraphs (owned by xvmf8).

- [ ] **Step 2: Verify + commit**

Run: `grep -n "bot_review_cap_exhausted\|allow-force-after-bot-timeout\|rereview_round_count" docs/architecture/review-merge-policy/design.md`
Expected: hits in the bot-quiescence lifecycle section.
```bash
git add docs/architecture/review-merge-policy/design.md
git commit -m "docs(review-merge-policy): document bot-quiescence retry + force-after-timeout (9njsd)"
```

---

## Task 8: Full verification sweep + consistency self-check

**Files:** none (verification only)

- [ ] **Step 1: Run the full skill-test sweep**

Run:
```bash
find src/user/.agents/skills src/user/.claude/hooks -name '*_test.sh' -print0 | sort -z | \
  xargs -0 -I{} sh -c 'echo "[TEST] $1"; bash "$1" || exit 1' _ {}
```
Expected: every `[TEST]` block ends without a `FAIL:` line; overall exit 0. Pay attention to `resolve_policy_test.sh`, `compute-rereview-polling_test.sh`, `check-merge-eligibility_test.sh`, `build-inventory-body_test.sh`, `validate-inventory_test.sh`.

- [ ] **Step 2: Cross-artifact consistency self-check**

Confirm the invariants the spec's adversarial review established still hold in the assembled files:
- Force-merge precondition is machine-bound (Step 4 reads floor-clean ⟺ exit 0/`blockers==[]`, `bot_clean_review_at_head==false`, `bot_review_cap_exhausted==true`, `policy.allow_force_after_bot_timeout==true`, fresh named instruction).
- The eligibility read is head-exact (`${OWNER}-${REPO}-${PR}-${HEAD_OID}.json`), never the glob.
- Scoped force-merge uses its own terminal merge; Step 5 `--admin` ladder guarded to normal-authorization entries.
- Decision-Matrix sub-table ↔ Step-4 sub-bullets ↔ Red-Flags agree; no dangling `timed_out` hand-off.

Run: `git diff main --stat` and re-read each changed file's touched region against `docs/specs/2026-07-03-merge-guard-bot-quiescence-retry.md`.

- [ ] **Step 3: Completion gate**

Run the completion gate (`quality-reviewer` → address → `simplify` → address → `verify-checklist`) per the repo's workflow, then `finishing-a-development-branch` (PR). Do NOT merge — this repo's merge-authorization policy governs that (resolve via `merge-guard`). Note the xvmf8 coordination in the PR body.

---

## Self-review (plan author)

- **Spec coverage:** Prerequisite → Tasks 2 (helper), 4 (pass-through), 5 (Phase 6 persist). Part (a) → Tasks 3 (fact read), 6 (Step-4 retry bullet + hand-rolled-reply Red Flag). Part (c) → Tasks 1 (config key), 6 (force-merge sub-branch + Step-5 guard + Matrix + Red Flags). Design-doc → Task 7. Every spec § maps to a task.
- **Deviations flagged:** (1) new `compute-rereview-polling.sh` helper (repo L0 Code-over-Prose; spec's "helpers unchanged" refers to the existing two, which stay unchanged); (2) tests use the existing subprocess/CLI `unittest` style, not `pytest.raises`.
- **Type/name consistency:** `allow_force_after_bot_timeout` (snake, dataclass/JSON) vs `allow-force-after-bot-timeout` (kebab, TOML/config key) used consistently; `rereview_round_count` / `bot_review_cap_exhausted` identical across helper, inventory, eligibility fact, and Step-4 predicates.

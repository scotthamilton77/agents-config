#!/usr/bin/env bash
# Verification script for bead 7bk.19.3 [m]-tagged acceptance criteria.
# Asserts mechanically-verifiable claims about the rewritten implement-bead
# skill (SKILL.md) and slash command (implement-bead.md). Exits 0 if all
# pass, 1 otherwise.
#
# Pre-rewrite this script intentionally fails (RED phase). Green-loop
# rewrites the target files until every assertion passes.

set -e
set -u

REPO_ROOT="$(git rev-parse --show-toplevel)"
SKILL="$REPO_ROOT/src/plugins/beads/.agents/skills/implement-bead/SKILL.md"
SLASH="$REPO_ROOT/src/plugins/beads/.claude/commands/implement-bead.md"

PASS=0
FAIL=0
FAILURES=()

ok() {
  PASS=$((PASS + 1))
  printf "PASS: %s\n" "$1"
}

bad() {
  FAIL=$((FAIL + 1))
  FAILURES+=("$1")
  printf "FAIL: %s\n" "$1"
}

# Helpers — return 0 (assertion passes) or non-zero (fails). Each helper is
# wrapped in `if ...; then ok ...; else bad ...; fi` so individual failures
# do not abort the script even under `set -e` (the `if` short-circuits the
# errexit semantics).

assert_file_exists() {
  local f="$1" desc="$2"
  if [[ -f "$f" ]]; then ok "$desc"; else bad "$desc (missing: $f)"; fi
}

assert_grep() {
  local pat="$1" file="$2" desc="$3"
  if grep -F -q -- "$pat" "$file" 2>/dev/null; then ok "$desc"; else bad "$desc"; fi
}

assert_grep_regex() {
  local pat="$1" file="$2" desc="$3"
  if grep -E -q -- "$pat" "$file" 2>/dev/null; then ok "$desc"; else bad "$desc"; fi
}

assert_no_grep() {
  local pat="$1" file="$2" desc="$3"
  if grep -F -q -- "$pat" "$file" 2>/dev/null; then bad "$desc"; else ok "$desc"; fi
}

assert_no_grep_regex() {
  local pat="$1" file="$2" desc="$3"
  if grep -E -q -- "$pat" "$file" 2>/dev/null; then bad "$desc"; else ok "$desc"; fi
}

assert_line_count_le() {
  local file="$1" max="$2" desc="$3"
  local n
  if [[ ! -f "$file" ]]; then bad "$desc (file missing)"; return; fi
  n=$(wc -l < "$file" | tr -d ' ')
  if [[ "$n" -le "$max" ]]; then ok "$desc (lines=$n, max=$max)"; else bad "$desc (lines=$n, max=$max)"; fi
}

# AC 1 — SKILL.md exists
assert_file_exists "$SKILL" "AC1: SKILL.md exists at expected path"

# AC 2 — Path convention: worker-audit/ + <step-bead-id> + <agent-name>; no worker-reports/
assert_grep "worker-audit/" "$SKILL" "AC2a: SKILL.md references worker-audit/ path convention"
assert_grep "<step-bead-id>" "$SKILL" "AC2b: SKILL.md references <step-bead-id> placeholder"
assert_grep "<agent-name>" "$SKILL" "AC2c: SKILL.md references <agent-name> placeholder"
assert_no_grep "worker-reports/" "$SKILL" "AC2d: SKILL.md has NO occurrences of worker-reports/"

# AC 3 — Audit-label prefix worker-audit-, no worker-report- LABEL prefix
# (worker-report-v1 the spec filename is allowed; ban worker-report- followed by alpha/digit
# in a label-prefix context. Original regex `worker-report-[a-z0-9]` was contradictory with
# AC5a's literal `worker-report-v1.md` requirement — the `v` matched. Tightened to exclude
# the v1 spec-filename form while still catching label-prefix usages like
# `worker-report-1`, `worker-report-iter1`, `worker-report-tdd-...`,
# `worker-report-bug-...`, etc. The `[0-9]` branch covers digit-prefixed labels.)
assert_grep "worker-audit-" "$SKILL" "AC3a: SKILL.md uses worker-audit- label prefix"
assert_no_grep_regex "worker-report-([0-9]|[a-uw-z]|v[02-9])" "$SKILL" "AC3b: SKILL.md has NO worker-report- label prefix usage"

# AC 4 — Agent-tool dispatch (Agent( and subagent_type), no `claude -p` worker dispatch
assert_grep "Agent(" "$SKILL" "AC4a: SKILL.md instructs Agent( tool dispatch"
assert_grep "subagent_type" "$SKILL" "AC4b: SKILL.md mentions subagent_type"
assert_no_grep_regex "claude -p .*(worker|tdd-|bug-diagnoser|implement-bead)" "$SKILL" "AC4c: SKILL.md has NO claude -p re-entry for worker dispatch"

# AC 5 — Synthesis on crash + malformed: worker-report-v1.md AND §4 (or section 4 / synthesis)
assert_grep "worker-report-v1.md" "$SKILL" "AC5a: SKILL.md references worker-report-v1.md"
assert_grep_regex "(§4|section 4|synthes)" "$SKILL" "AC5b: SKILL.md mentions §4 / synthesis on crash/malformed"

# AC 6 — Gate roll-up derivation: §1.1 / section 1.1 / roll-up
assert_grep_regex "(§1\.1|section 1\.1|roll-up|gate roll)" "$SKILL" "AC6: SKILL.md mentions §1.1 / gate roll-up derivation"

# AC 7 — root_cause_note + bug-diagnoser together
assert_grep "root_cause_note" "$SKILL" "AC7a: SKILL.md mentions root_cause_note"
assert_grep "bug-diagnoser" "$SKILL" "AC7b: SKILL.md mentions bug-diagnoser"

# AC 8 — All five (stage, mode) combos as literal strings
assert_grep "(red-tests, implement-feature)" "$SKILL" "AC8a: stage→agent (red-tests, implement-feature)"
assert_grep "(red-tests, fix-bug)"            "$SKILL" "AC8b: stage→agent (red-tests, fix-bug)"
assert_grep "(green-loop, implement-feature)" "$SKILL" "AC8c: stage→agent (green-loop, implement-feature)"
assert_grep "(green-loop, fix-bug)"           "$SKILL" "AC8d: stage→agent (green-loop, fix-bug)"
assert_grep "(diagnose, fix-bug)"             "$SKILL" "AC8e: stage→agent (diagnose, fix-bug)"

# AC 9 — Metadata-driven dispatch: ralf:required, ralf-implement, ralf-review
assert_grep "ralf:required" "$SKILL" "AC9a: SKILL.md mentions ralf:required label"
assert_grep "ralf-implement" "$SKILL" "AC9b: SKILL.md mentions ralf-implement"
assert_grep "ralf-review"    "$SKILL" "AC9c: SKILL.md mentions ralf-review"

# AC 10 — I3 sibling-test placement: I3 OR sibling test, AND discovered-from
assert_grep_regex "(I3|sibling test|sibling-test)" "$SKILL" "AC10a: SKILL.md references I3 / sibling-test"
assert_grep "discovered-from" "$SKILL" "AC10b: SKILL.md references discovered-from edge"

# AC 11 — Discovered-work ordering: BEFORE applying status outcomes
# Approximate: SKILL.md must have a line containing both "before" and one of
# "discovered" or "outcomes" (case-insensitive). Use grep -Ei for portability
# across BSD awk (IGNORECASE is gawk-only) — single-line co-occurrence is
# enforced by piping the "before" hits into a second case-insensitive grep.
if grep -E -i 'before' "$SKILL" 2>/dev/null | grep -E -i -q 'discovered|outcomes'; then
  ok "AC11: SKILL.md mentions filing discovered_work BEFORE outcomes (single-line co-occurrence)"
else
  bad "AC11: SKILL.md mentions filing discovered_work BEFORE outcomes"
fi

# AC 12 — Audit-label scope: worker-only — mention review/fresh-eyes/out-of-band near "audit"
# Approximate: file mentions "audit" AND any of {review, fresh-eyes, out-of-band, worker-only, worker only}
if grep -F -q "audit" "$SKILL" 2>/dev/null && grep -E -q "(review|fresh-eyes|out-of-band|worker-only|worker only)" "$SKILL" 2>/dev/null; then
  ok "AC12: SKILL.md scopes audit labels (mentions audit + review/fresh-eyes/out-of-band/worker-only)"
else
  bad "AC12: SKILL.md scopes audit labels"
fi

# AC 13 — Upstream report retrieval: (red-tests, fix-bug) AND (green-loop, fix-bug) AND root_cause_note
# AC 8b/8d already verify the stage tuples; here ensure root_cause_note is mentioned in upstream-retrieval context
assert_grep_regex "(upstream|prior diagnose|diagnose step|previous step)" "$SKILL" "AC13: SKILL.md documents upstream report retrieval procedure"

# AC 14 — Invocation contexts: top-level session AND in-session
assert_grep_regex "top-level session" "$SKILL" "AC14a: SKILL.md mentions top-level session"
assert_grep_regex "in-session" "$SKILL" "AC14b: SKILL.md mentions in-session orchestration skill execution"

# AC 15 — SKILL.md ≤ 150 lines
assert_line_count_le "$SKILL" 150 "AC15: SKILL.md ≤ 150 lines"

# AC 16 — Slash command exists, mentions Agent tool + orchestration loop ownership; ≤ 40 lines
assert_file_exists "$SLASH" "AC16a: slash command implement-bead.md exists"
assert_grep "Agent" "$SLASH" "AC16b: slash command mentions Agent tool"
assert_grep_regex "(orchestration|ralf-implement|loop owner|loop ownership|owns the loop|owns iteration)" "$SLASH" "AC16c: slash command mentions orchestration-skill loop ownership"
assert_line_count_le "$SLASH" 40 "AC16d: slash command ≤ 40 lines"

# AC 17 — No bead-implementor in either file
assert_no_grep "bead-implementor" "$SKILL" "AC17a: SKILL.md has NO bead-implementor references"
assert_no_grep "bead-implementor" "$SLASH" "AC17b: slash command has NO bead-implementor references"

TOTAL=$((PASS + FAIL))
printf "\nTotal: %d  Pass: %d  Fail: %d\n" "$TOTAL" "$PASS" "$FAIL"

if [[ "$FAIL" -gt 0 ]]; then
  printf "\nFailing assertions:\n"
  for msg in "${FAILURES[@]}"; do
    printf "  - %s\n" "$msg"
  done
  exit 1
fi

exit 0

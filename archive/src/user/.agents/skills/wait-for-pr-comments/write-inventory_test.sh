#!/usr/bin/env bash
# Smoke test for write-inventory.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/write-inventory.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0

assert() {
  if eval "$2"; then
    echo "  ok: $1"
  else
    echo "  FAIL: $1"
    FAIL=1
  fi
}

echo "[write-inventory_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --state flag" "grep -q -- '--state' '$SCRIPT'"
assert "accepts --phase flag" "grep -q -- '--phase' '$SCRIPT'"
assert "accepts --output flag" "grep -q -- '--output' '$SCRIPT'"
assert "no positional arg parsing (no \$1/\$2/\$3)" "! grep -qE '^\s*STATE=\"\\\$1\"' '$SCRIPT'"

# Missing required flags — exit 64
"$SCRIPT" 2>/dev/null
rc_no_args=$?
assert "exits 64 with no flags" "[ \$rc_no_args -eq 64 ]"

"$SCRIPT" --state complete --phase p1 2>/dev/null
rc_no_output=$?
assert "exits 64 when --output missing" "[ \$rc_no_output -eq 64 ]"

"$SCRIPT" --state complete --output /tmp/x.json 2>/dev/null
rc_no_phase=$?
assert "exits 64 when --phase missing" "[ \$rc_no_phase -eq 64 ]"

"$SCRIPT" --phase p1 --output /tmp/x.json 2>/dev/null
rc_no_state=$?
assert "exits 64 when --state missing" "[ \$rc_no_state -eq 64 ]"

# Bad --state value — exit 64
"$SCRIPT" --state bogus --phase p1 --output /tmp/x.json 2>/dev/null
rc_bad_state=$?
assert "exits 64 for invalid --state" "[ \$rc_bad_state -eq 64 ]"

# Unknown flag — exit 64
"$SCRIPT" --state complete --phase p1 --output /tmp/x.json --bogus 2>/dev/null
rc_bogus=$?
assert "exits 64 for unknown flag" "[ \$rc_bogus -eq 64 ]"

# Trailing flag with no value — must exit 64 (not silent exit 1)
"$SCRIPT" --state 2>/dev/null
rc_dangling=$?
assert "exits 64 for flag with no value (not silent exit 1)" "[ \$rc_dangling -eq 64 ]"

# --- Happy path: complete state ---
OUT_COMPLETE="$TMP/inv-complete.json"
printf '{"schema_version":1,"pr":{"number":1},"items":[]}' | \
  "$SCRIPT" --state complete --phase 7-write-inventory --output "$OUT_COMPLETE" 2>/dev/null
rc_complete=$?
assert "exits 0 on complete write" "[ \$rc_complete -eq 0 ]"
assert "output file exists" "[ -f '$OUT_COMPLETE' ]"
assert "crash_recovery.skill_a_completed is true" \
  "jq -e '.crash_recovery.skill_a_completed == true' '$OUT_COMPLETE' >/dev/null 2>&1"
assert "crash_recovery.last_completed_phase is 7-write-inventory" \
  "jq -e '.crash_recovery.last_completed_phase == \"7-write-inventory\"' '$OUT_COMPLETE' >/dev/null 2>&1"

# --- Happy path: partial state ---
OUT_PARTIAL="$TMP/inv-partial.json"
printf '{"schema_version":1,"pr":{"number":1},"items":[]}' | \
  "$SCRIPT" --state partial --phase 5a-verify-failed --output "$OUT_PARTIAL" 2>/dev/null
rc_partial=$?
assert "exits 0 on partial write" "[ \$rc_partial -eq 0 ]"
assert "crash_recovery.skill_a_completed is false" \
  "jq -e '.crash_recovery.skill_a_completed == false' '$OUT_PARTIAL' >/dev/null 2>&1"
assert "crash_recovery.last_completed_phase is 5a-verify-failed" \
  "jq -e '.crash_recovery.last_completed_phase == \"5a-verify-failed\"' '$OUT_PARTIAL' >/dev/null 2>&1"

# --- Invalid JSON input — exit 65 ---
OUT_BAD="$TMP/inv-bad.json"
printf 'not-json' | "$SCRIPT" --state complete --phase p1 --output "$OUT_BAD" 2>/dev/null
rc_bad_json=$?
assert "exits 65 on invalid JSON input" "[ \$rc_bad_json -eq 65 ]"

# --- Retention pruning: new .replyids/.posted sidecar suffixes ---
# The prune sweep only fires when --output's directory exactly equals
# ${HOME}/.claude/state/pr-inventory, so HOME is redirected to an isolated
# fixture dir before invoking the script (mirrors the FAKE_HOME pattern in
# merge-guard/check-merge-eligibility_test.sh) — never touches the real
# ~/.claude/state/pr-inventory.
PRUNE_HOME="$TMP/prune-home"
PRUNE_DIR="$PRUNE_HOME/.claude/state/pr-inventory"
mkdir -p "$PRUNE_DIR"

old_ts() {
  date -v-31d +%Y%m%d0000 2>/dev/null || date -d '31 days ago' +%Y%m%d0000
}
OLD_TS="$(old_ts)"

OLD_REPLYIDS="$PRUNE_DIR/o-r-1-abc.json.replyids"
OLD_POSTED="$PRUNE_DIR/o-r-1-abc.json.posted"
NEW_REPLYIDS="$PRUNE_DIR/o-r-2-def.json.replyids"
NEW_POSTED="$PRUNE_DIR/o-r-2-def.json.posted"
OLD_OTHER_PREFIX_REPLYIDS="$PRUNE_DIR/o-r-9-zzz.json.replyids"

: > "$OLD_REPLYIDS"; : > "$OLD_POSTED"
: > "$NEW_REPLYIDS"; : > "$NEW_POSTED"
: > "$OLD_OTHER_PREFIX_REPLYIDS"
touch -t "$OLD_TS" "$OLD_REPLYIDS" "$OLD_POSTED" "$OLD_OTHER_PREFIX_REPLYIDS"

PRUNE_OUT="$PRUNE_DIR/o-r-1-abc.json"
printf '{"schema_version":1,"pr":{"number":1},"items":[]}' | \
  env HOME="$PRUNE_HOME" "$SCRIPT" --state complete --phase 7-write-inventory --output "$PRUNE_OUT" 2>/dev/null
rc_prune=$?
assert "prune run exits 0" "[ \$rc_prune -eq 0 ]"

# A. New-suffix pruning fires for backdated sidecars
assert "backdated .replyids sidecar pruned" "[ ! -e '$OLD_REPLYIDS' ]"
assert "backdated .posted sidecar pruned" "[ ! -e '$OLD_POSTED' ]"

# B. Recent sidecars survive
assert "recent .replyids sidecar survives" "[ -e '$NEW_REPLYIDS' ]"
assert "recent .posted sidecar survives" "[ -e '$NEW_POSTED' ]"

# C. Other-PR-prefix sidecar: the pre-existing .json prune sweeps the whole
# directory by mtime alone with no filename-prefix scoping (verified against
# the live find predicate), so the new suffixes inherit that same
# directory-wide breadth rather than narrowing it — a backdated sidecar for a
# different PR prefix is pruned too, same as same-prefix backdated files.
assert "backdated other-prefix .replyids sidecar shares existing directory-wide prune scope" \
  "[ ! -e '$OLD_OTHER_PREFIX_REPLYIDS' ]"

exit $FAIL

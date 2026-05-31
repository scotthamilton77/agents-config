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

exit $FAIL

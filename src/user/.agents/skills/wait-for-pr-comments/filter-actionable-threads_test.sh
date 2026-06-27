#!/usr/bin/env bash
# Test for filter-actionable-threads.sh
#
# Phase 9's loop trigger must exclude threads that are intentionally
# unresolved (SKIP / ESCALATE classifications in the inventory). This helper
# post-processes count-unresolved-threads.sh output against the inventory so
# Phase 9 only re-loops on genuinely actionable threads (unresolved FIX or
# threads not present in the inventory at all).
#
# Behaviors covered:
#   1. Empty unresolved list → count 0, empty thread_ids
#   2. All threads are SKIP in inventory → count 0 (the bug aexb fixes)
#   3. All threads are ESCALATE in inventory → count 0
#   4. Mix of SKIP + FIX → only FIX thread remains
#   5. Thread not in inventory (genuinely new) → preserved (count > 0)
#   6. review_summary / issue_comment items (no thread_id) → ignored
#   7. Missing --inventory flag → exit 2
#   8. Inventory file missing → exit 1

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/filter-actionable-threads.sh"
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

echo "[filter-actionable-threads_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"

# --- Helper to build a count-unresolved-threads-style JSON payload ---
make_threads_json() {
  # $1 = space-separated thread IDs
  local ids="$1"
  jq -nc --argjson ids "$(printf '%s' "$ids" | jq -R 'split(" ") | map(select(length>0))')" \
    '{count: ($ids | length), thread_ids: $ids}'
}

# --- Helper to build an inventory items array ---
make_inventory() {
  # Each arg: "<thread_id>:<classification>"
  local items="[]"
  for spec in "$@"; do
    local tid="${spec%%:*}"
    local cls="${spec##*:}"
    items="$(jq -nc --argjson a "$items" --arg tid "$tid" --arg cls "$cls" \
      '$a + [{thread_id: $tid, classification: $cls}]')"
  done
  printf '%s' "$items"
}

# --- Test 1: empty unresolved list ---
EMPTY_THREADS='{"count":0,"thread_ids":[]}'
echo '{"items":[]}' > "$TMP/inv1.json"
printf '%s' "$EMPTY_THREADS" | "$SCRIPT" --inventory "$TMP/inv1.json" > "$TMP/out1.json" 2>&1
rc1=$?
assert "test 1: exits 0 on empty threads" "[ \$rc1 -eq 0 ]"
assert "test 1: count is 0" "jq -e '.count == 0' '$TMP/out1.json' >/dev/null 2>&1"
assert "test 1: thread_ids empty" "jq -e '(.thread_ids | length) == 0' '$TMP/out1.json' >/dev/null 2>&1"

# --- Test 2: all SKIP → count 0 (the aexb bug) ---
SKIP_THREADS='{"count":2,"thread_ids":["t1","t2"]}'
INV2="$(make_inventory t1:SKIP t2:SKIP)"
echo "{\"items\":$INV2}" > "$TMP/inv2.json"
printf '%s' "$SKIP_THREADS" | "$SCRIPT" --inventory "$TMP/inv2.json" > "$TMP/out2.json" 2>&1
rc2=$?
assert "test 2: exits 0 when all SKIP" "[ \$rc2 -eq 0 ]"
assert "test 2: count is 0 (SKIP excluded)" "jq -e '.count == 0' '$TMP/out2.json' >/dev/null 2>&1"
assert "test 2: thread_ids empty" "jq -e '(.thread_ids | length) == 0' '$TMP/out2.json' >/dev/null 2>&1"

# --- Test 3: all ESCALATE → count 0 ---
ESC_THREADS='{"count":1,"thread_ids":["t3"]}'
INV3="$(make_inventory t3:ESCALATE)"
echo "{\"items\":$INV3}" > "$TMP/inv3.json"
printf '%s' "$ESC_THREADS" | "$SCRIPT" --inventory "$TMP/inv3.json" > "$TMP/out3.json" 2>&1
rc3=$?
assert "test 3: exits 0 when all ESCALATE" "[ \$rc3 -eq 0 ]"
assert "test 3: count is 0 (ESCALATE excluded)" "jq -e '.count == 0' '$TMP/out3.json' >/dev/null 2>&1"

# --- Test 4: mix of SKIP + FIX → only FIX remains ---
MIX_THREADS='{"count":2,"thread_ids":["t1","t4"]}'
INV4="$(make_inventory t1:SKIP t4:FIX)"
echo "{\"items\":$INV4}" > "$TMP/inv4.json"
printf '%s' "$MIX_THREADS" | "$SCRIPT" --inventory "$TMP/inv4.json" > "$TMP/out4.json" 2>&1
rc4=$?
assert "test 4: exits 0 on mix" "[ \$rc4 -eq 0 ]"
assert "test 4: count is 1 (FIX preserved)" "jq -e '.count == 1' '$TMP/out4.json' >/dev/null 2>&1"
assert "test 4: thread_ids contains t4 only" "jq -e '.thread_ids == [\"t4\"]' '$TMP/out4.json' >/dev/null 2>&1"

# --- Test 5: thread not in inventory → preserved (genuinely new) ---
NEW_THREADS='{"count":1,"thread_ids":["tUnknown"]}'
echo '{"items":[]}' > "$TMP/inv5.json"
printf '%s' "$NEW_THREADS" | "$SCRIPT" --inventory "$TMP/inv5.json" > "$TMP/out5.json" 2>&1
rc5=$?
assert "test 5: exits 0 on unknown thread" "[ \$rc5 -eq 0 ]"
assert "test 5: count is 1 (unknown preserved)" "jq -e '.count == 1' '$TMP/out5.json' >/dev/null 2>&1"
assert "test 5: thread_ids contains tUnknown" "jq -e '.thread_ids == [\"tUnknown\"]' '$TMP/out5.json' >/dev/null 2>&1"

# --- Test 6: review_summary / issue_comment items (no thread_id) ignored ---
# Inventory has a SKIP review_summary (no thread_id) and a SKIP review_thread.
# Unresolved list has the thread. Only the thread's classification matters.
SUMMARY_THREADS='{"count":1,"thread_ids":["t1"]}'
INV6="$(jq -nc '[{classification: "SKIP"}, {thread_id: "t1", classification: "SKIP"}]')"
echo "{\"items\":$INV6}" > "$TMP/inv6.json"
printf '%s' "$SUMMARY_THREADS" | "$SCRIPT" --inventory "$TMP/inv6.json" > "$TMP/out6.json" 2>&1
rc6=$?
assert "test 6: exits 0 with summary items present" "[ \$rc6 -eq 0 ]"
assert "test 6: count is 0 (thread t1 is SKIP)" "jq -e '.count == 0' '$TMP/out6.json' >/dev/null 2>&1"

# --- Test 7: missing --inventory flag → exit 2 ---
printf '%s' "$EMPTY_THREADS" | "$SCRIPT" > "$TMP/out7.json" 2>&1
rc7=$?
assert "test 7: exits 2 on missing --inventory" "[ \$rc7 -eq 2 ]"

# --- Test 8: inventory file missing → exit 1 ---
printf '%s' "$EMPTY_THREADS" | "$SCRIPT" --inventory "$TMP/nonexistent.json" > "$TMP/out8.json" 2>&1
rc8=$?
assert "test 8: exits 1 on missing inventory file" "[ \$rc8 -eq 1 ]"

# --- Test 9: malformed inventory JSON → exit 2 with helpful message ---
MALFORMED_THREADS='{"count":1,"thread_ids":["t1"]}'
echo '{not valid json' > "$TMP/inv9.json"
printf '%s' "$MALFORMED_THREADS" | "$SCRIPT" --inventory "$TMP/inv9.json" > "$TMP/out9.json" 2>&1
rc9=$?
assert "test 9: exits 2 on malformed inventory JSON" "[ \$rc9 -eq 2 ]"
assert "test 9: stderr has script-level error message" "grep -qE '^error:' '$TMP/out9.json'"

exit $FAIL

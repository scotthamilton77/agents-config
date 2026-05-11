#!/usr/bin/env bash
# Smoke test for render-reply-bodies.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/render-reply-bodies.sh"
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

echo "[render-reply-bodies_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --inventory flag" "grep -q -- '--inventory' '$SCRIPT'"
assert "accepts --out flag" "grep -q -- '--out' '$SCRIPT'"

# Helper: build a single-item inventory JSON
make_inv() {
  local item="$1"
  echo "{\"schema_version\":1,\"pr\":{\"number\":1},\"items\":[$item]}"
}

# --- FIX committed ---
INV_FIX_COMMITTED="$TMP/inv-fix-committed.json"
make_inv '{"comment_id":"c1","classification":"FIX","fix_outcome":"committed","fix_commit_sha":"abc123","fix_summary":"fixed the thing"}' > "$INV_FIX_COMMITTED"
OUT_FIX_COMMITTED="$TMP/out-fix-committed.json"
"$SCRIPT" --inventory "$INV_FIX_COMMITTED" --out "$OUT_FIX_COMMITTED" > "$TMP/fix-committed.log" 2>&1
rc_fix_committed=$?
assert "FIX+committed exits 0" "[ \$rc_fix_committed -eq 0 ]"
assert "FIX+committed sets reply_body" \
  "jq -e '.items[0].reply_body == \"Fixed in abc123. fixed the thing\"' '$OUT_FIX_COMMITTED' >/dev/null 2>&1"

# --- FIX already_addressed ---
INV_FIX_AA="$TMP/inv-fix-aa.json"
make_inv '{"comment_id":"c2","classification":"FIX","fix_outcome":"already_addressed","fix_commit_sha":"def456"}' > "$INV_FIX_AA"
OUT_FIX_AA="$TMP/out-fix-aa.json"
"$SCRIPT" --inventory "$INV_FIX_AA" --out "$OUT_FIX_AA" > "$TMP/fix-aa.log" 2>&1
rc_fix_aa=$?
assert "FIX+already_addressed exits 0" "[ \$rc_fix_aa -eq 0 ]"
assert "FIX+already_addressed sets reply_body" \
  "jq -e '.items[0].reply_body == \"Already addressed in def456.\"' '$OUT_FIX_AA' >/dev/null 2>&1"

# --- FIX duplicate_of ---
INV_FIX_DUP="$TMP/inv-fix-dup.json"
make_inv '{"comment_id":"c3","classification":"FIX","fix_outcome":"committed","fix_commit_sha":"ghi","fix_summary":"s","duplicate_of":"https://github.com/o/r/pull/1#discussion_r999"}' > "$INV_FIX_DUP"
OUT_FIX_DUP="$TMP/out-fix-dup.json"
"$SCRIPT" --inventory "$INV_FIX_DUP" --out "$OUT_FIX_DUP" > "$TMP/fix-dup.log" 2>&1
rc_fix_dup=$?
assert "FIX+duplicate_of exits 0" "[ \$rc_fix_dup -eq 0 ]"
assert "FIX+duplicate_of sets reply_body with linked permalink" \
  "jq -e '.items[0].reply_body == \"Fixed via the change addressing https://github.com/o/r/pull/1#discussion_r999.\"' '$OUT_FIX_DUP' >/dev/null 2>&1"

# --- SKIP ---
INV_SKIP="$TMP/inv-skip.json"
make_inv '{"comment_id":"c4","classification":"SKIP","rationale":"out of scope"}' > "$INV_SKIP"
OUT_SKIP="$TMP/out-skip.json"
"$SCRIPT" --inventory "$INV_SKIP" --out "$OUT_SKIP" > "$TMP/skip.log" 2>&1
rc_skip=$?
assert "SKIP exits 0" "[ \$rc_skip -eq 0 ]"
assert "SKIP sets reply_body to rationale" \
  "jq -e '.items[0].reply_body == \"out of scope\"' '$OUT_SKIP' >/dev/null 2>&1"

# --- ESCALATE + filed + cap-exceeded rationale ---
INV_ESC_CAP="$TMP/inv-esc-cap.json"
make_inv '{"comment_id":"c5","classification":"ESCALATE","escalation_filed":true,"rationale":"exceeded re-review round cap"}' > "$INV_ESC_CAP"
OUT_ESC_CAP="$TMP/out-esc-cap.json"
"$SCRIPT" --inventory "$INV_ESC_CAP" --out "$OUT_ESC_CAP" > "$TMP/esc-cap.log" 2>&1
rc_esc_cap=$?
assert "ESCALATE+cap-exceeded exits 0" "[ \$rc_esc_cap -eq 0 ]"
assert "ESCALATE+cap-exceeded sets cap-exceeded template" \
  "jq -e '.items[0].reply_body == \"Round limit reached on this PR; deferring further iterations to a human reviewer.\"' '$OUT_ESC_CAP' >/dev/null 2>&1"

# --- ESCALATE + filed + other rationale ---
INV_ESC_AUTO="$TMP/inv-esc-auto.json"
make_inv '{"comment_id":"c6","classification":"ESCALATE","escalation_filed":true,"rationale":"some other reason"}' > "$INV_ESC_AUTO"
OUT_ESC_AUTO="$TMP/out-esc-auto.json"
"$SCRIPT" --inventory "$INV_ESC_AUTO" --out "$OUT_ESC_AUTO" > "$TMP/esc-auto.log" 2>&1
rc_esc_auto=$?
assert "ESCALATE+autonomous exits 0" "[ \$rc_esc_auto -eq 0 ]"
assert "ESCALATE+autonomous sets autonomous-filed template" \
  "jq -e '.items[0].reply_body == \"Captured for follow-up; will respond on a later push to this PR or in a related issue.\"' '$OUT_ESC_AUTO' >/dev/null 2>&1"

# --- ESCALATE + NOT filed → no reply_body ---
INV_ESC_UNFILED="$TMP/inv-esc-unfiled.json"
make_inv '{"comment_id":"c7","classification":"ESCALATE","escalation_filed":false,"rationale":"some reason"}' > "$INV_ESC_UNFILED"
OUT_ESC_UNFILED="$TMP/out-esc-unfiled.json"
"$SCRIPT" --inventory "$INV_ESC_UNFILED" --out "$OUT_ESC_UNFILED" > "$TMP/esc-unfiled.log" 2>&1
rc_esc_unfiled=$?
assert "ESCALATE+not-filed exits 0" "[ \$rc_esc_unfiled -eq 0 ]"
assert "ESCALATE+not-filed has no reply_body" \
  "jq -e '.items[0] | has(\"reply_body\") | not' '$OUT_ESC_UNFILED' >/dev/null 2>&1"

# --- Unknown classification → no reply_body, no error ---
INV_UNKNOWN="$TMP/inv-unknown.json"
make_inv '{"comment_id":"c8","classification":"WEIRD","rationale":"something"}' > "$INV_UNKNOWN"
OUT_UNKNOWN="$TMP/out-unknown.json"
"$SCRIPT" --inventory "$INV_UNKNOWN" --out "$OUT_UNKNOWN" > "$TMP/unknown.log" 2>&1
rc_unknown=$?
assert "unknown classification exits 0" "[ \$rc_unknown -eq 0 ]"
assert "unknown classification has no reply_body" \
  "jq -e '.items[0] | has(\"reply_body\") | not' '$OUT_UNKNOWN' >/dev/null 2>&1"

# --- FIX+committed missing fix_commit_sha → error (exit 1) ---
INV_BAD="$TMP/inv-bad.json"
make_inv '{"comment_id":"c9","classification":"FIX","fix_outcome":"committed","fix_summary":"s"}' > "$INV_BAD"
OUT_BAD="$TMP/out-bad.json"
"$SCRIPT" --inventory "$INV_BAD" --out "$OUT_BAD" > "$TMP/bad.log" 2>&1
rc_bad=$?
assert "FIX+committed missing fix_commit_sha exits 1" "[ \$rc_bad -eq 1 ]"

# --- Bad CLI invocation → exit 2 ---
"$SCRIPT" --no-such-flag 2>/dev/null
rc_cli=$?
assert "bad CLI flag exits 2" "[ \$rc_cli -eq 2 ]"

"$SCRIPT" 2>/dev/null
rc_no_args=$?
assert "no args exits 2" "[ \$rc_no_args -eq 2 ]"

exit $FAIL

#!/usr/bin/env bash
# Smoke test for validate-inventory.sh
#
# Verifies the --phase flag honors the pipeline contract:
#   --phase 0 runs guards 0-8 only (raw inventory; reply_body not yet populated)
#   --phase 2 (default) runs all ten guards

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/validate-inventory.sh"
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

echo "[validate-inventory_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents --phase flag in header" "head -30 '$SCRIPT' | grep -q -- '--phase'"
assert "documents --inventory flag in header" "head -30 '$SCRIPT' | grep -q -- '--inventory'"

# Bad flag usage — exit 64
"$SCRIPT" --phase 3 --inventory /tmp/whatever 2>/dev/null
rc_bad_phase=$?
assert "rejects --phase 3 with exit 64" "[ \$rc_bad_phase -eq 64 ]"

"$SCRIPT" --no-such-flag 2>/dev/null
rc_unknown=$?
assert "rejects unknown flag with exit 64" "[ \$rc_unknown -eq 64 ]"

# Missing --inventory — exit 64
"$SCRIPT" 2>/dev/null
rc_no_inv=$?
assert "missing --inventory exits 64" "[ \$rc_no_inv -eq 64 ]"

# Missing file — exit 66
"$SCRIPT" --inventory /nonexistent/path.json 2>/dev/null
rc_missing=$?
assert "missing file exits 66" "[ \$rc_missing -eq 66 ]"

# --- Raw inventory: a FIX-committed item lacks reply_body (typical Phase 0 input) ---
# Guard 10 would reject this; guards 0-8 should pass.
RAW="$TMP/raw.json"
cat >"$RAW" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {
      "comment_id": "c1",
      "kind": "review_thread",
      "classification": "FIX",
      "fix_outcome": "committed",
      "fix_commit_sha": "abc123",
      "fix_summary": "fixed",
      "fix_gate_variant": "lite",
      "rationale": "needs fixing"
    }
  ]
}
JSON

"$SCRIPT" --phase 0 --inventory "$RAW" 2>/dev/null
rc_phase0_raw=$?
assert "--phase 0 accepts raw inventory missing reply_body" "[ \$rc_phase0_raw -eq 0 ]"

"$SCRIPT" --phase 2 --inventory "$RAW" 2>/dev/null
rc_phase2_raw=$?
assert "--phase 2 rejects raw inventory missing reply_body (exit 1)" "[ \$rc_phase2_raw -eq 1 ]"

# Default --phase (no --phase flag) must behave as --phase 2
"$SCRIPT" --inventory "$RAW" 2>/dev/null
rc_default_raw=$?
assert "default --phase rejects raw inventory missing reply_body" "[ \$rc_default_raw -eq 1 ]"

# --- Rendered inventory: reply_body populated; both phases accept ---
RENDERED="$TMP/rendered.json"
cat >"$RENDERED" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {
      "comment_id": "c1",
      "kind": "review_thread",
      "classification": "FIX",
      "fix_outcome": "committed",
      "fix_commit_sha": "abc123",
      "fix_summary": "fixed",
      "fix_gate_variant": "lite",
      "rationale": "needs fixing",
      "reply_body": "Fixed in abc123. fixed"
    }
  ]
}
JSON

"$SCRIPT" --phase 0 --inventory "$RENDERED" 2>/dev/null
rc_phase0_rendered=$?
assert "--phase 0 accepts rendered inventory" "[ \$rc_phase0_rendered -eq 0 ]"

"$SCRIPT" --phase 2 --inventory "$RENDERED" 2>/dev/null
rc_phase2_rendered=$?
assert "--phase 2 accepts rendered inventory" "[ \$rc_phase2_rendered -eq 0 ]"

# --- Bad schema_version (Guard 0) — both phases reject ---
BAD_VERSION="$TMP/bad-version.json"
cat >"$BAD_VERSION" <<'JSON'
{"schema_version": 2, "items": []}
JSON

"$SCRIPT" --phase 0 --inventory "$BAD_VERSION" 2>/dev/null
rc_v_p0=$?
assert "--phase 0 rejects wrong schema_version" "[ \$rc_v_p0 -eq 1 ]"

"$SCRIPT" --phase 2 --inventory "$BAD_VERSION" 2>/dev/null
rc_v_p2=$?
assert "--phase 2 rejects wrong schema_version" "[ \$rc_v_p2 -eq 1 ]"

# ── review_id on review_summary (guard 3) ────────────────────────────────────
T15="$(mktemp -d)"
mk_inv() {  # mk_inv <items-json>
  jq -n --argjson items "$1" '{schema_version: 1, pr: {}, polling: {}, items: $items,
    crash_recovery: {skill_a_completed: false, last_completed_phase: "7-write-inventory"}}'
}
good_summary='[{"kind":"review_summary","review_id":301,"thread_id":null,"reply_to_comment_id":null,"issue_comment_id":null,"author":"copilot","body_excerpt":"x","classification":"SKIP","rationale":"noise","fix_outcome":null}]'
no_id_summary='[{"kind":"review_summary","thread_id":null,"reply_to_comment_id":null,"issue_comment_id":null,"author":"copilot","body_excerpt":"x","classification":"SKIP","rationale":"noise","fix_outcome":null}]'
wrong_id_summary='[{"kind":"review_summary","review_id":301,"thread_id":null,"reply_to_comment_id":null,"issue_comment_id":88,"author":"copilot","body_excerpt":"x","classification":"SKIP","rationale":"noise","fix_outcome":null}]'
string_id_summary='[{"kind":"review_summary","review_id":"301","thread_id":null,"reply_to_comment_id":null,"issue_comment_id":null,"author":"copilot","body_excerpt":"x","classification":"SKIP","rationale":"noise","fix_outcome":null}]'

mk_inv "$good_summary" > "$T15/good.json"
mk_inv "$no_id_summary" > "$T15/noid.json"
mk_inv "$wrong_id_summary" > "$T15/wrongid.json"
mk_inv "$string_id_summary" > "$T15/stringid.json"

"$HERE/validate-inventory.sh" --inventory "$T15/good.json" --phase 0 >/dev/null 2>&1
assert "review_summary with review_id passes guard 3" "[ \$? -eq 0 ]"
"$HERE/validate-inventory.sh" --inventory "$T15/noid.json" --phase 0 >/dev/null 2>&1
assert "review_summary without review_id fails guard 3" "[ \$? -eq 1 ]"
"$HERE/validate-inventory.sh" --inventory "$T15/wrongid.json" --phase 0 >/dev/null 2>&1
assert "review_summary with issue_comment_id still fails guard 3" "[ \$? -eq 1 ]"
"$HERE/validate-inventory.sh" --inventory "$T15/stringid.json" --phase 0 >/dev/null 2>&1
assert "review_summary with string review_id fails guard 3" "[ \$? -eq 1 ]"
rm -rf "$T15"

# inventory carrying the new polling fields still validates at v1
NEWPOLL="$TMP/newpoll-inv.json"
jq -n '{schema_version:1, pr:{number:1,owner:"o",repo:"r"},
        polling:{copilot_status:"timeout",rereview_round_count:1,bot_review_cap_exhausted:true},
        items:[]}' > "$NEWPOLL"
"$SCRIPT" --phase 0 --inventory "$NEWPOLL" 2>/dev/null
assert "phase 0 accepts new polling fields (exit 0)" "[ \$? -eq 0 ]"

exit $FAIL

#!/usr/bin/env bash
# Smoke test for validate-inventory.sh
#
# Verifies the --phase flag honors the pipeline contract:
#   --phase 0 runs guards 1-9 only (raw inventory; reply_body not yet populated)
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

# Bad flag usage — exit 64
"$SCRIPT" --phase 3 /tmp/whatever 2>/dev/null
rc_bad_phase=$?
assert "rejects --phase 3 with exit 64" "[ \$rc_bad_phase -eq 64 ]"

"$SCRIPT" --no-such-flag /tmp/whatever 2>/dev/null
rc_unknown=$?
assert "rejects unknown flag with exit 64" "[ \$rc_unknown -eq 64 ]"

# Missing file — exit 66
"$SCRIPT" /nonexistent/path.json 2>/dev/null
rc_missing=$?
assert "missing file exits 66" "[ \$rc_missing -eq 66 ]"

# --- Raw inventory: a FIX-committed item lacks reply_body (typical Phase 0 input) ---
# Guard 10 would reject this; guards 1-9 should pass.
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

"$SCRIPT" --phase 0 "$RAW" 2>/dev/null
rc_phase0_raw=$?
assert "--phase 0 accepts raw inventory missing reply_body" "[ \$rc_phase0_raw -eq 0 ]"

"$SCRIPT" --phase 2 "$RAW" 2>/dev/null
rc_phase2_raw=$?
assert "--phase 2 rejects raw inventory missing reply_body (exit 1)" "[ \$rc_phase2_raw -eq 1 ]"

# Default (no --phase) must behave as --phase 2 for backwards compat
"$SCRIPT" "$RAW" 2>/dev/null
rc_default_raw=$?
assert "default (no flag) rejects raw inventory missing reply_body" "[ \$rc_default_raw -eq 1 ]"

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

"$SCRIPT" --phase 0 "$RENDERED" 2>/dev/null
rc_phase0_rendered=$?
assert "--phase 0 accepts rendered inventory" "[ \$rc_phase0_rendered -eq 0 ]"

"$SCRIPT" --phase 2 "$RENDERED" 2>/dev/null
rc_phase2_rendered=$?
assert "--phase 2 accepts rendered inventory" "[ \$rc_phase2_rendered -eq 0 ]"

# --- Bad schema_version (Guard 0) — both phases reject ---
BAD_VERSION="$TMP/bad-version.json"
cat >"$BAD_VERSION" <<'JSON'
{"schema_version": 2, "items": []}
JSON

"$SCRIPT" --phase 0 "$BAD_VERSION" 2>/dev/null
rc_v_p0=$?
assert "--phase 0 rejects wrong schema_version" "[ \$rc_v_p0 -eq 1 ]"

"$SCRIPT" --phase 2 "$BAD_VERSION" 2>/dev/null
rc_v_p2=$?
assert "--phase 2 rejects wrong schema_version" "[ \$rc_v_p2 -eq 1 ]"

exit $FAIL

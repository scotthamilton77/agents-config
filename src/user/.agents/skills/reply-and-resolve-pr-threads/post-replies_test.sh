#!/usr/bin/env bash
# Smoke test for post-replies.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/post-replies.sh"
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

echo "[post-replies_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --inventory flag" "grep -q -- '--inventory' '$SCRIPT'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"

# Inventory fixture for behavior tests
INV="$TMP/inv.json"
cat >"$INV" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {"comment_id": "c1", "classification": "FIX", "fix_outcome": "committed"},
    {"comment_id": "c2", "classification": "FIX", "fix_outcome": "committed"}
  ]
}
JSON

# --- Fake-gh shim: pr comment posts succeed ---
FAKEBIN="$TMP/bin"
mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/gh" <<'FAKE'
#!/usr/bin/env bash
# Fake gh — any invocation succeeds.
exit 0
FAKE
chmod +x "$FAKEBIN/gh"

# Behavior test: --skip-comment-ids flag must be ACCEPTED (not rejected as
# unknown). Convention: unknown-flag rejections use exit 2 (per the
# audit-subagent-report contract used elsewhere in this skill). In red
# phase the script doesn't exist → rc=127. In green phase the flag is
# accepted and the script proceeds past flag parsing.
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV" --owner o --repo r --pr 1 \
  --skip-comment-ids "c1,c2" > "$TMP/skip-out.txt" 2>&1
rc_skip=$?
assert "--skip-comment-ids is not rejected as unknown flag (rc != 2)" \
  "[ \$rc_skip -ne 2 ]"

# Behavior test: items missing reply_body must emit FAILED <cid> reply_body_missing
# and the process must exit 1 (any_failed). Fixture INV has c1 and c2 with
# classification=FIX but no reply_body field.
INV_NO_BODY="$TMP/inv-no-body.json"
cat >"$INV_NO_BODY" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {"comment_id": "c1", "classification": "FIX", "fix_outcome": "committed"}
  ]
}
JSON
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_NO_BODY" --owner o --repo r --pr 1 \
  > "$TMP/nobody-out.txt" 2>&1
rc_nobody=$?
if [ "$rc_nobody" = "1" ]; then
  echo "  ok: missing reply_body causes exit 1"
else
  echo "  FAIL: missing reply_body should exit 1, got $rc_nobody"
  FAIL=1
fi
if grep -q 'FAILED c1 reply_body_missing' "$TMP/nobody-out.txt"; then
  echo "  ok: emits FAILED <cid> reply_body_missing"
else
  echo "  FAIL: missing FAILED c1 reply_body_missing output; got: $(cat "$TMP/nobody-out.txt")"
  FAIL=1
fi

# Behavior test: ESCALATE+escalation_filed=true items must be POSTED
# (not FILTERED). Use a stub gh that always succeeds.
INV_ESCALATE="$TMP/inv-escalate.json"
cat >"$INV_ESCALATE" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {
      "comment_id": "cE",
      "classification": "ESCALATE",
      "escalation_filed": true,
      "kind": "review_thread",
      "reply_to_comment_id": "12345",
      "reply_body": "Captured for follow-up; will respond on a later push to this PR or in a related issue.",
      "rationale": "needs human review"
    }
  ]
}
JSON
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_ESCALATE" --owner o --repo r --pr 1 \
  > "$TMP/escalate-out.txt" 2>&1
rc_escalate=$?
if grep -q 'POSTED cE' "$TMP/escalate-out.txt"; then
  echo "  ok: ESCALATE+escalation_filed=true is POSTED (not FILTERED)"
else
  echo "  FAIL: ESCALATE+escalation_filed=true should emit POSTED cE; got: $(cat "$TMP/escalate-out.txt")"
  FAIL=1
fi

# Failure path: invoking without --inventory must fail (flag validation)
if "$SCRIPT" --owner o --repo r --pr 1 2>/dev/null; then
  echo "  FAIL: accepted invocation without --inventory"
  FAIL=1
else
  echo "  ok: rejects missing --inventory"
fi

# Failure path: bad inventory path must fail
if "$SCRIPT" --inventory /nonexistent/path.json --owner o --repo r --pr 1 2>/dev/null; then
  echo "  FAIL: accepted nonexistent inventory file"
  FAIL=1
else
  echo "  ok: rejects nonexistent inventory file"
fi

exit $FAIL

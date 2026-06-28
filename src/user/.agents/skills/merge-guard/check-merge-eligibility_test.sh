#!/usr/bin/env bash
# Smoke test for check-merge-eligibility.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/check-merge-eligibility.sh"
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

echo "[check-merge-eligibility_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"
assert "accepts --comments-seen flag" "grep -q -- '--comments-seen' '$SCRIPT'"
assert "no positional owner/repo parsing" "! grep -qE '^\s*REPO=\"\\\$1\"' '$SCRIPT'"

# Missing required flags — exit 3
"$SCRIPT" 2>/dev/null
rc_no_args=$?
assert "exits 3 with no flags" "[ \$rc_no_args -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 2>/dev/null
rc_no_cs=$?
assert "exits 3 when --comments-seen missing" "[ \$rc_no_cs -eq 3 ]"

"$SCRIPT" --owner o --repo r --comments-seen 0 2>/dev/null
rc_no_pr=$?
assert "exits 3 when --pr missing" "[ \$rc_no_pr -eq 3 ]"

"$SCRIPT" --owner o --pr 1 --comments-seen 0 2>/dev/null
rc_no_repo=$?
assert "exits 3 when --repo missing" "[ \$rc_no_repo -eq 3 ]"

"$SCRIPT" --repo r --pr 1 --comments-seen 0 2>/dev/null
rc_no_owner=$?
assert "exits 3 when --owner missing" "[ \$rc_no_owner -eq 3 ]"

# Bad numeric values
"$SCRIPT" --owner o --repo r --pr notanumber --comments-seen 0 2>/dev/null
rc_bad_pr=$?
assert "exits 3 for non-integer --pr" "[ \$rc_bad_pr -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --comments-seen notanumber 2>/dev/null
rc_bad_cs=$?
assert "exits 3 for non-integer --comments-seen" "[ \$rc_bad_cs -eq 3 ]"

# Unknown flag
"$SCRIPT" --owner o --repo r --pr 1 --comments-seen 0 --bogus 2>/dev/null
rc_bogus=$?
assert "exits 3 for unknown flag" "[ \$rc_bogus -eq 3 ]"

# Trailing flag with no value — must exit 3 (not silent exit 1)
"$SCRIPT" --owner 2>/dev/null
rc_dangling=$?
assert "exits 3 for flag with no value (not silent exit 1)" "[ \$rc_dangling -eq 3 ]"

# ── Regression (nnqwg): reply comments must NOT count toward unseen ───────────
# A gh stub returns canned JSON per endpoint so the comment-counting jq filter
# runs end-to-end. Fixture: 2 top-level reviewer comments + 2 agent replies.
# With both top-level comments triaged (--comments-seen 2), the buggy `length`
# count yields 4 → unseen=2 → exit 2. The fix counts only top-level (2) → eligible.
STUB_DIR="$TMP/bin"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
[ "$1" = "auth" ] && exit 0
if [ "$1" = "api" ]; then
  path="$2"; shift 2
  filter=""
  while [ $# -gt 0 ]; do
    case "$1" in --jq) filter="$2"; shift 2 ;; *) shift ;; esac
  done
  case "$path" in
    */requested_reviewers) body='{"users":[],"teams":[]}' ;;
    */issues/*/events)     body='[]' ;;
    */pulls/*/reviews)     body='[]' ;;
    */pulls/*/comments)    body="$FIXTURE_COMMENTS" ;;
    */pulls/*)             body='{"state":"open"}' ;;
    *)                     body='{}' ;;
  esac
  if [ -n "$filter" ]; then printf '%s' "$body" | jq -r "$filter"; else printf '%s' "$body"; fi
  exit 0
fi
exit 0
STUB
chmod +x "$STUB_DIR/gh"

export FIXTURE_COMMENTS='[
  {"id":1,"in_reply_to_id":null,"user":{"login":"reviewer"}},
  {"id":2,"in_reply_to_id":null,"user":{"login":"reviewer"}},
  {"id":3,"in_reply_to_id":1,"user":{"login":"agent"}},
  {"id":4,"in_reply_to_id":2,"user":{"login":"agent"}}
]'

reply_out=$(PATH="$STUB_DIR:$PATH" "$SCRIPT" --owner o --repo r --pr 1 --comments-seen 2 2>/dev/null)
rc_replies=$?
assert "reply comments excluded → eligible (exit 0)" "[ \$rc_replies -eq 0 ]"
assert "total_comments counts only top-level (==2)" "[ \"\$(printf '%s' \"\$reply_out\" | jq -r '.total_comments')\" = '2' ]"

exit $FAIL

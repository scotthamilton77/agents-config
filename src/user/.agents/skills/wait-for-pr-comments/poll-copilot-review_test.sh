#!/usr/bin/env bash
# Smoke test for poll-copilot-review.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/poll-copilot-review.sh"
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

echo "[poll-copilot-review_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -25 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"
assert "no positional owner/repo parsing" "! grep -qE '^\s*REPO=\"\\\$1\"' '$SCRIPT'"

# Missing required flags — exit 3
"$SCRIPT" 2>/dev/null
rc_no_args=$?
assert "exits 3 with no flags" "[ \$rc_no_args -eq 3 ]"

"$SCRIPT" --owner o --repo r 2>/dev/null
rc_no_pr=$?
assert "exits 3 when --pr missing" "[ \$rc_no_pr -eq 3 ]"

"$SCRIPT" --owner o --pr 1 2>/dev/null
rc_no_repo=$?
assert "exits 3 when --repo missing" "[ \$rc_no_repo -eq 3 ]"

"$SCRIPT" --repo r --pr 1 2>/dev/null
rc_no_owner=$?
assert "exits 3 when --owner missing" "[ \$rc_no_owner -eq 3 ]"

# Bad --pr value
"$SCRIPT" --owner o --repo r --pr notanumber 2>/dev/null
rc_bad_pr=$?
assert "exits 3 for non-integer --pr" "[ \$rc_bad_pr -eq 3 ]"

# Unknown flag
"$SCRIPT" --owner o --repo r --pr 1 --bogus 2>/dev/null
rc_bogus=$?
assert "exits 3 for unknown flag" "[ \$rc_bogus -eq 3 ]"

# Trailing flag with no value — must exit 3 (not silent exit 1)
"$SCRIPT" --owner 2>/dev/null
rc_dangling=$?
assert "exits 3 for flag with no value (not silent exit 1)" "[ \$rc_dangling -eq 3 ]"

# ── --timeout-seconds (wgclw.14: plumbs Axis-1 bot_inactivity_timeout_seconds) ──

assert "accepts --timeout-seconds flag" "grep -q -- '--timeout-seconds' '$SCRIPT'"

"$SCRIPT" --owner o --repo r --pr 1 --timeout-seconds notanumber 2>/dev/null
rc_bad_timeout=$?
assert "exits 3 for non-integer --timeout-seconds" "[ \$rc_bad_timeout -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --timeout-seconds 0 2>/dev/null
rc_zero_timeout=$?
assert "exits 3 for --timeout-seconds 0" "[ \$rc_zero_timeout -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --timeout-seconds -5 2>/dev/null
rc_neg_timeout=$?
assert "exits 3 for negative --timeout-seconds" "[ \$rc_neg_timeout -eq 3 ]"

# ── --timeout-seconds drives the deadline (gh stub, no real gh calls) ───────────

STUB_DIR="$TMP/bin"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
[ "$1" = "auth" ] && exit 0
if [ "$1" = "api" ]; then
  shift
  path="$1"; shift
  filter=""
  while [ $# -gt 0 ]; do
    case "$1" in --jq) filter="$2"; shift 2 ;; *) shift ;; esac
  done
  case "$path" in
    */issues/*/events*)  body="${FIXTURE_EVENTS:-[]}" ;;
    */pulls/*/reviews*)  body="${FIXTURE_REVIEWS:-[]}" ;;
    */pulls/*/comments*) body="${FIXTURE_COMMENTS:-[]}" ;;
    */pulls/*)           body="${FIXTURE_PR:-'{"state":"open"}'}" ;;
    *)                   body='{}' ;;
  esac
  body="${body#\'}"; body="${body%\'}"
  if [ -n "$filter" ]; then printf '%s' "$body" | jq -r "$filter"; else printf '%s' "$body"; fi
  exit 0
fi
exit 0
STUB
chmod +x "$STUB_DIR/gh"

# Skip sub-phase A (--skip-request-check) and make sub-phase B resolve on its
# first attempt (copilot_work_started already present) so no real sleep is
# incurred before reaching sub-phase C's timeout loop.
FIXTURE_EVENTS_STARTED='[{"event":"copilot_work_started"}]'

start_ts=$(date +%s)
out=$(env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 2>/dev/null)
rc_tiny_timeout=$?
end_ts=$(date +%s)
elapsed=$((end_ts - start_ts))

assert "tiny --timeout-seconds exits 1 (timeout)" "[ \$rc_tiny_timeout -eq 1 ]"
assert "tiny --timeout-seconds reports copilot_review_timeout" "printf '%s' '$out' | grep -q copilot_review_timeout"
assert "tiny --timeout-seconds does not wait for the default ~10-minute window" "[ \$elapsed -lt 15 ]"

exit $FAIL

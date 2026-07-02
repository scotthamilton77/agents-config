#!/usr/bin/env bash
# Smoke test for check-merge-eligibility.sh (policy-driven rewrite).
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
assert "documents inputs/outputs in header" "head -40 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --policy-json flag" "grep -q -- '--policy-json' '$SCRIPT'"
assert "no --comments-seen flag (retired)" "! grep -q -- '--comments-seen' '$SCRIPT'"
assert "no substring copilot matching" "! grep -q 'test(\"copilot\"' '$SCRIPT'"

# ── gh + prgroom stubs ────────────────────────────────────────────────────────
STUB_DIR="$TMP/bin"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
[ "$1" = "auth" ] && exit 0
if [ "$1" = "api" ]; then
  shift
  if [ "$1" = "graphql" ]; then
    default_threads='{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]}}}}}'
    printf '%s' "${FIXTURE_GRAPHQL_THREADS:-$default_threads}"
    exit 0
  fi
  path="$1"; shift
  filter=""
  while [ $# -gt 0 ]; do
    case "$1" in --jq) filter="$2"; shift 2 ;; *) shift ;; esac
  done
  case "$path" in
    */requested_reviewers)  body="${FIXTURE_REQUESTED_REVIEWERS:-'{\"users\":[],\"teams\":[]}'}" ;;
    */issues/*/events*)     body="${FIXTURE_EVENTS:-[]}" ;;
    */issues/*/comments*)   body="${FIXTURE_ISSUE_COMMENTS:-[]}" ;;
    */pulls/*/reviews*)     body="${FIXTURE_REVIEWS:-[]}" ;;
    */protection/required_status_checks*)
        if [ "${FIXTURE_PROTECTION_404:-1}" = 1 ]; then
          echo "gh: Not Found (HTTP 404)" >&2; exit 1
        fi
        body="${FIXTURE_REQUIRED_CHECKS}" ;;
    */check-runs*)          body="${FIXTURE_CHECK_RUNS:-'{\"check_runs\":[]}'}" ;;
    */commits/*/status*)    body="${FIXTURE_COMMIT_STATUS:-'{\"statuses\":[]}'}" ;;
    */pulls/*)              body="${FIXTURE_PR:-'{\"state\":\"open\",\"head\":{\"sha\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"},\"base\":{\"ref\":\"main\"},\"created_at\":\"2026-01-01T00:00:00Z\"}'}" ;;
    *)                      body='{}' ;;
  esac
  body="${body#\'}"; body="${body%\'}"
  if [ -n "$filter" ]; then printf '%s' "$body" | jq -r "$filter"; else printf '%s' "$body"; fi
  exit 0
fi
exit 0
STUB
chmod +x "$STUB_DIR/gh"
# prgroom stub: emits FIXTURE_PRGROOM when set, else fails (= no prgroom state)
cat > "$STUB_DIR/prgroom" <<'STUB'
#!/usr/bin/env bash
[ -n "${FIXTURE_PRGROOM:-}" ] && { printf '%s' "$FIXTURE_PRGROOM"; exit 0; }
exit 1
STUB
chmod +x "$STUB_DIR/prgroom"

# Isolated HOME so inventory globs never see the real ~/.claude/state
FAKE_HOME="$TMP/home"
mkdir -p "$FAKE_HOME/.claude/state/pr-inventory"

run_script() {  # run_script <policy-json> [env VAR=... pairs]
  local policy="$1"; shift
  env HOME="$FAKE_HOME" PATH="$STUB_DIR:$PATH" "$@" \
    "$SCRIPT" --owner o --repo r --pr 1 --policy-json "$policy" 2>/dev/null
}

# Base policy: nothing expected on Axis 1 → in-flight atom vacuously clear
BASE_POLICY='{"bot_review_expected":false,"bot_reviewers":["trusted-bot[bot]"],"bot_inactivity_timeout_seconds":1200,"human_approvers_required":0,"human_review_timeout_seconds":null,"merge_authorization":"explicit","merge_rule":null}'
HEAD_SHA="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

# ── Arg validation (exit 3) ───────────────────────────────────────────────────
"$SCRIPT" 2>/dev/null;                                       assert "exits 3 with no flags" "[ \$? -eq 3 ]"
"$SCRIPT" --owner o --repo r --pr 1 2>/dev/null;             assert "exits 3 when --policy-json missing" "[ \$? -eq 3 ]"
"$SCRIPT" --owner o --repo r --pr x --policy-json "$BASE_POLICY" 2>/dev/null
assert "exits 3 for non-integer --pr" "[ \$? -eq 3 ]"
"$SCRIPT" --owner o --repo r --pr 1 --policy-json 'not-json' 2>/dev/null
assert "exits 3 for unparseable policy" "[ \$? -eq 3 ]"
"$SCRIPT" --owner o --repo r --pr 1 --policy-json '{}' 2>/dev/null
assert "exits 3 for policy missing required keys" "[ \$? -eq 3 ]"

# ── Skeleton behavior: empty fixtures + nothing expected → eligible ──────────
out=$(run_script "$BASE_POLICY"); rc=$?
assert "empty PR with nothing expected → exit 0" "[ \$rc -eq 0 ]"
assert "status is eligible" "[ \"\$(jq -r '.status' <<<\"\$out\")\" = eligible ]"
assert "head_ref_oid echoed" "[ \"\$(jq -r '.head_ref_oid' <<<\"\$out\")\" = \"$HEAD_SHA\" ]"
assert "blockers array empty" "[ \"\$(jq '.blockers | length' <<<\"\$out\")\" = 0 ]"
assert "merge hint binds head" "jq -r '.merge_command_hint' <<<\"\$out\" | grep -q -- \"--match-head-commit $HEAD_SHA\""

# ── Task 8: trusted-bot clean review fact ─────────────────────────────────────
mk_review() {  # mk_review <login> <state> <commit> <ts> [type]
  jq -n --arg l "$1" --arg s "$2" --arg c "$3" --arg t "$4" --arg ty "${5:-Bot}" \
    '{user: {login: $l, type: $ty}, state: $s, commit_id: $c, submitted_at: $t, body: ""}'
}

# clean: trusted bot, APPROVED at head
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "trusted APPROVED at head → fact true" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = true ]"

# COMMENTED at head is also clean (triage completeness is the floor's job)
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' COMMENTED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "trusted COMMENTED at head → fact true" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = true ]"

# stale head → not satisfied
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' APPROVED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "stale-head review → fact false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# missing commit_id → fail closed
revs='[{"user":{"login":"trusted-bot[bot]","type":"Bot"},"state":"APPROVED","submitted_at":"2026-01-01T01:00:00Z","body":""}]'
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "missing commit_id → fact false (fail closed)" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# untrusted bot (would match a substring filter) → ignored
revs=$(jq -n --argjson a "$(mk_review 'evil-copilot-clone[bot]' APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "untrusted bot ignored (exact identity)" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# latest wins: APPROVED then CHANGES_REQUESTED at head → not clean
revs=$(jq -n \
  --argjson a "$(mk_review 'trusted-bot[bot]' APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z)" \
  --argjson b "$(mk_review 'trusted-bot[bot]' CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T02:00:00Z)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "latest CHANGES_REQUESTED → fact false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# ── Task 9: requested-changes sticky blocker ─────────────────────────────────
# CR on an OLD commit still blocks (not head-scoped)
revs=$(jq -n --argjson a "$(mk_review reviewer1 CHANGES_REQUESTED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2026-01-01T01:00:00Z Human)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "stale-commit CR still blocks" "[ \$rc -eq 1 ]"
assert "blocker code requested_changes_active" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q requested_changes_active"

# later COMMENTED from same reviewer does NOT clear it
revs=$(jq -n \
  --argjson a "$(mk_review reviewer1 CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" \
  --argjson b "$(mk_review reviewer1 COMMENTED "$HEAD_SHA" 2026-01-01T02:00:00Z Human)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "later COMMENTED does not clear CR" "[ \$rc -eq 1 ]"

# later APPROVED from same reviewer DOES clear it
revs=$(jq -n \
  --argjson a "$(mk_review reviewer1 CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" \
  --argjson b "$(mk_review reviewer1 APPROVED "$HEAD_SHA" 2026-01-01T02:00:00Z Human)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "superseding APPROVED clears CR" "[ \$rc -eq 0 ]"

# dismissed CR (state=DISMISSED in API) does not block
revs=$(jq -n --argjson a "$(mk_review reviewer1 DISMISSED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "dismissed review does not block" "[ \$rc -eq 0 ]"

# ── Task 10: distinct current approvers ──────────────────────────────────────
# same login twice = 1; bot approval excluded; stale-head approval excluded
revs=$(jq -n \
  --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" \
  --argjson b "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T02:00:00Z Human)" \
  --argjson c "$(mk_review bot-x[bot] APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z Bot)" \
  --argjson d "$(mk_review carol APPROVED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2026-01-01T01:00:00Z Human)" \
  '[$a,$b,$c,$d]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "dedup by login, bots and stale heads excluded (==1)" "[ \"\$(jq '.facts.distinct_current_approvers' <<<\"\$out\")\" = 1 ]"

# APPROVED superseded by later CHANGES_REQUESTED = 0 approvers (and CR blocks)
revs=$(jq -n \
  --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" \
  --argjson b "$(mk_review alice CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T02:00:00Z Human)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "approval superseded by CR counts 0" "[ \"\$(jq '.facts.distinct_current_approvers' <<<\"\$out\")\" = 0 ]"

# ── Task 11: unresolved threads ──────────────────────────────────────────────
export_threads() {  # export_threads <resolved-bools...>  e.g. export_threads true false
  local nodes; nodes=$(printf '%s\n' "$@" | jq -R 'fromjson? // . | {isResolved: (. == "true" or . == true)}' | jq -s .)
  jq -n --argjson n "$nodes" '{data:{repository:{pullRequest:{reviewThreads:{pageInfo:{hasNextPage:false,endCursor:null},nodes:$n}}}}}'
}

out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads true false)"); rc=$?
assert "unresolved thread blocks" "[ \$rc -eq 1 ]"
assert "blocker code unresolved_threads" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q unresolved_threads"

out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads true true)"); rc=$?
assert "all threads resolved → eligible" "[ \$rc -eq 0 ]"

exit $FAIL

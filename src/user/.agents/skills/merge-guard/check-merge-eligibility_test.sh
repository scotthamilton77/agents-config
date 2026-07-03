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

# Structural precondition: the skill invokes this script directly, so a lost
# exec bit fails every case below with an opaque 126 — assert it once for a
# clear diagnostic. Behavioral properties (flag handling, exact-identity bot
# matching, set -e fail-closed exits) are pinned by the run tests below, never
# by grepping the script's own source text.
assert "script is executable" "[ -x '$SCRIPT' ]"

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
    # cursor-keyed pagination: the script threads a page's endCursor into the
    # follow-up query as `-f cursor=<val>`. Serve page 2 ONLY for the expected
    # cursor, so a dropped/mis-threaded cursor resolves to the empty terminal
    # page (never an accidental page-2 hit, never an infinite re-serve of page 1).
    cursor=""
    for a in "$@"; do case "$a" in cursor=*) cursor="${a#cursor=}" ;; esac; done
    if [ -n "$cursor" ]; then
      if [ "$cursor" = "${FIXTURE_THREADS_PAGE2_CURSOR:-CURSOR1}" ]; then
        printf '%s' "${FIXTURE_GRAPHQL_THREADS_PAGE2:-$default_threads}"
      else
        printf '%s' "$default_threads"
      fi
    else
      printf '%s' "${FIXTURE_GRAPHQL_THREADS:-$default_threads}"
    fi
    exit 0
  fi
  path="$1"; shift
  filter=""
  while [ $# -gt 0 ]; do
    case "$1" in --jq) filter="$2"; shift 2 ;; *) shift ;; esac
  done
  case "$path" in
    */requested_reviewers)  body="${FIXTURE_REQUESTED_REVIEWERS:-'{\"users\":[],\"teams\":[]}'}" ;;
    */issues/*/events*)
        if [ "${FIXTURE_EVENTS_FAIL:-0}" = 1 ]; then
          echo "gh: 502 Bad Gateway" >&2; exit 1
        fi
        body="${FIXTURE_EVENTS:-[]}" ;;
    */issues/*/comments*)   body="${FIXTURE_ISSUE_COMMENTS:-[]}" ;;
    */pulls/*/reviews*)     body="${FIXTURE_REVIEWS:-[]}" ;;
    */protection/required_status_checks*)
        if [ -n "${FIXTURE_BASE_REF_ENCODED:-}" ] && [[ "$path" != *"branches/${FIXTURE_BASE_REF_ENCODED}/protection"* ]]; then
          echo "gh: Not Found (HTTP 404)" >&2; exit 1
        fi
        if [ "${FIXTURE_PROTECTION_404:-1}" = 1 ]; then
          echo "gh: Not Found (HTTP 404)" >&2; exit 1
        fi
        body="${FIXTURE_REQUIRED_CHECKS}" ;;
    */check-runs*)          body="${FIXTURE_CHECK_RUNS:-'{\"check_runs\":[]}'}" ;;
    */commits/*/status*)
        if [ -n "${FIXTURE_COMMIT_STATUS_PAGE2:-}" ]; then
          # emulate `gh api --paginate` on an object-returning endpoint: each
          # page's JSON object is concatenated (arrays are NOT merged) — exactly
          # what the combined-status endpoint streams page-by-page. (A stub can't
          # reproduce real gh's server-side 30-item truncation; this exercises
          # the multi-page assembly the fix must handle.)
          s1="${FIXTURE_COMMIT_STATUS:-'{\"statuses\":[]}'}"; s1="${s1#\'}"; s1="${s1%\'}"
          s2="${FIXTURE_COMMIT_STATUS_PAGE2#\'}"; s2="${s2%\'}"
          printf '%s%s' "$s1" "$s2"; exit 0
        fi
        body="${FIXTURE_COMMIT_STATUS:-'{\"statuses\":[]}'}" ;;
    */rules/branches/*)
        if [ "${FIXTURE_RULES_FAIL:-0}" = 1 ]; then
          echo "gh: 500 Internal Server Error" >&2; exit 1
        fi
        if [ "${FIXTURE_RULES_404:-1}" = 1 ]; then
          echo "gh: Not Found (HTTP 404)" >&2; exit 1
        fi
        body="${FIXTURE_BRANCH_RULES:-[]}" ;;
    */rulesets/*)
        if [ "${FIXTURE_RULESET_FAIL:-0}" = 1 ]; then
          echo "gh: 500 Internal Server Error" >&2; exit 1
        fi
        case "$path" in
          # a null ruleset_id renders as the literal path segment "null" —
          # real GitHub 404s that; the stub mirrors it unconditionally so a
          # null id can't silently resolve to a fake bypass grant
          */rulesets/null) echo "gh: Not Found (HTTP 404)" >&2; exit 1 ;;
          */rulesets/111)  body="${FIXTURE_RULESET_111:-'{\"current_user_can_bypass\":\"none\"}'}" ;;
          */rulesets/222)  body="${FIXTURE_RULESET_222:-'{\"current_user_can_bypass\":\"none\"}'}" ;;
          *)               body="${FIXTURE_RULESET_BYPASS:-'{\"current_user_can_bypass\":\"none\"}'}" ;;
        esac ;;
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
# Unknown-flag rejection (also the regression guard for the retired
# --comments-seen flag — it must never be silently accepted again).
"$SCRIPT" --owner o --repo r --pr 1 --policy-json "$BASE_POLICY" --comments-seen 2>/dev/null
assert "exits 3 for an unknown flag (retired --comments-seen)" "[ \$? -eq 3 ]"

# ── Skeleton behavior: empty fixtures + nothing expected → eligible ──────────
out=$(run_script "$BASE_POLICY"); rc=$?
assert "empty PR with nothing expected → exit 0" "[ \$rc -eq 0 ]"
assert "status is eligible" "[ \"\$(jq -r '.status' <<<\"\$out\")\" = eligible ]"
assert "head_ref_oid echoed" "[ \"\$(jq -r '.head_ref_oid' <<<\"\$out\")\" = \"$HEAD_SHA\" ]"
assert "blockers array empty" "[ \"\$(jq '.blockers | length' <<<\"\$out\")\" = 0 ]"
assert "merge hint binds head" "jq -r '.merge_command_hint' <<<\"\$out\" | grep -q -- \"--match-head-commit $HEAD_SHA\""

# ── Fail-closed on non-open PR / absent head SHA (exit 3) ────────────────────
# The script refuses any non-open PR state, and any absent/null head SHA, before
# computing a single fact — an unknown/closed PR must never yield a verdict, and
# every positive fact binds to a real head. Both paths must exit 3 with no JSON.
closed_pr=$(jq -n --arg sha "$HEAD_SHA" '{state:"closed", head:{sha:$sha}, base:{ref:"main"}, created_at:"2026-01-01T00:00:00Z"}')
out=$(run_script "$BASE_POLICY" FIXTURE_PR="$closed_pr"); rc=$?
assert "closed PR → exit 3 (fail closed)" "[ \$rc -eq 3 ]"
assert "closed PR prints no verdict" "[ -z \"\$out\" ]"

merged_pr=$(jq -n --arg sha "$HEAD_SHA" '{state:"merged", head:{sha:$sha}, base:{ref:"main"}, created_at:"2026-01-01T00:00:00Z"}')
out=$(run_script "$BASE_POLICY" FIXTURE_PR="$merged_pr"); rc=$?
assert "merged PR → exit 3 (fail closed)" "[ \$rc -eq 3 ]"

null_head_pr=$(jq -n '{state:"open", head:{sha:null}, base:{ref:"main"}, created_at:"2026-01-01T00:00:00Z"}')
out=$(run_script "$BASE_POLICY" FIXTURE_PR="$null_head_pr"); rc=$?
assert "open PR with null head SHA → exit 3 (fail closed)" "[ \$rc -eq 3 ]"
assert "null head SHA prints no verdict" "[ -z \"\$out\" ]"

missing_head_pr=$(jq -n '{state:"open", head:{}, base:{ref:"main"}, created_at:"2026-01-01T00:00:00Z"}')
out=$(run_script "$BASE_POLICY" FIXTURE_PR="$missing_head_pr"); rc=$?
assert "open PR with missing head.sha key → exit 3 (fail closed)" "[ \$rc -eq 3 ]"

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

# superstring impersonation: a login that CONTAINS a trusted allowlist entry is
# still not that identity. Pins exact array-membership against a substring
# refactor of the trust boundary — evil-copilot-clone above is unrelated to the
# trusted name and would survive such a refactor, but this login would not.
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]-evil' APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "superstring-of-trusted login ignored (exact identity, not substring)" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# latest wins: APPROVED then CHANGES_REQUESTED at head → not clean
revs=$(jq -n \
  --argjson a "$(mk_review 'trusted-bot[bot]' APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z)" \
  --argjson b "$(mk_review 'trusted-bot[bot]' CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T02:00:00Z)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "latest CHANGES_REQUESTED → fact false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# ── Task 9: requested-changes sticky blocker ─────────────────────────────────
# CR on an OLD commit still blocks (not head-scoped)
revs=$(jq -n --argjson a "$(mk_review reviewer1 CHANGES_REQUESTED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2026-01-01T01:00:00Z User)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "stale-commit CR still blocks" "[ \$rc -eq 1 ]"
assert "blocker code requested_changes_active" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q requested_changes_active"

# later COMMENTED from same reviewer does NOT clear it
revs=$(jq -n \
  --argjson a "$(mk_review reviewer1 CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T01:00:00Z User)" \
  --argjson b "$(mk_review reviewer1 COMMENTED "$HEAD_SHA" 2026-01-01T02:00:00Z User)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "later COMMENTED does not clear CR" "[ \$rc -eq 1 ]"

# later APPROVED from same reviewer DOES clear it
revs=$(jq -n \
  --argjson a "$(mk_review reviewer1 CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T01:00:00Z User)" \
  --argjson b "$(mk_review reviewer1 APPROVED "$HEAD_SHA" 2026-01-01T02:00:00Z User)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "superseding APPROVED clears CR" "[ \$rc -eq 0 ]"

# dismissed CR (state=DISMISSED in API) does not block
revs=$(jq -n --argjson a "$(mk_review reviewer1 DISMISSED "$HEAD_SHA" 2026-01-01T01:00:00Z User)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "dismissed review does not block" "[ \$rc -eq 0 ]"

# ── Task 10: distinct current approvers ──────────────────────────────────────
# same login twice = 1; bot approval excluded; stale-head approval excluded
revs=$(jq -n \
  --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z User)" \
  --argjson b "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T02:00:00Z User)" \
  --argjson c "$(mk_review bot-x[bot] APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z Bot)" \
  --argjson d "$(mk_review carol APPROVED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2026-01-01T01:00:00Z User)" \
  '[$a,$b,$c,$d]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "dedup by login, bots and stale heads excluded (==1)" "[ \"\$(jq '.facts.distinct_current_approvers' <<<\"\$out\")\" = 1 ]"

# APPROVED superseded by later CHANGES_REQUESTED = 0 approvers (and CR blocks)
revs=$(jq -n \
  --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z User)" \
  --argjson b "$(mk_review alice CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T02:00:00Z User)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "approval superseded by CR counts 0" "[ \"\$(jq '.facts.distinct_current_approvers' <<<\"\$out\")\" = 0 ]"

# commit_id key wholly ABSENT on an APPROVED human review → not counted. The
# carol fixture above covers a stale/mismatched head; this pins the other arm
# of (.commit_id // "") — a missing key must fail closed exactly like a stale
# one. Raw literal (not mk_review, which always emits commit_id).
revs='[{"user":{"login":"dave","type":"User"},"state":"APPROVED","submitted_at":"2026-01-01T01:00:00Z","body":""}]'
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "APPROVED human review with no commit_id key → not counted (0 approvers)" "[ \"\$(jq '.facts.distinct_current_approvers' <<<\"\$out\")\" = 0 ]"

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

# multi-page: the reviewThreads cursor loop must visit every page, threading
# each page's endCursor into the next query. Page 1 (hasNextPage=true,
# endCursor=CURSOR1) carries 1 unresolved; page 2 is served ONLY for CURSOR1
# and carries 1 more. A total of 2 proves BOTH cross-page accumulation and
# correct cursor threading — a dropped cursor would miss page 2 and count 1.
export_threads_page() {  # export_threads_page <hasNextPage-bool> <endCursor|""> <resolved-bools...>
  local has="$1" cur="$2"; shift 2
  local nodes; nodes=$(printf '%s\n' "$@" | jq -R 'fromjson? // . | {isResolved: (. == "true" or . == true)}' | jq -s .)
  local cur_json=null; [ -n "$cur" ] && cur_json=$(jq -n --arg c "$cur" '$c')
  jq -n --argjson n "$nodes" --argjson h "$has" --argjson c "$cur_json" \
    '{data:{repository:{pullRequest:{reviewThreads:{pageInfo:{hasNextPage:$h,endCursor:$c},nodes:$n}}}}}'
}

p1=$(export_threads_page true CURSOR1 false true)   # 1 unresolved on page 1
p2=$(export_threads_page false "" false true)        # 1 unresolved on page 2
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$p1" FIXTURE_GRAPHQL_THREADS_PAGE2="$p2"); rc=$?
assert "unresolved threads across two pages block" "[ \$rc -eq 1 ]"
assert "unresolved count accumulates across BOTH pages (2)" \
  "jq -r '.blockers[].details' <<<\"\$out\" | grep -q '^2 unresolved'"

# every page resolved → eligible (the loop still advances to and past page 2)
p1r=$(export_threads_page true CURSOR1 true)
p2r=$(export_threads_page false "" true true)
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$p1r" FIXTURE_GRAPHQL_THREADS_PAGE2="$p2r"); rc=$?
assert "all threads resolved across two pages → eligible" "[ \$rc -eq 0 ]"

# ── Task 12: CI-green ────────────────────────────────────────────────────────
REQ_ONE='{"strict":false,"contexts":["ci/build"],"checks":[{"context":"ci/build","app_id":15368}]}'
run_ok()   { jq -n '{check_runs:[{name:"ci/build",status:"completed",conclusion:"success",app:{id:15368}}]}'; }
run_wrong_app() { jq -n '{check_runs:[{name:"ci/build",status:"completed",conclusion:"success",app:{id:99999}}]}'; }
run_pending()   { jq -n '{check_runs:[{name:"ci/build",status:"in_progress",conclusion:null,app:{id:15368}}]}'; }
run_failed()    { jq -n '{check_runs:[{name:"ci/build",status:"completed",conclusion:"failure",app:{id:15368}}]}'; }

# no branch protection (stub default 404) → vacuously green
out=$(run_script "$BASE_POLICY"); rc=$?
assert "no protection → ci_state none, eligible" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = none ]"

# required + success from the pinned app → green
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_ok)"); rc=$?
assert "pinned success → green, eligible" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = green ]"

# same-named success from a DIFFERENT app → not green (spoofed integration)
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_wrong_app)"); rc=$?
assert "wrong-app success → blocked" "[ \$rc -eq 1 ]"
assert "blocker code ci_not_green (wrong app)" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q ci_not_green"

# required check never started (absent from rollup) → not green
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS='{"check_runs":[]}'); rc=$?
assert "required check never started → blocked" "[ \$rc -eq 1 ]"

# in-progress → not green; failure → not green
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_pending)"); rc=$?
assert "in-progress required check → blocked" "[ \$rc -eq 1 ]"
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_failed)"); rc=$?
assert "failed required check → blocked" "[ \$rc -eq 1 ]"

# unpinned requirement satisfied by legacy commit status
REQ_UNPINNED='{"strict":false,"contexts":["legacy/lint"],"checks":[{"context":"legacy/lint","app_id":null}]}'
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_UNPINNED" \
      FIXTURE_COMMIT_STATUS='{"statuses":[{"context":"legacy/lint","state":"success"}]}'); rc=$?
assert "unpinned req satisfied by legacy status → eligible" "[ \$rc -eq 0 ]"

# multi-page: a required unpinned context whose combined-status lands on a later
# page must still be seen. Page 1 carries an unrelated status; legacy/lint's
# success is on page 2. The pre-fix single-object `jq` mishandles the
# concatenated multi-page stream; the fix slurps it with `--paginate | jq -s`.
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_UNPINNED" \
      FIXTURE_COMMIT_STATUS='{"statuses":[{"context":"legacy/other","state":"success"}]}' \
      FIXTURE_COMMIT_STATUS_PAGE2='{"statuses":[{"context":"legacy/lint","state":"success"}]}'); rc=$?
assert "required legacy context on a later status page is seen → eligible, green" \
  "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = green ]"

# ── admin-bypass fact: authenticated identity's standing bypass grant on a
#    GitHub ruleset's required-approving-review rule (separate from Axis 1) ──
# no rules apply to this branch (default 404) → inert, not required
out=$(run_script "$BASE_POLICY"); rc=$?
assert "no branch rules → admin_bypass inert, still eligible" "[ \$rc -eq 0 ]"
assert "review_rule_active false" "[ \"\$(jq '.facts.admin_bypass.review_rule_active' <<<\"\$out\")\" = false ]"
assert "required_approving_review_count 0" "[ \"\$(jq '.facts.admin_bypass.required_approving_review_count' <<<\"\$out\")\" = 0 ]"
assert "current_actor_can_bypass null when inactive" "[ \"\$(jq '.facts.admin_bypass.current_actor_can_bypass' <<<\"\$out\")\" = null ]"

RULES_ONE='[{"type":"pull_request","ruleset_id":111,"parameters":{"required_approving_review_count":1}}]'

# ruleset active, current identity holds an "always" bypass grant
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_ONE" FIXTURE_RULESET_111='{"current_user_can_bypass":"always"}'); rc=$?
assert "always-bypass identity → current_actor_can_bypass true" "[ \"\$(jq '.facts.admin_bypass.current_actor_can_bypass' <<<\"\$out\")\" = true ]"
assert "review_rule_active true when count > 0" "[ \"\$(jq '.facts.admin_bypass.review_rule_active' <<<\"\$out\")\" = true ]"
assert "required_approving_review_count echoed" "[ \"\$(jq '.facts.admin_bypass.required_approving_review_count' <<<\"\$out\")\" = 1 ]"

# pull_requests_only bypass mode also counts as bypassable
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_ONE" FIXTURE_RULESET_111='{"current_user_can_bypass":"pull_requests_only"}'); rc=$?
assert "pull_requests_only bypass → true" "[ \"\$(jq '.facts.admin_bypass.current_actor_can_bypass' <<<\"\$out\")\" = true ]"

# identity NOT on the bypass list (GitHub's real negative enum is "none") →
# fail closed, false
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_ONE" FIXTURE_RULESET_111='{"current_user_can_bypass":"none"}'); rc=$?
assert "none-bypass identity → current_actor_can_bypass false" "[ \"\$(jq '.facts.admin_bypass.current_actor_can_bypass' <<<\"\$out\")\" = false ]"

# an unrecognized value is never treated as bypassable — the allow-list
# rejects anything that isn't exactly "always" or "pull_requests_only"
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_ONE" FIXTURE_RULESET_111='{"current_user_can_bypass":"garbage"}'); rc=$?
assert "unrecognized bypass value → current_actor_can_bypass false" "[ \"\$(jq '.facts.admin_bypass.current_actor_can_bypass' <<<\"\$out\")\" = false ]"

# two rulesets covering the branch: one bypassable, one not → AND is false
RULES_TWO='[{"type":"pull_request","ruleset_id":111,"parameters":{"required_approving_review_count":1}},{"type":"pull_request","ruleset_id":222,"parameters":{"required_approving_review_count":2}}]'
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_TWO" \
      FIXTURE_RULESET_111='{"current_user_can_bypass":"always"}' FIXTURE_RULESET_222='{"current_user_can_bypass":"none"}'); rc=$?
assert "mixed bypass across rulesets → false (fail closed)" "[ \"\$(jq '.facts.admin_bypass.current_actor_can_bypass' <<<\"\$out\")\" = false ]"
assert "required_approving_review_count is the max across rulesets" "[ \"\$(jq '.facts.admin_bypass.required_approving_review_count' <<<\"\$out\")\" = 2 ]"

# a pull_request rule with count 0 (e.g. code-owner-review only) doesn't activate this fact
RULES_ZERO='[{"type":"pull_request","ruleset_id":111,"parameters":{"required_approving_review_count":0,"require_code_owner_review":true}}]'
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_ZERO"); rc=$?
assert "zero-count pull_request rule → review_rule_active false" "[ \"\$(jq '.facts.admin_bypass.review_rule_active' <<<\"\$out\")\" = false ]"

# a rule with count > 0 but a null ruleset_id → jq renders it as the literal
# path segment "null", GitHub 404s that detail fetch. admin_bypass never gates
# a blocker, so the unreadable ruleset degrades to non-bypassable (fail closed
# for --admin) and eligibility continues rather than aborting.
RULES_NULL_ID='[{"type":"pull_request","ruleset_id":null,"parameters":{"required_approving_review_count":1}}]'
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_NULL_ID"); rc=$?
assert "null ruleset_id with active count → eligible, current_actor_can_bypass false (fail closed for --admin)" \
    "[ \$rc -eq 0 ] && [ \"\$(jq '.facts.admin_bypass.current_actor_can_bypass' <<<\"\$out\")\" = false ]"

# rules/branches fetch fails for a reason other than 404 → admin_bypass degrades
# to the inert "no rulesets" state (never aborts eligibility over an
# informational fact)
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_FAIL=1); rc=$?
assert "branch-rules fetch hard failure → eligible, admin_bypass inert (review_rule_active false, current_actor_can_bypass null)" \
    "[ \$rc -eq 0 ] && [ \"\$(jq '.facts.admin_bypass.review_rule_active' <<<\"\$out\")\" = false ] && [ \"\$(jq '.facts.admin_bypass.current_actor_can_bypass' <<<\"\$out\")\" = null ]"

# a ruleset's own detail fetch fails after being listed → degrade to
# non-bypassable (fail closed for --admin) and continue rather than abort
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_ONE" FIXTURE_RULESET_FAIL=1); rc=$?
assert "ruleset detail fetch hard failure → eligible, current_actor_can_bypass false (fail closed for --admin)" \
    "[ \$rc -eq 0 ] && [ \"\$(jq '.facts.admin_bypass.current_actor_can_bypass' <<<\"\$out\")\" = false ]"

# ── Task 13: review still in flight ──────────────────────────────────────────
BOT_POLICY=$(jq -c '.bot_review_expected = true' <<<"$BASE_POLICY")
TS_RECENT=$(jq -rn 'now - 60 | todate')      # 1 min ago  < 1200s timeout
TS_OLD=$(jq -rn 'now - 7200 | todate')       # 2 h ago    > 1200s timeout

# bot expected, requested recently, no review yet → blocked (in flight)
ev=$(jq -n --arg t "$TS_RECENT" '[{event:"review_requested", requested_reviewer:{login:"trusted-bot[bot]"}, created_at:$t}]')
out=$(run_script "$BOT_POLICY" FIXTURE_EVENTS="$ev"); rc=$?
assert "pending bot review blocks explicit merge" "[ \$rc -eq 1 ]"
assert "blocker code review_in_flight" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q review_in_flight"
assert "review_wait.bot is waiting" "[ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = waiting ]"

# bot expected, silence past timeout → wait over (timed_out), not blocked
ev=$(jq -n --arg t "$TS_OLD" '[{event:"review_requested", requested_reviewer:{login:"trusted-bot[bot]"}, created_at:$t}]')
old_pr=$(jq -n --arg t "$TS_OLD" '{state:"open", head:{sha:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, base:{ref:"main"}, created_at:$t}')
out=$(run_script "$BOT_POLICY" FIXTURE_EVENTS="$ev" FIXTURE_PR="$old_pr"); rc=$?
assert "bot silence past timeout → eligible (timed_out)" "[ \$rc -eq 0 ]"
assert "review_wait.bot is timed_out" "[ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = timed_out ]"
assert "timeout does NOT satisfy the positive fact" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# bot review arrived at head → satisfied
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' COMMENTED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BOT_POLICY" FIXTURE_REVIEWS="$revs" FIXTURE_PR="$old_pr"); rc=$?
assert "arrived bot review → satisfied, eligible" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = satisfied ]"

# humans required, none yet, no timeout → blocks indefinitely
H_POLICY=$(jq -c '.human_approvers_required = 1' <<<"$BASE_POLICY")
out=$(run_script "$H_POLICY" FIXTURE_PR="$old_pr"); rc=$?
assert "missing human approval with null timeout blocks" "[ \$rc -eq 1 ]"
assert "review_wait.human is waiting" "[ \"\$(jq -r '.facts.review_wait.human' <<<\"\$out\")\" = waiting ]"

# humans required, timeout elapsed → wait over
H_TIMEOUT_POLICY=$(jq -c '.human_approvers_required = 1 | .human_review_timeout_seconds = 1200' <<<"$BASE_POLICY")
out=$(run_script "$H_TIMEOUT_POLICY" FIXTURE_PR="$old_pr"); rc=$?
assert "human timeout elapsed → eligible (timed_out)" "[ \$rc -eq 0 ]"

# humans required and enough current approvals → satisfied
revs=$(jq -n --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z User)" '[$a]')
out=$(run_script "$H_POLICY" FIXTURE_REVIEWS="$revs" FIXTURE_PR="$old_pr"); rc=$?
assert "enough approvals → satisfied, eligible" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.review_wait.human' <<<\"\$out\")\" = satisfied ]"

# ── Task 17: untriaged non-thread feedback ───────────────────────────────────
INV_DIR="$FAKE_HOME/.claude/state/pr-inventory"
write_inv() {  # write_inv <filename> <items-json>
  jq -n --argjson items "$2" '{schema_version: 1, pr: {}, polling: {}, items: $items,
    crash_recovery: {skill_a_completed: true, last_completed_phase: "9-final-check-done"}}' \
    > "$INV_DIR/$1"
}
clean_invs() { rm -f "$INV_DIR"/*.json; }

IC='[{"id": 900, "user": {"login": "reviewer"}, "body": "please fix the naming"}]'

# untriaged issue comment blocks
clean_invs
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "untriaged issue comment blocks" "[ \$rc -eq 1 ]"
assert "blocker code untriaged_feedback" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q untriaged_feedback"

# terminal triage in a retained inventory clears it — recorded against a
# DIFFERENT head SHA than current (union across pushes, never head-scoped)
write_inv "o-r-1-oldsha0001.json" '[{"kind":"issue_comment","issue_comment_id":900,"classification":"SKIP","rationale":"cosmetic","fix_outcome":null}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "triage from an older-head inventory still clears (union)" "[ \$rc -eq 0 ]"

# ESCALATE triage still blocks
clean_invs
write_inv "o-r-1-oldsha0001.json" '[{"kind":"issue_comment","issue_comment_id":900,"classification":"ESCALATE","escalation_filed":true,"rationale":"needs human","fix_outcome":null}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "ESCALATE disposition still blocks" "[ \$rc -eq 1 ]"

# a recorded agent reply is excluded by exact ID…
clean_invs
write_inv "o-r-1-oldsha0002.json" '[{"kind":"issue_comment","issue_comment_id":444,"classification":"SKIP","rationale":"r","fix_outcome":null,"posted_reply_id":900}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "recorded posted_reply_id excluded → eligible" "[ \$rc -eq 0 ]"

# …but a manual comment from the same account with a DIFFERENT id still blocks
IC2='[{"id": 900, "user": {"login": "operator"}, "body": "agent reply"}, {"id": 901, "user": {"login": "operator"}, "body": "actually, one more thing"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC2"); rc=$?
assert "same-account manual comment (unrecorded id) blocks" "[ \$rc -eq 1 ]"

# an APPROVED bot review with a non-empty body needs triage too
clean_invs
revs=$(jq -n '[{user: {login: "trusted-bot[bot]", type: "Bot"}, state: "APPROVED",
  commit_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", submitted_at: "2026-01-01T01:00:00Z",
  id: 301, body: "LGTM but consider renaming this module"}]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "APPROVED review with body blocks until triaged" "[ \$rc -eq 1 ]"

# triaged by review_id in a retained inventory → clears
write_inv "o-r-1-oldsha0003.json" '[{"kind":"review_summary","review_id":301,"classification":"FIX","rationale":"renamed","fix_outcome":"already_addressed","fix_commit_sha":"abc"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "review_summary triaged by review_id clears" "[ \$rc -eq 0 ]"
clean_invs

# a FIX item that FAILED to land is terminal but NOT clean → still blocks.
# terminal_ok clears FIX only for committed/already_addressed; Guard 5 in
# validate-inventory.sh permits fix_outcome=failed on a FIX item, so this is a
# real inventory shape the checker must never treat as resolved.
write_inv "o-r-1-failsha0001.json" '[{"kind":"issue_comment","issue_comment_id":900,"classification":"FIX","fix_outcome":"failed","rationale":"fix attempt failed","fix_commit_sha":null}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "FIX/failed disposition is terminal but not clean → still blocks" "[ \$rc -eq 1 ]"
clean_invs

# ── Durable reply-id sidecar (<owner>-<repo>-<pr>-<sha>.json.replyids) is
#    unioned into the posted-reply exclusion set as an ADDITIONAL, more
#    crash-robust source than inventory posted_reply_id fields ─────────────
write_replyids() {  # write_replyids <filename> <jsonl-line>...
  local file="$1"; shift
  printf '%s\n' "$@" > "$INV_DIR/$file"
}
clean_sidecars() { rm -f "$INV_DIR"/*.replyids; }

# A. sidecar-only exclusion: rid appears ONLY in a .replyids sidecar (no
#    inventory posted_reply_id anywhere) → still excluded, eligible
clean_invs; clean_sidecars
IC_SC='[{"id": 900, "user": {"login": "reviewer"}, "body": "please fix the naming"}]'
write_replyids "o-r-1-sidecarsha1.json.replyids" '{"k":"issue_comment_id","v":"900","rid":900}'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_SC"); rc=$?
assert "sidecar-only rid excludes matching live comment (no inventory posted_reply_id)" "[ \$rc -eq 0 ]"
clean_sidecars

# B. truncated final line tolerated: one valid line + one malformed
#    (hard-killed mid-append) final line → no crash, valid line still excludes
write_replyids "o-r-1-truncsha1.json.replyids" \
  '{"k":"issue_comment_id","v":"900","rid":900}' \
  '{"k":"issue_comment_id","v":"901","rid":901'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_SC"); rc=$?
assert "truncated final sidecar line does not crash the script" "[ -n \"\$out\" ] && [ \$rc -ne 3 ]"
assert "valid line ahead of a truncated one still excludes its rid" "[ \$rc -eq 0 ]"
clean_sidecars

# C. cross-sha union: two sidecar files for the same PR at different head
#    shas → rids from BOTH are excluded
IC_CROSS='[{"id": 970, "user": {"login": "reviewer"}, "body": "fix X"}, {"id": 971, "user": {"login": "reviewer"}, "body": "fix Y"}]'
write_replyids "o-r-1-crossshaA.json.replyids" '{"k":"issue_comment_id","v":"970","rid":970}'
write_replyids "o-r-1-crossshaB.json.replyids" '{"k":"issue_comment_id","v":"971","rid":971}'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_CROSS"); rc=$?
assert "rids from two different-sha sidecars both excluded (union)" "[ \$rc -eq 0 ]"
clean_sidecars

# D. duplicate rid across (and within) sidecars doesn't break the union+unique
IC_DUP='[{"id": 980, "user": {"login": "reviewer"}, "body": "dup across files"}]'
write_replyids "o-r-1-dupshaA.json.replyids" '{"k":"issue_comment_id","v":"980","rid":980}'
write_replyids "o-r-1-dupshaB.json.replyids" '{"k":"issue_comment_id","v":"980","rid":980}'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_DUP"); rc=$?
assert "duplicate rid across two sidecars still excludes without jq error" "[ \$rc -eq 0 ]"
clean_sidecars

IC_DUP2='[{"id": 981, "user": {"login": "reviewer"}, "body": "dup within one file"}]'
write_replyids "o-r-1-dupsame.json.replyids" \
  '{"k":"issue_comment_id","v":"981","rid":981}' \
  '{"k":"issue_comment_id","v":"981","rid":981}'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_DUP2"); rc=$?
assert "duplicate rid twice within one sidecar still excludes without jq error" "[ \$rc -eq 0 ]"
clean_sidecars

# ── Task 18: prgroom internal atoms ──────────────────────────────────────────
PG_BLOCKED='{"merge_gates":{"phase_is_quiesced":true,"last_error_clear":true,"no_blocker_items":false,"human_review_satisfied":true},"auto_merge_eligible":false}'
PG_ERROR='{"merge_gates":{"phase_is_quiesced":true,"last_error_clear":false,"no_blocker_items":true,"human_review_satisfied":true},"auto_merge_eligible":false}'
# rollup says GO but an atom says NO — proves the rollup is never consumed
PG_ROLLUP_LIES='{"merge_gates":{"phase_is_quiesced":true,"last_error_clear":true,"no_blocker_items":false,"human_review_satisfied":true},"auto_merge_eligible":true}'

out=$(run_script "$BASE_POLICY" FIXTURE_PRGROOM="$PG_BLOCKED"); rc=$?
assert "prgroom no_blocker_items=false blocks" "[ \$rc -eq 1 ]"
assert "blocker code prgroom_blocker" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q prgroom_blocker"

out=$(run_script "$BASE_POLICY" FIXTURE_PRGROOM="$PG_ERROR"); rc=$?
assert "prgroom last_error_clear=false blocks" "[ \$rc -eq 1 ]"

out=$(run_script "$BASE_POLICY" FIXTURE_PRGROOM="$PG_ROLLUP_LIES"); rc=$?
assert "auto_merge_eligible=true never overrides an atom" "[ \$rc -eq 1 ]"

out=$(run_script "$BASE_POLICY"); rc=$?
assert "no prgroom state → n/a, eligible" "[ \$rc -eq 0 ]"
assert "prgroom_available false" "[ \"\$(jq '.facts.prgroom_available' <<<\"\$out\")\" = false ]"

# ── Fix: issue-events fetch failure fails closed (exit 3) exactly when the
#    bot-wait computation needs events; the endpoint is never consulted when
#    no bot review is expected or the expected review already arrived ────────
out=$(run_script "$BOT_POLICY" FIXTURE_EVENTS_FAIL=1); rc=$?
assert "events-fetch failure exits 3 while bot wait needs events (fail closed)" "[ \$rc -eq 3 ]"
assert "events-fetch failure prints no verdict" "[ -z \"\$out\" ]"

out=$(run_script "$BASE_POLICY" FIXTURE_EVENTS_FAIL=1); rc=$?
assert "events failure irrelevant when no bot review expected" "[ \$rc -eq 0 ]"

revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BOT_POLICY" FIXTURE_EVENTS_FAIL=1 FIXTURE_REVIEWS="$revs"); rc=$?
assert "events failure irrelevant once expected review arrived at head" "[ \$rc -eq 0 ]"

# ── Fix: terminal disposition union excludes partial-crash inventories, but
#    the posted_reply_id exclusion union still reads them ──────────────────
write_inv_partial() {  # write_inv_partial <filename> <items-json>
  jq -n --argjson items "$2" '{schema_version: 1, pr: {}, polling: {}, items: $items,
    crash_recovery: {skill_a_completed: false, last_completed_phase: "5a-verify-failed"}}' \
    > "$INV_DIR/$1"
}

clean_invs
write_inv_partial "o-r-1-partial0001.json" \
  '[{"kind":"issue_comment","issue_comment_id":900,"classification":"SKIP","rationale":"cosmetic","fix_outcome":null}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "partial-crash inventory disposition does NOT clear untriaged feedback" "[ \$rc -eq 1 ]"
clean_invs

write_inv_partial "o-r-1-partial0002.json" \
  '[{"kind":"issue_comment","issue_comment_id":444,"classification":"SKIP","rationale":"r","fix_outcome":null,"posted_reply_id":900}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "posted_reply_id recorded in a partial-crash inventory still excludes it" "[ \$rc -eq 0 ]"
clean_invs

# ── Fix: cross-inventory triage union across TWO retained inventory files ───
IC3='[{"id": 950, "user": {"login": "reviewer"}, "body": "fix A"}, {"id": 951, "user": {"login": "reviewer"}, "body": "fix B"}]'
write_inv "o-r-1-multi0001.json" \
  '[{"kind":"issue_comment","issue_comment_id":950,"classification":"SKIP","rationale":"a","fix_outcome":null}]'
write_inv "o-r-1-multi0002.json" \
  '[{"kind":"issue_comment","issue_comment_id":951,"classification":"FIX","rationale":"b","fix_outcome":"committed"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC3"); rc=$?
assert "dispositions split across two retained inventories both clear (union)" "[ \$rc -eq 0 ]"
clean_invs

# ── Fix: BASE_REF is URL-encoded before the branch-protection fetch ─────────
slash_pr=$(jq -n --arg t "2026-01-01T00:00:00Z" --arg sha "$HEAD_SHA" \
  '{state:"open", head:{sha:$sha}, base:{ref:"release/1.0"}, created_at:$t}')
out=$(run_script "$BASE_POLICY" FIXTURE_PR="$slash_pr" FIXTURE_PROTECTION_404=0 \
      FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_ok)" \
      FIXTURE_BASE_REF_ENCODED="release%2F1.0"); rc=$?
assert "base ref with a slash resolves protection via the url-encoded path" \
  "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = green ]"

# ── Spec: both Axis-1 expectations simultaneously ────────────────────────────
BOTH_POLICY=$(jq -c '.bot_review_expected = true | .human_approvers_required = 1' <<<"$BASE_POLICY")
recent_pr=$(jq -n --arg t "$TS_RECENT" --arg sha "$HEAD_SHA" \
  '{state:"open", head:{sha:$sha}, base:{ref:"main"}, created_at:$t}')

revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' COMMENTED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BOTH_POLICY" FIXTURE_PR="$recent_pr" FIXTURE_REVIEWS="$revs"); rc=$?
assert "both-axis: bot clean, human missing → blocked" "[ \$rc -eq 1 ]"
assert "both-axis: bot satisfied while human waits" "[ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = satisfied ]"
assert "both-axis: human waiting while bot satisfied" "[ \"\$(jq -r '.facts.review_wait.human' <<<\"\$out\")\" = waiting ]"

revs=$(jq -n --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z User)" '[$a]')
out=$(run_script "$BOTH_POLICY" FIXTURE_PR="$recent_pr" FIXTURE_REVIEWS="$revs"); rc=$?
assert "both-axis: human approved, bot missing → blocked" "[ \$rc -eq 1 ]"
assert "both-axis: human satisfied while bot waits" "[ \"\$(jq -r '.facts.review_wait.human' <<<\"\$out\")\" = satisfied ]"
assert "both-axis: bot waiting while human satisfied" "[ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = waiting ]"

revs=$(jq -n \
  --argjson a "$(mk_review 'trusted-bot[bot]' COMMENTED "$HEAD_SHA" 2026-01-01T01:00:00Z)" \
  --argjson b "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T02:00:00Z User)" '[$a,$b]')
out=$(run_script "$BOTH_POLICY" FIXTURE_PR="$recent_pr" FIXTURE_REVIEWS="$revs"); rc=$?
assert "both-axis: both settled → eligible" "[ \$rc -eq 0 ]"

# ── Spec: prgroom present-and-clean combined with a live blocker ────────────
PG_CLEAN='{"merge_gates":{"phase_is_quiesced":true,"last_error_clear":true,"no_blocker_items":true,"human_review_satisfied":true},"auto_merge_eligible":true}'

out=$(run_script "$BASE_POLICY" FIXTURE_PRGROOM="$PG_CLEAN" FIXTURE_GRAPHQL_THREADS="$(export_threads false)"); rc=$?
assert "prgroom clean + live unresolved thread → blocked" "[ \$rc -eq 1 ]"
assert "blocker is unresolved_threads, not masked by prgroom" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q unresolved_threads"

out=$(run_script "$BASE_POLICY" FIXTURE_PRGROOM="$PG_CLEAN" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "prgroom clean + untriaged feedback → blocked" "[ \$rc -eq 1 ]"
assert "blocker is untriaged_feedback, not masked by prgroom" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q untriaged_feedback"

# ── Spec: distinct-approver counting with N>=2 ───────────────────────────────
revs=$(jq -n \
  --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z User)" \
  --argjson b "$(mk_review bob APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z User)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "two distinct current approvers count as 2" "[ \"\$(jq '.facts.distinct_current_approvers' <<<\"\$out\")\" = 2 ]"

revs=$(jq -n \
  --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z User)" \
  --argjson b "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T02:00:00Z User)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "same user approving twice counts as 1" "[ \"\$(jq '.facts.distinct_current_approvers' <<<\"\$out\")\" = 1 ]"

# ── Spec: SKIPPED and NEUTRAL required checks both count as passing ─────────
run_skipped() { jq -n '{check_runs:[{name:"ci/build",status:"completed",conclusion:"skipped",app:{id:15368}}]}'; }
run_neutral() { jq -n '{check_runs:[{name:"ci/build",status:"completed",conclusion:"neutral",app:{id:15368}}]}'; }
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_skipped)"); rc=$?
assert "SKIPPED required check counts as passing" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = green ]"
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_neutral)"); rc=$?
assert "NEUTRAL required check counts as passing" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = green ]"

# ── Spec: well-formed but wrong-typed policy values fail closed ─────────────
# (run via run_script so a real, un-stubbed `gh` in the environment can't
#  mask a missing type check by failing later for an unrelated reason)
BAD_BOOL=$(jq -c '.bot_review_expected = "true"' <<<"$BASE_POLICY")
run_script "$BAD_BOOL" >/dev/null; rc=$?
assert "exits 3 for bot_review_expected as a string" "[ \$rc -eq 3 ]"

BAD_TIMEOUT=$(jq -c '.bot_inactivity_timeout_seconds = "1200"' <<<"$BASE_POLICY")
run_script "$BAD_TIMEOUT" >/dev/null; rc=$?
assert "exits 3 for bot_inactivity_timeout_seconds as a string" "[ \$rc -eq 3 ]"

BAD_HUMAN_TIMEOUT=$(jq -c '.human_review_timeout_seconds = "1200"' <<<"$BASE_POLICY")
run_script "$BAD_HUMAN_TIMEOUT" >/dev/null; rc=$?
assert "exits 3 for human_review_timeout_seconds as a string" "[ \$rc -eq 3 ]"

BAD_ARRAY=$(jq -c '.bot_reviewers = "trusted-bot[bot]"' <<<"$BASE_POLICY")
run_script "$BAD_ARRAY" >/dev/null; rc=$?
assert "exits 3 for bot_reviewers as a non-array" "[ \$rc -eq 3 ]"

GOOD_NULL_TIMEOUT=$(jq -c '.human_review_timeout_seconds = null' <<<"$BASE_POLICY")
out=$(run_script "$GOOD_NULL_TIMEOUT"); rc=$?
assert "null human_review_timeout_seconds is still valid" "[ \$rc -eq 0 ]"

exit $FAIL

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
    user)
        if [ "${FIXTURE_AUTH_LOGIN_FAIL:-0}" = 1 ]; then
          echo "gh: 401 Unauthorized" >&2; exit 1
        fi
        body="${FIXTURE_AUTH_LOGIN_JSON:-'{\"login\":\"session-user\"}'}" ;;
    */requested_reviewers)  body="${FIXTURE_REQUESTED_REVIEWERS:-'{\"users\":[],\"teams\":[]}'}" ;;
    */issues/*/events*)
        if [ "${FIXTURE_EVENTS_FAIL:-0}" = 1 ]; then
          echo "gh: 502 Bad Gateway" >&2; exit 1
        fi
        body="${FIXTURE_EVENTS:-[]}" ;;
    */issues/*/comments*)   body="${FIXTURE_ISSUE_COMMENTS:-[]}" ;;
    */issues/*/reactions*)
        if [ "${FIXTURE_REACTIONS_FAIL:-0}" = 1 ]; then
          echo "gh: 502 Bad Gateway" >&2; exit 1
        fi
        if [ -n "${FIXTURE_REACTIONS_PAGE2:-}" ]; then
          # emulate `gh api --paginate` on an array-returning endpoint: each
          # page's JSON array is later merged via `jq -s 'add // []'` — mirrors
          # the ALL_REVIEWS / ISSUE_COMMENTS pagination idiom already in use.
          printf '%s\n%s\n' "${FIXTURE_REACTIONS:-[]}" "$FIXTURE_REACTIONS_PAGE2"; exit 0
        fi
        body="${FIXTURE_REACTIONS:-[]}" ;;
    */issues/*/timeline*)
        if [ -n "${FIXTURE_TIMELINE_PAGE2:-}" ]; then
          printf '%s\n%s\n' "${FIXTURE_TIMELINE:-[]}" "$FIXTURE_TIMELINE_PAGE2"; exit 0
        fi
        body="${FIXTURE_TIMELINE:-[]}" ;;
    */pulls/*/reviews*)     body="${FIXTURE_REVIEWS:-[]}" ;;
    */protection/required_status_checks*)
        if [ -n "${FIXTURE_BASE_REF_ENCODED:-}" ] && [[ "$path" != *"branches/${FIXTURE_BASE_REF_ENCODED}/protection"* ]]; then
          echo "gh: Not Found (HTTP 404)" >&2; exit 1
        fi
        if [ "${FIXTURE_PROTECTION_PRO_PAYWALL:-0}" = 1 ]; then
          echo "gh: Upgrade to GitHub Pro or make this repository public to enable this feature. (HTTP 403)" >&2; exit 1
        fi
        if [ "${FIXTURE_PROTECTION_FAIL:-0}" = 1 ]; then
          echo "gh: Resource not accessible by integration (HTTP 403)" >&2; exit 1
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
          # newline-separate the pages: jq's slurp (-s) reads whitespace-separated
          # JSON values, and real `gh --paginate` streams page bodies rather than
          # butting them together — a delimiter keeps older jq (1.5) happy too.
          printf '%s\n%s\n' "$s1" "$s2"; exit 0
        fi
        body="${FIXTURE_COMMIT_STATUS:-'{\"statuses\":[]}'}" ;;
    */commits/*)
        # plain single-commit fetch (committer date for the reaction-path
        # freshness check) — must be listed AFTER the more specific
        # */commits/*/status* case above, since this pattern also matches it.
        body="${FIXTURE_COMMIT:-'{\"commit\":{\"committer\":{\"date\":null}}}'}" ;;
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
    */pulls/*)
        # The Component 2 reaction path re-reads the head SHA (via --jq
        # .head.sha) AFTER the reactions/timeline fetch, to reject a head that
        # moved mid-check. FIXTURE_PR_REREAD lets a test simulate that move;
        # unset, the re-read sees the same FIXTURE_PR as the initial fetch.
        if [ "$filter" = ".head.sha" ] && [ -n "${FIXTURE_PR_REREAD:-}" ]; then
          body="$FIXTURE_PR_REREAD"
        else
          body="${FIXTURE_PR:-'{\"state\":\"open\",\"head\":{\"sha\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"},\"base\":{\"ref\":\"main\",\"sha\":\"cccccccccccccccccccccccccccccccccccccccc\"},\"created_at\":\"2026-01-01T00:00:00Z\"}'}"
        fi ;;
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
BASE_SHA="cccccccccccccccccccccccccccccccccccccccc"

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
assert "base_ref_oid echoed" "[ \"\$(jq -r '.base_ref_oid' <<<\"\$out\")\" = \"$BASE_SHA\" ]"
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

# GitHub's plan-paywall 403 for private repos without GitHub Pro/Team blocks
# reading branch-protection config outright (never 404s). Narrow text+status
# match only — vacuously green here reflects a verified ground truth (this
# script's real target repo has no branch protection configured), not a guess.
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_PRO_PAYWALL=1); rc=$?
assert "GitHub-Pro-paywall 403 on branch protection → vacuously green, eligible" \
  "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = none ]"

# a differently-worded 403 (missing token scope, app permission, etc.) must
# NOT be swallowed by the narrow paywall match — a real authNZ failure still
# fails closed exactly as before.
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_FAIL=1); rc=$?
assert "non-paywall 403 on branch protection still fails closed (exit 3)" "[ \$rc -eq 3 ]"
assert "non-paywall 403 prints no verdict" "[ -z \"\$out\" ]"

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

# ── ruleset-sourced required status checks (rules/branches/{base}, a
#    required_status_checks-type rule) — a repo enforcing CI via a GitHub
#    Ruleset instead of classic branch protection 404s the classic endpoint;
#    that 404 must NOT collapse the required set to empty when the modern
#    endpoint lists a real requirement. ────────────────────────────────────
RULES_CI_ONE='[{"type":"required_status_checks","ruleset_id":333,"parameters":{"required_status_checks":[{"context":"ci","integration_id":15368}]}}]'
run_ci_ok()        { jq -n '{check_runs:[{name:"ci",status:"completed",conclusion:"success",app:{id:15368}}]}'; }
run_ci_wrong_app() { jq -n '{check_runs:[{name:"ci",status:"completed",conclusion:"success",app:{id:99999}}]}'; }

# classic endpoint 404s (no classic protection), ruleset alone requires "ci",
# satisfied by a pinned-app success → green, eligible
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_CI_ONE" FIXTURE_CHECK_RUNS="$(run_ci_ok)"); rc=$?
assert "ruleset-only required check satisfied → ci_state green, eligible" \
  "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = green ]"

# ruleset-only required check never started → blocked, never vacuously green
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_CI_ONE" FIXTURE_CHECK_RUNS='{"check_runs":[]}'); rc=$?
assert "ruleset-only required check absent → blocked (rc 1)" "[ \$rc -eq 1 ]"
assert "blocker code ci_not_green (ruleset-sourced)" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q ci_not_green"

# a same-named success from a DIFFERENT app than the ruleset's integration_id
# pin is not satisfied — the ruleset source pins trust exactly like the
# classic-endpoint app_id pin does
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_CI_ONE" FIXTURE_CHECK_RUNS="$(run_ci_wrong_app)"); rc=$?
assert "ruleset-pinned wrong-app success → blocked" "[ \$rc -eq 1 ]"

# union: classic protection requires ci/build, ruleset separately requires
# ci — BOTH sources' requirements must be evaluated, not just whichever
# endpoint answered. Only ci/build's check run exists → still blocked on the
# ruleset-sourced "ci" requirement.
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" \
      FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_CI_ONE" FIXTURE_CHECK_RUNS="$(run_ok)"); rc=$?
assert "union of classic+ruleset required checks, ruleset one unmet → blocked" "[ \$rc -eq 1 ]"

# union satisfied from both sources → green
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" \
      FIXTURE_RULES_404=0 FIXTURE_BRANCH_RULES="$RULES_CI_ONE" \
      FIXTURE_CHECK_RUNS='{"check_runs":[{"name":"ci/build","status":"completed","conclusion":"success","app":{"id":15368}},{"name":"ci","status":"completed","conclusion":"success","app":{"id":15368}}]}'); rc=$?
assert "union of classic+ruleset required checks, both met → green, eligible" \
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

# rules/branches now also sources the CI-green blocker's required-checks
# union (not just the informational admin_bypass fact), so a hard failure on
# it must fail closed exactly like the classic protection endpoint's own
# hard-failure branch — never silently degrade to "no rulesets" and risk a
# ruleset-only required check reading vacuously green.
out=$(run_script "$BASE_POLICY" FIXTURE_RULES_FAIL=1); rc=$?
assert "branch-rules fetch hard failure → fails closed (exit 3)" "[ \$rc -eq 3 ]"
assert "branch-rules fetch hard failure → prints no verdict" "[ -z \"\$out\" ]"

# classic protection legitimately absent (404, ruleset-only repo) AND the
# rules/branches fetch hard-fails → must NOT read as vacuous green (the
# original bug relocated to this endpoint's failure path)
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=1 FIXTURE_RULES_FAIL=1); rc=$?
assert "classic 404 + rules hard failure → fails closed, not vacuous green (exit 3)" "[ \$rc -eq 3 ]"

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
old_pr=$(jq -n --arg t "$TS_OLD" --arg base "$BASE_SHA" '{state:"open", head:{sha:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, base:{ref:"main", sha:$base}, created_at:$t}')
out=$(run_script "$BOT_POLICY" FIXTURE_EVENTS="$ev" FIXTURE_PR="$old_pr"); rc=$?
assert "bot silence past timeout → eligible (timed_out)" "[ \$rc -eq 0 ]"
assert "review_wait.bot is timed_out" "[ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = timed_out ]"
assert "timeout does NOT satisfy the positive fact" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# bot review arrived at head → satisfied
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' COMMENTED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BOT_POLICY" FIXTURE_REVIEWS="$revs" FIXTURE_PR="$old_pr"); rc=$?
assert "arrived bot review → satisfied, eligible" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = satisfied ]"

# ── review_wait.bot recognizes Codex's reaction-based signals (2026-07-18
# codex-rereview-path-design), not just Copilot's review-object/event
# vocabulary. "arrived" must also fire off the already-computed
# reaction_clean fact (Component 2b) — Codex's clean auto/push-triggered pass
# leaves a +1 reaction, never a review object — and latest_ref's freshness
# clock must also advance on a trusted `eyes` reaction, the Codex analogue of
# Copilot's copilot_work_started event.

# Codex-only PR: no review object, no review_requested/copilot_work_started
# events, just a qualifying clean +1 reaction at head → satisfied via the
# reaction path (arrived must OR in reaction_clean).
commit_recent=$(jq -n '{commit:{committer:{date:"2026-01-01T00:00:00Z"}}}')
reacts_plus1=$(jq -n --arg t "2026-01-01T01:00:00Z" \
  '[{id:1, content:"+1", user:{login:"trusted-bot[bot]", type:"Bot"}, created_at:$t}]')
out=$(run_script "$BOT_POLICY" FIXTURE_REACTIONS="$reacts_plus1" FIXTURE_COMMIT="$commit_recent"); rc=$?
assert "codex-only clean +1 reaction → review_wait.bot satisfied (reaction path)" \
    "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = satisfied ]"

# Load-bearing regression: an `eyes` reaction from a trusted identity resets
# the freshness clock. PR age alone (old_pr, 2h old) would exceed
# BOT_TIMEOUT, but a recent `eyes` must push latest_ref forward so the wait
# reads "waiting", not "timed_out" — Codex is comment-triggered and never
# emits review_requested/copilot_work_started, so without this the wait
# always reads stale mid-review.
reacts_eyes_only=$(jq -n --arg t "$TS_RECENT" \
  '[{id:2, content:"eyes", user:{login:"trusted-bot[bot]", type:"Bot"}, created_at:$t}]')
out=$(run_script "$BOT_POLICY" FIXTURE_REACTIONS="$reacts_eyes_only" FIXTURE_PR="$old_pr"); rc=$?
assert "trusted eyes reaction resets freshness clock → waiting, not timed_out" \
    "[ \$rc -eq 1 ] && [ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = waiting ]"

# Non-allowlisted identity's eyes/+1 must not feed into arrived or
# latest_ref — same allowlist-exact-match discipline as the rest of the
# reaction path. Old PR, only untrusted reactions → still timed_out.
reacts_untrusted=$(jq -n --arg t "$TS_RECENT" \
  '[{id:3, content:"eyes", user:{login:"evil-bot[bot]", type:"Bot"}, created_at:$t},
    {id:4, content:"+1", user:{login:"evil-bot[bot]", type:"Bot"}, created_at:$t}]')
out=$(run_script "$BOT_POLICY" FIXTURE_REACTIONS="$reacts_untrusted" FIXTURE_PR="$old_pr"); rc=$?
assert "non-allowlisted eyes/+1 reactions ignored → still timed_out" \
    "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = timed_out ]"

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

# ── Component 2b (2026-07-18 spec): loop-generated comments are not feedback ──
# Both the clean-pass announcement and the "@codex review" trigger comment are
# artifacts of the re-review loop itself, not human/bot feedback needing
# triage — excluded from live_issue entirely (same effect as terminal triage).
clean_invs

# (1) Clean-pass marker from an allowlisted bot → excluded, eligible
IC_CLEAN='[{"id": 950, "user": {"login": "trusted-bot[bot]"}, "body": "Codex Review: Didn'\''t find any major issues here, LGTM"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_CLEAN"); rc=$?
assert "clean-pass marker from allowlisted bot excluded → eligible" "[ \$rc -eq 0 ]"

# (2) Same marker text from a NON-allowlisted author still blocks — the
# exemption is a bot-identity + marker conjunction, not a marker-alone match
IC_CLEAN_UNTRUSTED='[{"id": 951, "user": {"login": "random-user"}, "body": "Codex Review: Didn'\''t find any major issues here"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_CLEAN_UNTRUSTED"); rc=$?
assert "clean-pass marker text from non-allowlisted author still blocks" "[ \$rc -eq 1 ]"

# (3) A bot comment that merely CONTAINS the marker, not starting with it,
# still blocks — prefix match only, never substring
IC_CLEAN_NOTPREFIX='[{"id": 952, "user": {"login": "trusted-bot[bot]"}, "body": "FYI: Codex Review: Didn'\''t find any major issues here"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_CLEAN_NOTPREFIX"); rc=$?
assert "marker not at body start still blocks (prefix match only)" "[ \$rc -eq 1 ]"

# (4) An unrelated bot comment still blocks — bot identity alone is never
# the exemption, only bot identity + marker together
IC_BOT_OTHER='[{"id": 953, "user": {"login": "trusted-bot[bot]"}, "body": "please rename this variable"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_BOT_OTHER"); rc=$?
assert "unrelated bot comment still blocks" "[ \$rc -eq 1 ]"

# (5) Trigger comment authored by the PR author → excluded, eligible
PR_AUTHOR_JSON='{"state":"open","head":{"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"base":{"ref":"main","sha":"cccccccccccccccccccccccccccccccccccccccc"},"created_at":"2026-01-01T00:00:00Z","user":{"login":"pr-author"}}'
IC_TRIGGER_AUTHOR='[{"id": 960, "user": {"login": "pr-author"}, "body": "@codex review"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_PR="$PR_AUTHOR_JSON" FIXTURE_ISSUE_COMMENTS="$IC_TRIGGER_AUTHOR"); rc=$?
assert "trigger comment from PR author excluded → eligible" "[ \$rc -eq 0 ]"

# (6) Trigger comment authored by the authenticated session identity (the
# CLI's own re-ask) → excluded, eligible. Default FIXTURE_PR carries no
# `user`, so $pr_author is empty here — isolates the auth-login match.
IC_TRIGGER_SESSION='[{"id": 961, "user": {"login": "session-user"}, "body": "@codex review"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_TRIGGER_SESSION"); rc=$?
assert "trigger comment from authenticated session identity excluded → eligible" "[ \$rc -eq 0 ]"

# (7) Trigger comment from neither identity still blocks
IC_TRIGGER_OTHER='[{"id": 962, "user": {"login": "operator"}, "body": "@codex review"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC_TRIGGER_OTHER"); rc=$?
assert "trigger comment from unrelated identity still blocks" "[ \$rc -eq 1 ]"

# (8) The trigger phrase must be at the body start too — not a substring
IC_TRIGGER_NOTPREFIX='[{"id": 963, "user": {"login": "pr-author"}, "body": "please do @codex review this again"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_PR="$PR_AUTHOR_JSON" FIXTURE_ISSUE_COMMENTS="$IC_TRIGGER_NOTPREFIX"); rc=$?
assert "trigger phrase not at body start still blocks (not a substring match)" "[ \$rc -eq 1 ]"

# (8b) The body must be EXACTLY the trigger phrase, not merely start with it —
# a prefix match would let real feedback appended after "@codex review" ride
# through unexamined (Codex review finding on PR #335, round 1).
IC_TRIGGER_PLUS_FEEDBACK='[{"id": 964, "user": {"login": "pr-author"}, "body": "@codex review — please also fix the race described below"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_PR="$PR_AUTHOR_JSON" FIXTURE_ISSUE_COMMENTS="$IC_TRIGGER_PLUS_FEEDBACK"); rc=$?
assert "trigger phrase plus appended feedback still blocks (exact match only)" "[ \$rc -eq 1 ]"

# (9) A failed `gh api user` lookup never aborts the run (it does not gate
# eligibility) — it degrades AUTH_LOGIN to an unmatchable empty string, so
# the session-identity exemption just doesn't fire and the comment blocks
# like any other untriaged item (fail closed).
out=$(run_script "$BASE_POLICY" FIXTURE_AUTH_LOGIN_FAIL=1 FIXTURE_ISSUE_COMMENTS="$IC_TRIGGER_SESSION"); rc=$?
assert "authenticated-identity lookup failure does not abort the script" "[ \$rc -ne 3 ]"
assert "authenticated-identity lookup failure degrades the exemption (blocks)" "[ \$rc -eq 1 ]"

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
slash_pr=$(jq -n --arg t "2026-01-01T00:00:00Z" --arg sha "$HEAD_SHA" --arg base "$BASE_SHA" \
  '{state:"open", head:{sha:$sha}, base:{ref:"release/1.0", sha:$base}, created_at:$t}')
out=$(run_script "$BASE_POLICY" FIXTURE_PR="$slash_pr" FIXTURE_PROTECTION_404=0 \
      FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_ok)" \
      FIXTURE_BASE_REF_ENCODED="release%2F1.0"); rc=$?
assert "base ref with a slash resolves protection via the url-encoded path" \
  "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = green ]"

# ── Spec: both Axis-1 expectations simultaneously ────────────────────────────
BOTH_POLICY=$(jq -c '.bot_review_expected = true | .human_approvers_required = 1' <<<"$BASE_POLICY")
recent_pr=$(jq -n --arg t "$TS_RECENT" --arg sha "$HEAD_SHA" --arg base "$BASE_SHA" \
  '{state:"open", head:{sha:$sha}, base:{ref:"main", sha:$base}, created_at:$t}')

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

# ── bot_review_cap_exhausted: head-prefix glob, fail-closed ──────────────────
# write_inv's schema hardcodes polling: {} (Task 17), so it can't express
# polling.bot_review_cap_exhausted — write these inventories directly instead.
write_cap_inv() {  # write_cap_inv <filename> <polling-json>
  jq -n --argjson polling "$2" '{schema_version: 1, pr: {}, polling: $polling, items: []}' \
    > "$INV_DIR/$1"
}
HEAD12="${HEAD_SHA:0:12}"

# production convention: detect-pr-context.sh writes 12-char truncated-sha
# filenames — the reader MUST see these (regression pin for the dead read
# path that only matched a full-40-char filename no live writer produces)
write_cap_inv "o-r-1-${HEAD12}.json" '{"bot_review_cap_exhausted":true}'
out=$(run_script "$BASE_POLICY")
assert "cap true in 12-char-sha inventory (production convention) → fact true" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"
rm -f "$INV_DIR/o-r-1-${HEAD12}.json"

# LegacyExportStore convention: full 40-char sha shares the 12-char prefix,
# so the same head-scoped glob covers prgroom's writer
write_cap_inv "o-r-1-${HEAD_SHA}.json" '{"bot_review_cap_exhausted":true}'
out=$(run_script "$BASE_POLICY")
assert "cap true in full-sha inventory (LegacyExportStore convention) → fact true" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"
rm -f "$INV_DIR/o-r-1-${HEAD_SHA}.json"

# ad-hoc suffixed artifact (the PR #256 incident's manually written -r3 file):
# tolerated as robustness — no writer constructs suffixed names
write_cap_inv "o-r-1-${HEAD12}-r3.json" '{"bot_review_cap_exhausted":true}'
out=$(run_script "$BASE_POLICY")
assert "cap true in ad-hoc suffixed inventory → fact true (tolerated)" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"
rm -f "$INV_DIR/o-r-1-${HEAD12}-r3.json"

# OR across matching files: once the budget is spent at a head nothing at the
# same head can un-spend it — a false sibling must not mask a true one
write_cap_inv "o-r-1-${HEAD12}.json" '{"bot_review_cap_exhausted":false}'
write_cap_inv "o-r-1-${HEAD12}-r3.json" '{"bot_review_cap_exhausted":true}'
out=$(run_script "$BASE_POLICY")
assert "false + true siblings at same head OR to true" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"
rm -f "$INV_DIR/o-r-1-${HEAD12}.json" "$INV_DIR/o-r-1-${HEAD12}-r3.json"

# present-false
write_cap_inv "o-r-1-${HEAD12}.json" '{"bot_review_cap_exhausted":false}'
out=$(run_script "$BASE_POLICY")
assert "cap exhausted false → fact false" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"
rm -f "$INV_DIR/o-r-1-${HEAD12}.json"

# type-strict: a JSON STRING "true" must NOT satisfy the boolean gate.
# jq -r prints both boolean true and string "true" as the bare word `true`,
# so a bash string compare would fail-OPEN on a string. This authorization
# escape hatch must only unlock on a real JSON boolean true.
write_cap_inv "o-r-1-${HEAD12}.json" '{"bot_review_cap_exhausted":"true"}'
out=$(run_script "$BASE_POLICY")
assert "cap exhausted string \"true\" → fact false (type-strict)" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"
rm -f "$INV_DIR/o-r-1-${HEAD12}.json"

# field absent → false
write_cap_inv "o-r-1-${HEAD12}.json" '{"copilot_status":"timeout"}'
out=$(run_script "$BASE_POLICY")
assert "field absent → fact false" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"
rm -f "$INV_DIR/o-r-1-${HEAD12}.json"

# inventory absent → false
out=$(run_script "$BASE_POLICY")
assert "inventory absent → fact false" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"

# malformed current-head inventory → false (fail-closed); write raw non-JSON
# content directly since write_cap_inv always emits valid JSON
printf 'not json' > "$INV_DIR/o-r-1-${HEAD12}.json"
out=$(run_script "$BASE_POLICY")
assert "malformed current-head inventory → fact false" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"
rm -f "$INV_DIR/o-r-1-${HEAD12}.json"

# malformed file must not abort the scan — a readable true sibling still wins
printf 'not json' > "$INV_DIR/o-r-1-${HEAD12}.json"
write_cap_inv "o-r-1-${HEAD12}-r2.json" '{"bot_review_cap_exhausted":true}'
out=$(run_script "$BASE_POLICY")
assert "malformed sibling skipped, readable true still resolves → fact true" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"
rm -f "$INV_DIR/o-r-1-${HEAD12}.json" "$INV_DIR/o-r-1-${HEAD12}-r2.json"

# STALE-HEAD GUARD: a prior-head inventory with exhausted=true must NOT leak
# onto the current head when the current-head inventory is absent. This is
# the regression guard for the "bot timeout ≈ implicit approval" fail-open
# bug this feature exists to prevent. Different 12-char prefix ⇒ no match.
write_cap_inv "o-r-1-bbbbbbbbbbbb1234.json" '{"bot_review_cap_exhausted":true}'
out=$(run_script "$BASE_POLICY")
assert "stale prior-head exhausted does NOT leak → fact false" "[ \"\$(jq '.facts.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"
rm -f "$INV_DIR/o-r-1-bbbbbbbbbbbb1234.json"

# ── Spec 2026-07-16: triage-aware thread partition (abn9.8.34) ───────────────
# Live unresolved threads are partitioned against completed-inventory triage:
# ESCALATE → escalations_pending; all-SKIP-with-posted-reply → excluded;
# everything else (untriaged / unresolved-FIX / unposted-SKIP) → blocks.
export_threads_ids() {  # export_threads_ids <id:resolved>... ; id "-" → null id
  export_threads_ids_page false "" "$@"
}
export_threads_ids_page() {  # export_threads_ids_page <hasNextPage> <endCursor|""> <id:resolved>...
  local has="$1" cur="$2"; shift 2
  local nodes; nodes=$(printf '%s\n' "$@" | jq -R 'split(":") | {id: (if .[0] == "-" then null else .[0] end), isResolved: (.[1] == "true")}' | jq -s .)
  local cur_json=null; [ -n "$cur" ] && cur_json=$(jq -n --arg c "$cur" '$c')
  jq -n --argjson n "$nodes" --argjson h "$has" --argjson c "$cur_json" \
    '{data:{repository:{pullRequest:{reviewThreads:{pageInfo:{hasNextPage:$h,endCursor:$c},nodes:$n}}}}}'
}
esc_details() { jq -r '.blockers[] | select(.code == "escalations_pending") | .details' <<<"$1"; }
thr_details() { jq -r '.blockers[] | select(.code == "unresolved_threads") | .details' <<<"$1"; }

clean_invs; clean_sidecars

# untriaged: unresolved thread with no record in any completed inventory
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "untriaged unresolved thread → unresolved_threads blocker" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q unresolved_threads"
assert "untriaged thread counted in breakdown" "thr_details \"\$out\" | grep -q '1 untriaged'"
assert "thread_triage fact: 1 live, 1 blocking" \
  "[ \"\$(jq '.facts.thread_triage.live_unresolved' <<<\"\$out\")\" = 1 ] && [ \"\$(jq '.facts.thread_triage.blocking' <<<\"\$out\")\" = 1 ]"

# a GraphQL node with a null id can never be matched to triage → blocks as untriaged
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids -:false)"); rc=$?
assert "null-id unresolved thread blocks as untriaged" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q unresolved_threads"

# SKIP with a posted reply in a completed inventory → excluded, eligible
write_inv "o-r-1-thr0001.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"SKIP","rationale":"cosmetic pushback","fix_outcome":null,"posted_reply_id":9001}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "SKIP+posted-reply thread excluded → eligible" "[ \$rc -eq 0 ]"
assert "skip_excluded counted in thread_triage" \
  "[ \"\$(jq '.facts.thread_triage.skip_excluded' <<<\"\$out\")\" = 1 ] && [ \"\$(jq '.facts.thread_triage.blocking' <<<\"\$out\")\" = 0 ]"
clean_invs

# SKIP whose reply never posted → still blocks (argument never reached reviewer)
write_inv "o-r-1-thr0002.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"SKIP","rationale":"cosmetic","fix_outcome":null,"posted_reply_id":null}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "SKIP without posted reply → unresolved_threads" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q unresolved_threads"
assert "unposted-SKIP named in breakdown" "thr_details \"\$out\" | grep -q '1 unposted-SKIP'"
clean_invs

# ESCALATE (wait-for-pr-comments shape: escalation_filed + rationale) →
# escalations_pending, NOT unresolved_threads
write_inv "o-r-1-thr0003.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"ESCALATE","escalation_filed":true,"rationale":"needs human ruling on API shape","fix_outcome":null,"posted_reply_id":9002}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "ESCALATE thread → escalations_pending blocker" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q escalations_pending"
assert "ESCALATE thread NOT in unresolved_threads" \
  "! jq -r '.blockers[].code' <<<\"\$out\" | grep -q unresolved_threads"
assert "escalation details carry thread id and rationale" \
  "esc_details \"\$out\" | grep -q 'T1' && esc_details \"\$out\" | grep -q 'needs human ruling'"
clean_invs

# ESCALATE (prgroom LegacyExportStore shape: no escalation_filed, no rationale
# keys) lands in the same bucket — routing keys on classification alone
write_inv "o-r-1-thr0004.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"ESCALATE","fix_outcome":null,"posted_reply_id":9003}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "LegacyExportStore-shape ESCALATE → escalations_pending" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q escalations_pending"
assert "missing rationale reads '(no rationale recorded)'" \
  "esc_details \"\$out\" | grep -q '(no rationale recorded)'"
clean_invs

# non-string rationale (number) from a malformed/hand-edited inventory: the
# formatter must coerce before slicing, not let jq abort under set -e
write_inv "o-r-1-thr0004b.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"ESCALATE","escalation_filed":true,"rationale":42,"fix_outcome":null,"posted_reply_id":9013}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "numeric rationale → escalations_pending (no abort)" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q escalations_pending"
assert "numeric rationale coerced into details" "esc_details \"\$out\" | grep -q '42'"
clean_invs

# non-string rationale (object) is equally type-robust
write_inv "o-r-1-thr0004c.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"ESCALATE","escalation_filed":true,"rationale":{"note":"x"},"fix_outcome":null,"posted_reply_id":9014}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "object rationale → escalations_pending (no abort)" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q escalations_pending"
clean_invs

# ESCALATE beats coexisting SKIP records for the same thread (no reliable
# cross-round ordering → fail toward human attention)
write_inv "o-r-1-thr0005.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"ESCALATE","escalation_filed":true,"rationale":"human question","fix_outcome":null,"posted_reply_id":9004}]'
write_inv "o-r-1-thr0006.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"SKIP","rationale":"skip it","fix_outcome":null,"posted_reply_id":9005}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "ESCALATE record beats SKIP record for the same thread" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q escalations_pending"
clean_invs

# one thread, two comments (two items, same thread_id), both SKIP+posted → excluded
write_inv "o-r-1-thr0007.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"SKIP","rationale":"a","fix_outcome":null,"posted_reply_id":9006},
    {"kind":"review_thread","thread_id":"T1","reply_to_comment_id":502,"classification":"SKIP","rationale":"b","fix_outcome":null,"posted_reply_id":9007}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "multi-item thread, all SKIP+posted → excluded, eligible" "[ \$rc -eq 0 ]"
clean_invs

# one thread, SKIP+posted item and FIX/committed item, thread still unresolved
# → blocks (an unresolved FIX is actionable — the fix flow should have resolved it)
write_inv "o-r-1-thr0008.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"SKIP","rationale":"a","fix_outcome":null,"posted_reply_id":9008},
    {"kind":"review_thread","thread_id":"T1","reply_to_comment_id":502,"classification":"FIX","rationale":"b","fix_outcome":"committed","fix_commit_sha":"abc","posted_reply_id":9009}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "mixed SKIP+FIX thread still unresolved → unresolved_threads" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q unresolved_threads"
assert "unresolved-FIX named in breakdown" "thr_details \"\$out\" | grep -q '1 unresolved-FIX'"
clean_invs

# a SKIP recorded only in a partial-crash (incomplete) inventory does not count
write_inv_partial "o-r-1-thr0009.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"SKIP","rationale":"a","fix_outcome":null,"posted_reply_id":9010}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false)"); rc=$?
assert "SKIP only in incomplete inventory → still blocks (completed-only discipline)" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q unresolved_threads"
clean_invs

# live enumeration wins: thread resolved on GitHub, stale ESCALATE record remains
write_inv "o-r-1-thr0010.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"ESCALATE","escalation_filed":true,"rationale":"ruled","fix_outcome":null,"posted_reply_id":9011}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:true)"); rc=$?
assert "resolved-on-GitHub thread with stale ESCALATE record → no blocker" "[ \$rc -eq 0 ]"
assert "resolved thread not counted live" "[ \"\$(jq '.facts.thread_triage.live_unresolved' <<<\"\$out\")\" = 0 ]"
clean_invs

# partition across pages: SKIP-excluded thread on page 1, untriaged on page 2
write_inv "o-r-1-thr0011.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"SKIP","rationale":"a","fix_outcome":null,"posted_reply_id":9012}]'
p1=$(export_threads_ids_page true CURSOR1 T1:false)
p2=$(export_threads_ids_page false "" T2:false)
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$p1" FIXTURE_GRAPHQL_THREADS_PAGE2="$p2"); rc=$?
assert "cross-page partition: only the untriaged page-2 thread blocks" \
  "[ \$rc -eq 1 ] && jq -r '.blockers[].code' <<<\"\$out\" | grep -q unresolved_threads && ! jq -r '.blockers[].code' <<<\"\$out\" | grep -q escalations_pending"
assert "cross-page counts: 2 live, 1 skip-excluded, 1 blocking" \
  "[ \"\$(jq '.facts.thread_triage.live_unresolved' <<<\"\$out\")\" = 2 ] && [ \"\$(jq '.facts.thread_triage.skip_excluded' <<<\"\$out\")\" = 1 ] && [ \"\$(jq '.facts.thread_triage.blocking' <<<\"\$out\")\" = 1 ]"
clean_invs

# PR #256 composite (AC): 1 posted SKIP + 2 filed ESCALATEs, nothing else →
# exactly one blocker, escalations_pending, with both ids and rationales
write_inv "o-r-1-thr0012.json" \
  '[{"kind":"review_thread","thread_id":"T1","reply_to_comment_id":501,"classification":"SKIP","rationale":"defensible pushback","fix_outcome":null,"posted_reply_id":9013},
    {"kind":"review_thread","thread_id":"T2","reply_to_comment_id":502,"classification":"ESCALATE","escalation_filed":true,"rationale":"design question A","fix_outcome":null,"posted_reply_id":9014},
    {"kind":"review_thread","thread_id":"T3","reply_to_comment_id":503,"classification":"ESCALATE","escalation_filed":true,"rationale":"design question B","fix_outcome":null,"posted_reply_id":9015}]'
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false T2:false T3:false)"); rc=$?
assert "PR#256 state: exactly one blocker" "[ \$rc -eq 1 ] && [ \"\$(jq '.blockers | length' <<<\"\$out\")\" = 1 ]"
assert "PR#256 state: the blocker is escalations_pending" \
  "jq -r '.blockers[].code' <<<\"\$out\" | grep -q escalations_pending"
assert "PR#256 state: both thread ids and rationales in details" \
  "esc_details \"\$out\" | grep -q 'T2' && esc_details \"\$out\" | grep -q 'T3' && esc_details \"\$out\" | grep -q 'design question A' && esc_details \"\$out\" | grep -q 'design question B'"
assert "PR#256 counts: 3 live = 1 skip + 2 escalations + 0 blocking" \
  "[ \"\$(jq '.facts.thread_triage.live_unresolved' <<<\"\$out\")\" = 3 ] && [ \"\$(jq '.facts.thread_triage.skip_excluded' <<<\"\$out\")\" = 1 ] && [ \"\$(jq '.facts.thread_triage.escalations_pending' <<<\"\$out\")\" = 2 ] && [ \"\$(jq '.facts.thread_triage.blocking' <<<\"\$out\")\" = 0 ]"

# …and after a human resolves both escalated threads on GitHub → eligible
out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads_ids T1:false T2:true T3:true)"); rc=$?
assert "PR#256 after human resolves escalated threads → eligible" "[ \$rc -eq 0 ]"
clean_invs

# ── Component 2: reaction clean-pass path (2026-07-18 spec) ─────────────────
# docs/specs/2026-07-18-codex-rereview-path-design.md — bot_clean_review_at_head
# extends to a disjunction: (a) the existing review path, OR (b) a reaction
# path that is the only artifact Codex leaves on an auto/push-triggered clean
# pass. bot_clean_signal_source records which path (if either) fired.
mk_reaction() {  # mk_reaction <login> <content> <created_at> [type] [id]
  jq -n --arg l "$1" --arg c "$2" --arg t "$3" --arg ty "${4:-Bot}" --argjson id "${5:-42}" \
    '{id: $id, content: $c, user: {login: $l, type: $ty}, created_at: $t}'
}
mk_commit() {  # mk_commit <committer-date-or-"null">
  if [ "$1" = "null" ]; then
    jq -n '{commit:{committer:{date:null}}}'
  else
    jq -n --arg d "$1" '{commit:{committer:{date:$d}}}'
  fi
}
mk_fp_event() {  # mk_fp_event <created_at>
  jq -n --arg t "$1" '{event:"head_ref_force_pushed", created_at:$t}'
}
pr_with_head() {  # pr_with_head <sha>
  jq -n --arg sha "$1" --arg base "$BASE_SHA" \
    '{state:"open", head:{sha:$sha}, base:{ref:"main", sha:$base}, created_at:"2026-01-01T00:00:00Z"}'
}

COMMIT_TS="2026-01-01T00:00:00Z"           # head commit's committer date
PLUS1_TS_OK="2026-01-01T01:00:00Z"         # post-dates COMMIT_TS
PLUS1_TS_STALE="2025-12-31T23:00:00Z"      # pre-dates COMMIT_TS
FORCEPUSH_TS="2026-01-01T02:00:00Z"        # post-dates PLUS1_TS_OK
COMMIT_FIXTURE="$(mk_commit "$COMMIT_TS")"

# reaction path alone → true, source "reaction"
reacts=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "$PLUS1_TS_OK" Bot 99)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "reaction path alone → bot_clean_review_at_head true" \
  "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = true ]"
assert "reaction path alone → signal source reaction" \
  "[ \"\$(jq -r '.facts.bot_clean_signal_source' <<<\"\$out\")\" = reaction ]"
assert "reaction path alone → bot_reviewed_by is the reactor" \
  "[ \"\$(jq -r '.facts.bot_reviewed_by' <<<\"\$out\")\" = 'trusted-bot[bot]' ]"
assert "reaction path alone → bot_clean_reaction carries id and created_at (audit trail)" \
  "[ \"\$(jq -c '.facts.bot_clean_reaction' <<<\"\$out\")\" = '{\"id\":99,\"created_at\":\"$PLUS1_TS_OK\"}' ]"

# review path alone → true, source "review" (companion fact regression pin)
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "review path alone → signal source review" \
  "[ \"\$(jq -r '.facts.bot_clean_signal_source' <<<\"\$out\")\" = review ]"
assert "review path alone → bot_clean_reaction is null (no audit trail to fabricate)" \
  "[ \"\$(jq '.facts.bot_clean_reaction' <<<\"\$out\")\" = null ]"

# both present → source reads "review" (review wins over reaction), and the
# reaction audit trail stays null — the announcement has no reaction to cite
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs" FIXTURE_REACTIONS="$reacts" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "both paths present → fact true" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = true ]"
assert "both paths present → source review wins" \
  "[ \"\$(jq -r '.facts.bot_clean_signal_source' <<<\"\$out\")\" = review ]"
assert "both paths present → bot_reviewed_by is the reviewer, not the reactor" \
  "[ \"\$(jq -r '.facts.bot_reviewed_by' <<<\"\$out\")\" = 'trusted-bot[bot]' ]"
assert "both paths present → bot_clean_reaction null (review wins, no reaction cited)" \
  "[ \"\$(jq '.facts.bot_clean_reaction' <<<\"\$out\")\" = null ]"

# neither → false, source "none"
out=$(run_script "$BASE_POLICY" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "neither path → fact false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"
assert "neither path → signal source none" \
  "[ \"\$(jq -r '.facts.bot_clean_signal_source' <<<\"\$out\")\" = none ]"

# +1 predating the head commit's committer date → false
reacts_stale=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "$PLUS1_TS_STALE")" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts_stale" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "+1 predating committer date → false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# +1 predating a LATER head_ref_force_pushed timeline event → false
tl=$(jq -n --argjson a "$(mk_fp_event "$FORCEPUSH_TS")" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts" FIXTURE_COMMIT="$COMMIT_FIXTURE" FIXTURE_TIMELINE="$tl")
assert "+1 predating a later force-push event → false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# head_ref_force_pushed event on a LATER timeline page → pagination must
# still surface it (page 1 alone would wrongly read true)
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts" FIXTURE_COMMIT="$COMMIT_FIXTURE" \
      FIXTURE_TIMELINE='[]' FIXTURE_TIMELINE_PAGE2="$tl")
assert "force-push event on timeline page 2 still surfaces (pagination) → false" \
  "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# +1 from an identity outside the allowlist → false
reacts_untrusted=$(jq -n --argjson a "$(mk_reaction 'evil-bot[bot]' '+1' "$PLUS1_TS_OK")" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts_untrusted" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "+1 from untrusted identity → false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# +1 from an allowlisted login whose user.type is "User" → still true. GitHub
# reports "User" for the live chatgpt-codex-connector[bot] on this endpoint
# (verified 2026-07-19); the login allowlist is the trust boundary, not type.
reacts_nonbot=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "$PLUS1_TS_OK" User)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts_nonbot" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "+1 from allowlisted login with user.type=User still recognized (field-verified Codex behavior)" \
  "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = true ]"

# eyes present from a DIFFERENT allowlisted identity than the +1's → still blocks
BOT_POLICY_2=$(jq -c '.bot_reviewers = ["trusted-bot[bot]", "second-bot[bot]"]' <<<"$BASE_POLICY")
reacts_eyes_other=$(jq -n \
  --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "$PLUS1_TS_OK")" \
  --argjson b "$(mk_reaction 'second-bot[bot]' eyes "$PLUS1_TS_OK")" '[$a,$b]')
out=$(run_script "$BOT_POLICY_2" FIXTURE_REACTIONS="$reacts_eyes_other" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "eyes from a different allowlisted identity still blocks" \
  "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# eyes arriving on the SECOND PAGE of the reactions fetch → pagination must
# still surface it (page 1 alone, with just the +1, would wrongly read true)
eyes_page2=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' eyes "$PLUS1_TS_OK")" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts" FIXTURE_REACTIONS_PAGE2="$eyes_page2" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "eyes on reactions page 2 still surfaces (pagination) → false" \
  "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# head OID moved between the reactions fetch and the re-read → reject
moved_pr=$(pr_with_head bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts" FIXTURE_COMMIT="$COMMIT_FIXTURE" FIXTURE_PR_REREAD="$moved_pr")
assert "head moved between reactions fetch and re-read → false (fail closed)" \
  "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# missing committer date → false (no FIXTURE_COMMIT set; stub default is null)
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts")
assert "missing committer date → false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# unparseable reaction timestamp → false
reacts_bad_ts=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' 'not-a-date')" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts_bad_ts" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "unparseable +1 timestamp → false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# a +1 whose created_at EQUALS last_head_change to the exact second must be
# rejected — the predicate requires strict >, pinning that a future refactor
# can't accidentally loosen it to >=
reacts_exact_ts=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "$COMMIT_TS")" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS="$reacts_exact_ts" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "+1 created_at equal to last_head_change → false (strict >, not >=)" \
  "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# a failing reactions fetch is infrastructure error, not a false fact — the
# whole script exits 3 (fail-closed `gh_api ... || { ...; exit 3; }` idiom),
# same as every other required fetch in this file
out=$(run_script "$BASE_POLICY" FIXTURE_REACTIONS_FAIL=1 FIXTURE_COMMIT="$COMMIT_FIXTURE"); rc=$?
assert "reactions fetch failure exits 3 (fail-closed, infrastructure error)" "[ \$rc -eq 3 ]"

# empty allowlist → reaction path false
EMPTY_ALLOWLIST_POLICY=$(jq -c '.bot_reviewers = []' <<<"$BASE_POLICY")
out=$(run_script "$EMPTY_ALLOWLIST_POLICY" FIXTURE_REACTIONS="$reacts" FIXTURE_COMMIT="$COMMIT_FIXTURE")
assert "empty bot_reviewers allowlist → reaction path false" \
  "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"
assert "empty bot_reviewers allowlist → signal source none" \
  "[ \"\$(jq -r '.facts.bot_clean_signal_source' <<<\"\$out\")\" = none ]"

# ── review_summary ratchet (2026-07-18 spec, Component 2b continuation) ──────
# Each Codex re-review round mints a brand-new review_id, so a triaged round's
# disposition never covers the next round's review object. A fresh
# reaction_clean signal (never bot_clean_review_at_head, which would also
# admit the review path) retroactively clears any review_summary item whose
# submitted_at strictly predates the reaction's created_at — no per-round
# bookkeeping. clean_invs/clean_sidecars first: no leftover disposition from
# earlier Task 17 cases should leak into this section.
clean_invs; clean_sidecars
mk_review_summary() {  # mk_review_summary <id> <submitted_at> [login] [body]
  jq -n --argjson id "$1" --arg t "$2" --arg l "${3:-trusted-bot[bot]}" \
    --arg b "${4:-please address this finding}" --arg head "$HEAD_SHA" \
    '{id: $id, user: {login: $l, type: "Bot"}, state: "COMMENTED",
      commit_id: $head, submitted_at: $t, body: $b}'
}

# (1) stale review_summary (no disposition) + a LATER genuinely-clean reaction
# at head → auto-cleared, eligible.
r1=$(mk_review_summary 401 "2026-01-01T01:00:00Z")
revs1=$(jq -n --argjson a "$r1" '[$a]')
reacts1=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "2026-01-01T02:00:00Z")" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs1" FIXTURE_REACTIONS="$reacts1" FIXTURE_COMMIT="$COMMIT_FIXTURE"); rc=$?
assert "stale review_summary superseded by a later clean reaction → eligible" "[ \$rc -eq 0 ]"

# (2) TRAP CASE — review_summary submitted_at is AFTER the reaction's
# created_at (a later round found something after an earlier clean
# attestation) → stays untriaged, still blocks. Must never regress.
r2=$(mk_review_summary 402 "2026-01-01T03:00:00Z")
revs2=$(jq -n --argjson a "$r2" '[$a]')
reacts2=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "2026-01-01T02:00:00Z")" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs2" FIXTURE_REACTIONS="$reacts2" FIXTURE_COMMIT="$COMMIT_FIXTURE"); rc=$?
assert "review_summary AFTER the clean reaction is never masked → still blocks" "[ \$rc -eq 1 ]"
assert "review_summary AFTER the clean reaction → blocker code untriaged_feedback" \
  "jq -r '.blockers[].code' <<<\"\$out\" | grep -q untriaged_feedback"

# (3) Regression: an EXISTING terminal disposition (FIX/committed or SKIP)
# stays cleared regardless of reaction timing — no reaction fixture at all.
clean_invs
r3=$(mk_review_summary 403 "2026-01-01T01:00:00Z")
revs3=$(jq -n --argjson a "$r3" '[$a]')
write_inv "o-r-1-ratchet0001.json" '[{"kind":"review_summary","review_id":403,"classification":"SKIP","rationale":"cosmetic","fix_outcome":null}]'
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs3"); rc=$?
assert "existing terminal disposition clears regardless of reaction timing (unchanged)" "[ \$rc -eq 0 ]"
clean_invs

# (4) Multiple stale review_summary items from different earlier rounds, all
# predating ONE fresh clean reaction → ALL cleared by that single reaction.
r4a=$(mk_review_summary 404 "2026-01-01T01:00:00Z")
r4b=$(mk_review_summary 405 "2026-01-01T01:30:00Z")
revs4=$(jq -n --argjson a "$r4a" --argjson b "$r4b" '[$a,$b]')
reacts4=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "2026-01-01T02:00:00Z")" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs4" FIXTURE_REACTIONS="$reacts4" FIXTURE_COMMIT="$COMMIT_FIXTURE"); rc=$?
assert "one fresh clean reaction clears multiple earlier-round review_summary items" "[ \$rc -eq 0 ]"

# (5) No reaction_clean at all — review path won instead (bot_clean_review_at_head
# true via review, not reaction) — the new clearing condition must never fire
# off the review path; a findings-bearing review_summary still blocks.
r5=$(mk_review_summary 406 "2026-01-01T01:00:00Z")
r5_clean=$(mk_review 'trusted-bot[bot]' APPROVED "$HEAD_SHA" "2026-01-01T03:00:00Z")
revs5=$(jq -n --argjson a "$r5" --argjson b "$r5_clean" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs5"); rc=$?
assert "clean signal via the review path (not reaction) never clears a review_summary" "[ \$rc -eq 1 ]"

# (6) Reaction-mutability regression: a +1 is present but does NOT satisfy
# reaction_clean (an `eyes` reaction from the same allowlisted identity makes
# the fact false) — a stale review_summary that would have been cleared stays
# untriaged/live. Proves the check is evaluated fresh from live GitHub state.
r6=$(mk_review_summary 407 "2026-01-01T01:00:00Z")
revs6=$(jq -n --argjson a "$r6" '[$a]')
reacts6=$(jq -n \
  --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "2026-01-01T02:00:00Z")" \
  --argjson b "$(mk_reaction 'trusted-bot[bot]' eyes "2026-01-01T02:00:00Z")" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs6" FIXTURE_REACTIONS="$reacts6" FIXTURE_COMMIT="$COMMIT_FIXTURE"); rc=$?
assert "a +1 that fails reaction_clean (eyes present) never clears a stale review_summary" "[ \$rc -eq 1 ]"

# (7) Boundary: reaction created_at EXACTLY EQUAL to the review's submitted_at
# (same second) → must NOT clear (strict </>, matching the tie-breaking
# convention used throughout the reaction-path fact above).
r7=$(mk_review_summary 408 "2026-01-01T02:00:00Z")
revs7=$(jq -n --argjson a "$r7" '[$a]')
reacts7=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "2026-01-01T02:00:00Z")" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs7" FIXTURE_REACTIONS="$reacts7" FIXTURE_COMMIT="$COMMIT_FIXTURE"); rc=$?
assert "reaction created_at exactly equal to review submitted_at → does not clear (strict <)" "[ \$rc -eq 1 ]"

# (8) Codex review finding on PR #339: a human (non-allowlisted) reviewer's
# untriaged review_summary must NEVER clear off a Codex clean reaction —
# reaction_clean is Codex's own attestation about Codex's own findings, not
# a blanket "the PR is fine" signal. A human review with no disposition,
# submitted BEFORE a later Codex clean reaction, must still block.
r8=$(mk_review_summary 409 "2026-01-01T01:00:00Z" "human-reviewer")
revs8=$(jq -n --argjson a "$r8" '[$a]')
reacts8=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "2026-01-01T02:00:00Z")" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs8" FIXTURE_REACTIONS="$reacts8" FIXTURE_COMMIT="$COMMIT_FIXTURE"); rc=$?
assert "a human reviewer's untriaged review_summary is never cleared by Codex's reaction (author-scoped)" "[ \$rc -eq 1 ]"

# (9) Cross-identity trap: a policy trusting TWO bots (Codex + a second
# allowlisted identity). A findings-bearing review_summary from the SECOND
# bot must NOT be cleared by the FIRST bot's clean reaction — reaction_clean
# is scoped to the reacting identity specifically, not "any allowlisted
# bot". Without this, a Codex +1 could wrongly clear a stale Copilot
# findings review.
r9=$(mk_review_summary 410 "2026-01-01T01:00:00Z" "second-bot[bot]")
revs9=$(jq -n --argjson a "$r9" '[$a]')
reacts9=$(jq -n --argjson a "$(mk_reaction 'trusted-bot[bot]' '+1' "2026-01-01T02:00:00Z")" '[$a]')
out=$(run_script "$BOT_POLICY_2" FIXTURE_REVIEWS="$revs9" FIXTURE_REACTIONS="$reacts9" FIXTURE_COMMIT="$COMMIT_FIXTURE"); rc=$?
assert "a different allowlisted bot's untriaged review_summary is never cleared by another bot's reaction (identity-scoped, not allowlist-scoped)" "[ \$rc -eq 1 ]"

clean_invs

exit $FAIL

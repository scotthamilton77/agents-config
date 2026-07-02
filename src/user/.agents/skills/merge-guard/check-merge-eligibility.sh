#!/usr/bin/env bash
# check-merge-eligibility.sh — compute the no-blocker eligibility floor and the
# positive review facts for a PR, against a resolved review/merge policy.
#
# Contract: docs/architecture/review-merge-policy/design.md
#   - eligibility = the no-blocker floor (blockers[] empty)
#   - positive facts (bot clean review at head, distinct current approvers) are
#     emitted for merge-rule evaluation in merge-guard SKILL.md — they are
#     facts here, never blockers.
#
# Usage:
#   check-merge-eligibility.sh --owner <o> --repo <r> --pr <n> --policy-json '<json>'
#
# Inputs:
#   --policy-json   resolve_policy.py output (required — run the resolver first)
#
# Exit codes:
#   0 — eligible (no blockers)
#   1 — blocked (see .blockers[] in the JSON)
#   3 — error (auth, invalid args, network, invalid policy)
#
# Stdout (JSON):
#   { "status": "eligible|blocked", "head_ref_oid": "<sha>",
#     "blockers": [ {"code": "...", "details": "..."} ],
#     "facts": { ... }, "merge_command_hint": "gh pr merge <n> --squash --match-head-commit <sha>" }

set -euo pipefail

usage() {
    echo "Usage: $0 --owner <owner> --repo <repo> --pr <pr-number> --policy-json '<json>'" >&2
    exit 3
}

OWNER=""; REPO=""; PR=""; POLICY_JSON=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --owner)       [[ $# -ge 2 ]] || usage; OWNER="${2:-}";       shift 2 ;;
        --repo)        [[ $# -ge 2 ]] || usage; REPO="${2:-}";        shift 2 ;;
        --pr)          [[ $# -ge 2 ]] || usage; PR="${2:-}";          shift 2 ;;
        --policy-json) [[ $# -ge 2 ]] || usage; POLICY_JSON="${2:-}"; shift 2 ;;
        *) usage ;;
    esac
done
[[ -n "$OWNER" && -n "$REPO" && -n "$PR" && -n "$POLICY_JSON" ]] || usage
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "Error: --pr must be a positive integer" >&2; exit 3; }

# ── Policy parsing (fail loud on malformed/missing keys) ─────────────────────
if ! jq -e . >/dev/null 2>&1 <<<"$POLICY_JSON"; then
    echo "Error: --policy-json is not valid JSON" >&2; exit 3
fi
for key in bot_review_expected bot_reviewers bot_inactivity_timeout_seconds \
           human_approvers_required human_review_timeout_seconds \
           merge_authorization merge_rule; do
    jq -e --arg k "$key" 'has($k)' >/dev/null 2>&1 <<<"$POLICY_JSON" || {
        echo "Error: policy JSON missing key: $key (run resolve_policy.py)" >&2; exit 3; }
done
BOT_EXPECTED=$(jq -r '.bot_review_expected' <<<"$POLICY_JSON")
BOT_REVIEWERS=$(jq -c '.bot_reviewers' <<<"$POLICY_JSON")
BOT_TIMEOUT=$(jq -r '.bot_inactivity_timeout_seconds' <<<"$POLICY_JSON")
HUMANS_REQUIRED=$(jq -r '.human_approvers_required' <<<"$POLICY_JSON")
HUMAN_TIMEOUT=$(jq -r '.human_review_timeout_seconds' <<<"$POLICY_JSON")   # "null" = indefinite

# ── Helpers ──────────────────────────────────────────────────────────────────
gh_api() {
    local result exit_code=0
    result=$(gh api "$@" 2>/dev/null) || exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo "gh api failed (exit $exit_code): $*" >&2
        return 1
    fi
    printf '%s' "$result"
}

BLOCKERS='[]'
add_blocker() {  # add_blocker <code> <details>
    BLOCKERS=$(jq --arg c "$1" --arg d "$2" '. + [{code: $c, details: $d}]' <<<"$BLOCKERS")
}
FACTS='{}'
set_fact() {     # set_fact <key> <json-value>
    FACTS=$(jq --arg k "$1" --argjson v "$2" '.[$k] = $v' <<<"$FACTS")
}

# ── Pre-flight ───────────────────────────────────────────────────────────────
if ! gh auth status &>/dev/null; then
    echo "Error: gh auth failed — not authenticated" >&2; exit 3
fi
command -v jq &>/dev/null || { echo "Error: jq is required but not found" >&2; exit 3; }

PR_JSON=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}") || {
    echo "Error: failed to fetch PR #${PR}" >&2; exit 3; }
pr_state=$(jq -r '.state' <<<"$PR_JSON")
[[ "$pr_state" == "open" ]] || { echo "Error: PR #${PR} is ${pr_state}, not open" >&2; exit 3; }

# The head every positive fact binds to (Freshness invariant pt. 1) and the
# SHA the merge must be issued against (pt. 3).
HEAD_OID=$(jq -r '.head.sha' <<<"$PR_JSON")
[[ -n "$HEAD_OID" && "$HEAD_OID" != "null" ]] || { echo "Error: no head SHA on PR" >&2; exit 3; }
PR_CREATED=$(jq -r '.created_at' <<<"$PR_JSON")
BASE_REF=$(jq -r '.base.ref' <<<"$PR_JSON")

# Shared fetches (each gate filters this once-fetched data)
ALL_REVIEWS=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}/reviews?per_page=100" --paginate | jq -s 'add // []') || {
    echo "Error: failed to fetch reviews" >&2; exit 3; }

# Informational: pending requested reviewers (never a blocker by itself)
pending_json=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}/requested_reviewers") || pending_json='{"users":[],"teams":[]}'
set_fact pending_reviewers "$(jq '[(.users[].login), (.teams[].slug)]' <<<"$pending_json")"

# ── Gates (appended by later tasks) ──────────────────────────────────────────
# ── Fact: trusted-bot clean review at current head (bot-quiescence input) ────
# Exact-identity allowlist — never substring. Missing commit_id fails closed.
bot_fact=$(jq --argjson trusted "$BOT_REVIEWERS" --arg head "$HEAD_OID" '
    [ .[]
      | select(.user.login as $l | ($trusted | index($l)) != null)
      | select(.state != "DISMISSED")
      | select((.commit_id // "") == $head) ]
    | sort_by(.submitted_at) | last
    | if . == null then {clean: false, by: null}
      elif (.state == "APPROVED" or .state == "COMMENTED") then {clean: true, by: .user.login}
      else {clean: false, by: .user.login}
      end' <<<"$ALL_REVIEWS")
set_fact bot_clean_review_at_head "$(jq '.clean' <<<"$bot_fact")"
set_fact bot_reviewed_by "$(jq '.by' <<<"$bot_fact")"
# ── Blocker: active requested-changes verdict (sticky; never head-scoped) ────
# GitHub does not clear CHANGES_REQUESTED on push; only dismissal (state
# becomes DISMISSED) or a later APPROVED from the same reviewer clears it.
# COMMENTED is not a verdict change.
cr_logins=$(jq '
    group_by(.user.login)
    | map({
        login: .[0].user.login,
        cr: ([ .[] | select(.state == "CHANGES_REQUESTED") ] | sort_by(.submitted_at) | last),
        ok: ([ .[] | select(.state == "APPROVED") ] | sort_by(.submitted_at) | last)
      })
    | map(select(.cr != null and (.ok == null or .ok.submitted_at < .cr.submitted_at)))
    | map(.login)' <<<"$ALL_REVIEWS")
if [[ $(jq 'length' <<<"$cr_logins") -gt 0 ]]; then
    add_blocker requested_changes_active \
        "active CHANGES_REQUESTED from: $(jq -r 'join(", ")' <<<"$cr_logins") (cleared only by dismissal or a superseding APPROVED from the same reviewer)"
fi
# ── Fact: distinct current approvers (human-approvals rule input) ────────────
# One entry per non-bot login, latest review wins, APPROVED at current head
# only. Missing commit_id fails closed (does not count).
approvers=$(jq --arg head "$HEAD_OID" '
    [ .[] | select(.user.type != "Bot") ]
    | group_by(.user.login)
    | map(sort_by(.submitted_at) | last)
    | map(select(.state == "APPROVED" and (.commit_id // "") == $head))
    | map(.user.login)' <<<"$ALL_REVIEWS")
set_fact distinct_current_approvers "$(jq 'length' <<<"$approvers")"
set_fact approver_logins "$approvers"
APPROVER_COUNT=$(jq 'length' <<<"$approvers")
# ── Blocker: unresolved review threads (always live; prgroom is never a
#    substitute — a thread opened after prgroom quiesced is absent from state) ─
fetch_threads_page() {  # fetch_threads_page [cursor]
    if [[ $# -eq 0 ]]; then
        gh api graphql \
          -f query='query($owner:String!,$repo:String!,$pr:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$pr){reviewThreads(first:100){pageInfo{hasNextPage endCursor}nodes{isResolved}}}}}' \
          -f owner="$OWNER" -f repo="$REPO" -F pr="$PR" 2>/dev/null
    else
        gh api graphql \
          -f query='query($owner:String!,$repo:String!,$pr:Int!,$cursor:String!){repository(owner:$owner,name:$repo){pullRequest(number:$pr){reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor}nodes{isResolved}}}}}' \
          -f owner="$OWNER" -f repo="$REPO" -F pr="$PR" -f cursor="$1" 2>/dev/null
    fi
}
unresolved_threads=0
page=$(fetch_threads_page) || { echo "Error: reviewThreads query failed" >&2; exit 3; }
while :; do
    count=$(jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length' <<<"$page")
    unresolved_threads=$((unresolved_threads + count))
    has_next=$(jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage' <<<"$page")
    [[ "$has_next" == "true" ]] || break
    cursor=$(jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor' <<<"$page")
    page=$(fetch_threads_page "$cursor") || { echo "Error: reviewThreads pagination failed" >&2; exit 3; }
done
if [[ "$unresolved_threads" -gt 0 ]]; then
    add_blocker unresolved_threads "${unresolved_threads} unresolved review thread(s) on the PR"
fi
# ── Blocker: required CI checks not green ────────────────────────────────────
# Required set from branch protection — NEVER derived from the rollup (the
# rollup lists only contexts that already reported; filtering it would hide a
# required check that never started). 404 / no protection = empty set =
# vacuously green. A source-pinned (app_id) requirement is only satisfied by
# a run from that app — name alone is not a trust boundary.
prot=""
prot_stderr=$(mktemp)
if prot=$(gh api "repos/${OWNER}/${REPO}/branches/${BASE_REF}/protection/required_status_checks" 2>"$prot_stderr"); then
    :
else
    if grep -qiE 'HTTP 404|Not Found|Branch not protected' "$prot_stderr"; then
        prot=""   # no protection → empty required set
    else
        echo "Error: failed to fetch branch protection: $(cat "$prot_stderr")" >&2
        rm -f "$prot_stderr"; exit 3
    fi
fi
rm -f "$prot_stderr"
required_checks=$(jq -c '[.checks[]? | {context, app_id}]' <<<"${prot:-null}" 2>/dev/null || echo '[]')
[[ "$required_checks" == "null" ]] && required_checks='[]'

check_runs=$(gh_api "repos/${OWNER}/${REPO}/commits/${HEAD_OID}/check-runs?per_page=100" --paginate \
    | jq -s '[.[] | .check_runs[]? | {name, status, conclusion, app_id: (.app.id // null)}]') || {
    echo "Error: failed to fetch check runs" >&2; exit 3; }
legacy_statuses=$(gh_api "repos/${OWNER}/${REPO}/commits/${HEAD_OID}/status" \
    | jq '[.statuses[]? | {context, state}]') || legacy_statuses='[]'

ci_eval=$(jq -n --argjson req "$required_checks" --argjson runs "$check_runs" --argjson legacy "$legacy_statuses" '
    def red_conclusions: ["failure","cancelled","timed_out","action_required","startup_failure","stale"];
    def eval_one($r):
      ( [ $runs[] | select(.name == $r.context and ($r.app_id == null or .app_id == $r.app_id)) ]
        + ( if $r.app_id == null
            then [ $legacy[] | select(.context == $r.context)
                   | { name: .context, status: "legacy",
                       conclusion: (if .state == "success" then "success"
                                    elif (.state == "failure" or .state == "error") then "failure"
                                    else "pending" end) } ]
            else [] end) ) as $cands
      | if ($cands | length) == 0 then "pending"
        elif any($cands[]; (.conclusion // "") as $c | red_conclusions | index($c)) then "red"
        elif all($cands[]; ((.status == "completed") or (.status == "legacy"))
                           and ((.conclusion // "") as $c | ["success","skipped","neutral"] | index($c))) then "green"
        else "pending" end;
    if ($req | length) == 0 then {state: "none", not_green: []}
    else ([ $req[] | {context, result: eval_one(.)} ]) as $per
      | { state: (if any($per[]; .result == "red") then "red"
                  elif all($per[]; .result == "green") then "green"
                  else "pending" end),
          not_green: [ $per[] | select(.result != "green") | "\(.context) (\(.result))" ] }
    end')
set_fact ci_state "$(jq '.state' <<<"$ci_eval")"
ci_state=$(jq -r '.state' <<<"$ci_eval")
if [[ "$ci_state" != "green" && "$ci_state" != "none" ]]; then
    add_blocker ci_not_green \
        "required checks not green: $(jq -r '.not_green | join(", ")' <<<"$ci_eval") (pending/absent fails closed)"
fi
# ── Blocker: expected review still in flight ─────────────────────────────────
# A review that hasn't happened YET is otherwise indistinguishable from one
# that concluded clean — both read "no blocker" on every other row. Block
# until the expected review arrives at the current head or its wait window
# closes. Timing out ends the wait; it never satisfies the positive fact.
EVENTS=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/events?per_page=100" --paginate | jq -s 'add // []') || {
    echo "Error: failed to fetch issue events" >&2; exit 3; }

review_wait_bot="not_expected"
if [[ "$BOT_EXPECTED" == "true" ]]; then
    arrived=$(jq --argjson trusted "$BOT_REVIEWERS" --arg head "$HEAD_OID" '
        [ .[] | select((.user.login as $l | ($trusted | index($l)) != null)
                       and ((.commit_id // "") == $head)
                       and .state != "DISMISSED") ] | length' <<<"$ALL_REVIEWS")
    if [[ "$arrived" -gt 0 ]]; then
        review_wait_bot="satisfied"
    else
        latest_ref=$(jq -rn --argjson ev "$EVENTS" --argjson rv "$ALL_REVIEWS" \
            --argjson trusted "$BOT_REVIEWERS" --arg pr_created "$PR_CREATED" '
            ( [ $ev[] | select(.event == "review_requested"
                               and (((.requested_reviewer.login // "") as $l | ($trusted | index($l)) != null)))
                      | .created_at ]
            + [ $ev[] | select(.event == "copilot_work_started") | .created_at ]
            + [ $rv[] | select((.user.login as $l | ($trusted | index($l)) != null)) | .submitted_at ]
            + [ $pr_created ] ) | max')
        bot_age=$(jq -rn --arg ts "$latest_ref" '(now - ($ts | fromdateiso8601)) | floor')
        if [[ "$bot_age" -ge "$BOT_TIMEOUT" ]]; then
            review_wait_bot="timed_out"
        else
            review_wait_bot="waiting"
            add_blocker review_in_flight \
                "bot review expected but not arrived at head; last activity ${bot_age}s ago < inactivity timeout ${BOT_TIMEOUT}s"
        fi
    fi
fi

review_wait_human="not_expected"
if [[ "$HUMANS_REQUIRED" -gt 0 ]]; then
    if [[ "$APPROVER_COUNT" -ge "$HUMANS_REQUIRED" ]]; then
        review_wait_human="satisfied"
    elif [[ "$HUMAN_TIMEOUT" == "null" ]]; then
        review_wait_human="waiting"
        add_blocker review_in_flight \
            "waiting for ${HUMANS_REQUIRED} human approval(s), have ${APPROVER_COUNT}; no human-review-timeout — waits indefinitely"
    else
        human_age=$(jq -rn --arg ts "$PR_CREATED" '(now - ($ts | fromdateiso8601)) | floor')
        if [[ "$human_age" -ge "$HUMAN_TIMEOUT" ]]; then
            review_wait_human="timed_out"
        else
            review_wait_human="waiting"
            add_blocker review_in_flight \
                "waiting for ${HUMANS_REQUIRED} human approval(s), have ${APPROVER_COUNT}; ${human_age}s elapsed < timeout ${HUMAN_TIMEOUT}s"
        fi
    fi
fi
set_fact review_wait "$(jq -n --arg b "$review_wait_bot" --arg h "$review_wait_human" '{bot: $b, human: $h}')"
# ── Blocker: untriaged non-thread reviewer feedback ──────────────────────────
# review_summary / issue_comment items are disjoint GitHub objects from review
# threads — the thread check does not cover them, and prgroom's
# no_blocker_items must never stand in (an item prgroom has not polled has no
# disposition). Deliberately NOT head-scoped: an issue_comment carries no
# commit reference and a summary's feedback does not become moot on push —
# only an actual triage decision clears it. Exclusion is by exact recorded
# reply ID, never author login. No durable record anywhere = blocker (fail
# closed). Empty current set = vacuously clear.
ISSUE_COMMENTS=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/comments?per_page=100" --paginate | jq -s 'add // []') || {
    echo "Error: failed to fetch issue comments" >&2; exit 3; }

inventory_items='[]'
while IFS= read -r -d '' inv_file; do
    file_items=$(jq '[.items[]?]' "$inv_file" 2>/dev/null) || continue
    inventory_items=$(jq -n --argjson a "$inventory_items" --argjson b "$file_items" '$a + $b')
done < <(find "${HOME}/.claude/state/pr-inventory" -maxdepth 1 \
         -name "${OWNER}-${REPO}-${PR}-*.json" -print0 2>/dev/null)

untriaged=$(jq -n \
    --argjson live_issue "$(jq '[.[] | {id, author: .user.login}]' <<<"$ISSUE_COMMENTS")" \
    --argjson live_summaries "$(jq '[.[] | select((.body // "") != "") | {review_id: .id, author: .user.login}]' <<<"$ALL_REVIEWS")" \
    --argjson recorded "$inventory_items" '
    def terminal_ok:
        (.classification == "SKIP")
        or (.classification == "FIX"
            and (.fix_outcome == "committed" or .fix_outcome == "already_addressed"));
    ([ $recorded[] | .posted_reply_id // empty ] | unique) as $agent_replies
    | ([ $recorded[] | select(.kind == "issue_comment" and terminal_ok) | .issue_comment_id ] | unique) as $done_issue
    | ([ $recorded[] | select(.kind == "review_summary" and terminal_ok) | .review_id // empty ] | unique) as $done_review
    | ([ $live_issue[]
         | select((.id as $i | $agent_replies | index($i)) == null)
         | select((.id as $i | $done_issue | index($i)) == null)
         | "issue_comment #\(.id) by \(.author)" ])
    + ([ $live_summaries[]
         | select((.review_id as $i | $done_review | index($i)) == null)
         | "review_summary #\(.review_id) by \(.author)" ])')
untriaged_count=$(jq 'length' <<<"$untriaged")
set_fact untriaged_feedback_count "$untriaged_count"
if [[ "$untriaged_count" -gt 0 ]]; then
    add_blocker untriaged_feedback \
        "untriaged non-thread feedback (no terminal disposition in any retained inventory): $(jq -r 'join("; ")' <<<"$untriaged")"
fi
# ── Blockers: prgroom internal state (ADDITIONAL sources, never substitutes
#    for the live thread / non-thread checks; the rolled-up auto_merge_eligible
#    is never consumed — two of its four gates are unsuitable here) ───────────
prgroom_available=false
if command -v prgroom >/dev/null 2>&1; then
    if pg_status=$(prgroom status --json 2>/dev/null) && [[ -n "$pg_status" ]] \
       && jq -e '.merge_gates' >/dev/null 2>&1 <<<"$pg_status"; then
        prgroom_available=true
        [[ "$(jq -r '.merge_gates.no_blocker_items' <<<"$pg_status")" == "false" ]] \
            && add_blocker prgroom_blocker "prgroom reports escalated/failed item(s) (merge_gates.no_blocker_items=false)"
        [[ "$(jq -r '.merge_gates.last_error_clear' <<<"$pg_status")" == "false" ]] \
            && add_blocker prgroom_error "prgroom reports a terminal lifecycle error (merge_gates.last_error_clear=false)"
    fi
fi
set_fact prgroom_available "$prgroom_available"

# ── Decision ─────────────────────────────────────────────────────────────────
blocker_count=$(jq 'length' <<<"$BLOCKERS")
status="eligible"; exit_code=0
if [[ "$blocker_count" -gt 0 ]]; then status="blocked"; exit_code=1; fi

jq -n \
    --arg status "$status" \
    --arg head "$HEAD_OID" \
    --argjson blockers "$BLOCKERS" \
    --argjson facts "$FACTS" \
    --arg hint "gh pr merge ${PR} --squash --match-head-commit ${HEAD_OID}" \
    '{status: $status, head_ref_oid: $head, blockers: $blockers, facts: $facts, merge_command_hint: $hint}'
exit "$exit_code"

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
# GATE: requested-changes       (Task 9)
# GATE: distinct-approvers      (Task 10)
# GATE: unresolved-threads      (Task 11)
# GATE: ci-green                (Task 12)
# GATE: review-in-flight        (Task 13)
# GATE: non-thread-feedback     (Task 17)
# GATE: prgroom-internal        (Task 18)

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

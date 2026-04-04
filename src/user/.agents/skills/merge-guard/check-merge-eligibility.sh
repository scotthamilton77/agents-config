#!/usr/bin/env bash
# check-merge-eligibility.sh — Check whether a PR is safe to merge.
# Verifies no pending automated reviews and no unseen review comments.
#
# Usage: check-merge-eligibility.sh <owner/repo> <pr-number> <comments-seen>
#
#   owner/repo     — GitHub repository (e.g. "octocat/hello-world")
#   pr-number      — Pull request number
#   comments-seen  — Number of review comments the agent has already triaged.
#                    Pass 0 if the agent has not seen any comments.
#
# Exit codes:
#   0 — Eligible to merge (JSON on stdout)
#   1 — Blocked: Copilot review in progress, not yet completed
#   2 — Blocked: Unseen review comments exist
#   3 — Error (auth failure, invalid args, network issue)
#
# Stdout (JSON):
#   { "status": "eligible|review_in_progress|unseen_comments",
#     "copilot_requested": bool, "copilot_review_complete": bool,
#     "copilot_work_started": bool,
#     "total_comments": N, "comments_seen": N, "unseen_comments": N,
#     "pending_reviewers": [...], "details": "..." }

set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────

usage() {
    echo "Usage: $0 <owner/repo> <pr-number> <comments-seen>" >&2
    exit 3
}

[[ $# -ge 3 ]] || usage

REPO="$1"
PR="$2"
COMMENTS_SEEN="$3"

# Validate owner/repo format
[[ "$REPO" == */* ]] || { echo "Error: first argument must be owner/repo" >&2; exit 3; }

# Validate PR number is a positive integer
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "Error: PR number must be a positive integer" >&2; exit 3; }

# Validate comments-seen is a non-negative integer
[[ "$COMMENTS_SEEN" =~ ^[0-9]+$ ]] || { echo "Error: comments-seen must be a non-negative integer" >&2; exit 3; }

# ── Constants ─────────────────────────────────────────────────────────────────

COPILOT_LOGIN_FILTER='test("copilot"; "i")'

# ── Helper functions ──────────────────────────────────────────────────────────

gh_api() {
    local result exit_code=0
    result=$(gh api "$@" 2>/dev/null) || exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo "gh api failed (exit $exit_code)" >&2
        return 1
    fi
    printf '%s' "$result"
}

# ── Pre-flight checks ────────────────────────────────────────────────────────

if ! gh auth status &>/dev/null; then
    echo "Error: gh auth failed — not authenticated" >&2
    exit 3
fi

if ! command -v jq &>/dev/null; then
    echo "Error: jq is required but not found" >&2
    exit 3
fi

# Verify PR exists and is open
pr_state=$(gh_api "repos/${REPO}/pulls/${PR}" --jq '.state') || {
    echo "Error: failed to fetch PR #${PR}" >&2; exit 3;
}
if [[ "$pr_state" != "open" ]]; then
    echo "Error: PR #${PR} is ${pr_state}, not open" >&2
    exit 3
fi

# ── Check 1: Pending reviewers ───────────────────────────────────────────────

echo "Checking pending reviewers..." >&2

pending_json=$(gh_api "repos/${REPO}/pulls/${PR}/requested_reviewers") || {
    echo "Error: failed to fetch requested reviewers" >&2; exit 3;
}

pending_users=$(printf '%s' "$pending_json" | jq -r '[.users[].login] | join(", ")')
pending_teams=$(printf '%s' "$pending_json" | jq -r '[.teams[].slug] | join(", ")')

# Build pending list for output
pending_reviewers="[]"
pending_reviewers=$(printf '%s' "$pending_json" | jq '[(.users[].login), (.teams[].slug)]')

# ── Check 2: Copilot review status ───────────────────────────────────────────

echo "Checking Copilot review status..." >&2

# Was Copilot requested?
copilot_requested=false
request_count=$(gh_api "repos/${REPO}/issues/${PR}/events" \
    --jq "[.[] | select(
        .event == \"review_requested\" and
        .requested_reviewer.login and
        (.requested_reviewer.login | ${COPILOT_LOGIN_FILTER})
    )] | length") || {
    echo "Warning: events API failed, assuming Copilot not requested" >&2
    request_count=0
}

if [[ "$request_count" -gt 0 ]]; then
    copilot_requested=true
    echo "  Copilot was requested as reviewer" >&2
fi

# Did Copilot start working?
copilot_work_started=false
if [[ "$copilot_requested" == true ]]; then
    work_count=$(gh_api "repos/${REPO}/issues/${PR}/events" \
        --jq '[.[] | select(.event == "copilot_work_started")] | length') || work_count=0

    if [[ "$work_count" -gt 0 ]]; then
        copilot_work_started=true
        echo "  Copilot work started" >&2
    fi
fi

# Did Copilot complete a review?
copilot_review_complete=false
if [[ "$copilot_requested" == true ]]; then
    review_count=$(gh_api "repos/${REPO}/pulls/${PR}/reviews" \
        --jq "[.[] | select(
            (.user.type == \"Bot\") and
            (.user.login | ${COPILOT_LOGIN_FILTER}) and
            .state == \"COMMENTED\"
        )] | length") || review_count=0

    if [[ "$review_count" -gt 0 ]]; then
        copilot_review_complete=true
        echo "  Copilot review complete" >&2
    fi
fi

# ── Check 3: Comment count vs seen ───────────────────────────────────────────

echo "Checking comment counts..." >&2

total_comments=$(gh_api "repos/${REPO}/pulls/${PR}/comments" --jq 'length') || {
    echo "Error: failed to fetch comments" >&2; exit 3;
}

unseen_comments=$((total_comments - COMMENTS_SEEN))
if [[ $unseen_comments -lt 0 ]]; then
    unseen_comments=0
fi

echo "  Total: ${total_comments}, Seen: ${COMMENTS_SEEN}, Unseen: ${unseen_comments}" >&2

# ── Decision ──────────────────────────────────────────────────────────────────

if [[ "$copilot_requested" == true && "$copilot_review_complete" == false ]]; then
    # Copilot review in progress -- block
    details="Copilot was requested as reviewer but has not completed its review"
    if [[ "$copilot_work_started" == true ]]; then
        details="${details} (work started, awaiting results)"
    else
        details="${details} (review may still be queued)"
    fi

    jq -n \
        --arg status "review_in_progress" \
        --argjson copilot_requested "$copilot_requested" \
        --argjson copilot_review_complete "$copilot_review_complete" \
        --argjson copilot_work_started "$copilot_work_started" \
        --argjson total_comments "$total_comments" \
        --argjson comments_seen "$COMMENTS_SEEN" \
        --argjson unseen_comments "$unseen_comments" \
        --argjson pending_reviewers "$pending_reviewers" \
        --arg details "$details" \
        '{
            status: $status,
            copilot_requested: $copilot_requested,
            copilot_review_complete: $copilot_review_complete,
            copilot_work_started: $copilot_work_started,
            total_comments: $total_comments,
            comments_seen: $comments_seen,
            unseen_comments: $unseen_comments,
            pending_reviewers: $pending_reviewers,
            details: $details
        }'
    exit 1

elif [[ "$unseen_comments" -gt 0 ]]; then
    # Unseen comments exist -- block
    jq -n \
        --arg status "unseen_comments" \
        --argjson copilot_requested "$copilot_requested" \
        --argjson copilot_review_complete "$copilot_review_complete" \
        --argjson copilot_work_started "$copilot_work_started" \
        --argjson total_comments "$total_comments" \
        --argjson comments_seen "$COMMENTS_SEEN" \
        --argjson unseen_comments "$unseen_comments" \
        --argjson pending_reviewers "$pending_reviewers" \
        --arg details "${unseen_comments} review comment(s) have not been triaged by the agent" \
        '{
            status: $status,
            copilot_requested: $copilot_requested,
            copilot_review_complete: $copilot_review_complete,
            copilot_work_started: $copilot_work_started,
            total_comments: $total_comments,
            comments_seen: $comments_seen,
            unseen_comments: $unseen_comments,
            pending_reviewers: $pending_reviewers,
            details: $details
        }'
    exit 2

else
    # All clear
    jq -n \
        --arg status "eligible" \
        --argjson copilot_requested "$copilot_requested" \
        --argjson copilot_review_complete "$copilot_review_complete" \
        --argjson copilot_work_started "$copilot_work_started" \
        --argjson total_comments "$total_comments" \
        --argjson comments_seen "$COMMENTS_SEEN" \
        --argjson unseen_comments 0 \
        --argjson pending_reviewers "$pending_reviewers" \
        --arg details "No pending automated reviews and all comments triaged" \
        '{
            status: $status,
            copilot_requested: $copilot_requested,
            copilot_review_complete: $copilot_review_complete,
            copilot_work_started: $copilot_work_started,
            total_comments: $total_comments,
            comments_seen: $comments_seen,
            unseen_comments: $unseen_comments,
            pending_reviewers: $pending_reviewers,
            details: $details
        }'
    exit 0
fi

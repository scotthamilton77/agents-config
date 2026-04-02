#!/usr/bin/env bash
# poll-copilot-review.sh — Poll a GitHub PR for Copilot review completion.
# Replaces the background agent polling in wait-for-pr-comments skill.
# Zero Anthropic API tokens consumed — pure bash + gh CLI.
#
# Usage: poll-copilot-review.sh <owner/repo> <pr-number> [--skip-request-check]
#
# Exit codes:
#   0 — Review found (JSON on stdout)
#   1 — Timeout (no review after ~10 minutes)
#   2 — Copilot not requested (not added as reviewer within ~1 minute)
#   3 — Error (auth failure, invalid args, network issue)
#
# Stdout (exit 0):
#   { "status": "copilot_review_found", "reviews": [...], "inline_comments": [...], "human_comments": [...] }
# Stdout (exit 1):
#   { "status": "copilot_review_timeout" }
# Stdout (exit 2):
#   { "status": "copilot_not_requested" }
# Stderr: diagnostic messages

set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────

usage() {
    echo "Usage: $0 <owner/repo> <pr-number> [--skip-request-check]" >&2
    exit 3
}

[[ $# -ge 2 ]] || usage

REPO="$1"
PR="$2"
SKIP_REQUEST=false

if [[ $# -ge 3 && "$3" == "--skip-request-check" ]]; then
    SKIP_REQUEST=true
fi

# Validate owner/repo format
[[ "$REPO" == */* ]] || { echo "Error: first argument must be owner/repo" >&2; exit 3; }

# Validate PR number is a positive integer
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "Error: PR number must be a positive integer" >&2; exit 3; }

# ── Constants ─────────────────────────────────────────────────────────────────

# Copilot identity varies by endpoint — case-insensitive match covers both
# Events API: login "Copilot" (type "Bot")
# Reviews/Comments API: login "copilot-pull-request-reviewer[bot]" (type "Bot")
COPILOT_LOGIN_FILTER='test("copilot"; "i")'
COPILOT_REVIEW_FILTER="(.user.type == \"Bot\") and (.user.login | ${COPILOT_LOGIN_FILTER})"

# ── Helper functions ──────────────────────────────────────────────────────────

# Wrapped gh api — keeps stderr separate from stdout to avoid JSON contamination
gh_api() {
    local result exit_code=0
    result=$(gh api "$@" 2>/dev/null) || exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo "gh api failed (exit $exit_code)" >&2
        return 1
    fi
    printf '%s' "$result"
}

pr_is_open() {
    local state
    state=$(gh_api "repos/${REPO}/pulls/${PR}" --jq '.state') || return 1
    [[ "$state" == "open" ]]
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

# ── Sub-phase A: Request detection (20s × 3, max ~1 minute) ──────────────────

if [[ "$SKIP_REQUEST" == false ]]; then
    echo "Sub-phase A: Checking if Copilot was requested as reviewer..." >&2
    copilot_requested=false

    for i in 1 2 3; do
        count=$(gh_api "repos/${REPO}/issues/${PR}/events" \
            --jq "[.[] | select(
                .event == \"review_requested\" and
                .requested_reviewer.login and
                (.requested_reviewer.login | ${COPILOT_LOGIN_FILTER})
            )] | length") || { echo "Error: events API failed during request detection" >&2; exit 3; }

        if [[ "$count" -gt 0 ]]; then
            echo "  Copilot reviewer detected (attempt ${i})" >&2
            copilot_requested=true
            break
        fi

        echo "  Attempt ${i}/3: not yet requested" >&2
        [[ $i -lt 3 ]] && sleep 20
    done

    if [[ "$copilot_requested" == false ]]; then
        echo "Copilot was not added as a reviewer within 1 minute" >&2
        jq -n '{"status": "copilot_not_requested"}'
        exit 2
    fi
else
    echo "Sub-phase A: Skipped (--skip-request-check)" >&2
fi

# ── Sub-phase B: Start detection (20s × 3, max ~1 minute) ────────────────────

echo "Sub-phase B: Checking for copilot_work_started event..." >&2

for i in 1 2 3; do
    count=$(gh_api "repos/${REPO}/issues/${PR}/events" \
        --jq '[.[] | select(.event == "copilot_work_started")] | length') || {
        echo "Warning: events API failed during start detection, proceeding anyway" >&2
        break
    }

    if [[ "$count" -gt 0 ]]; then
        echo "  copilot_work_started detected (attempt ${i})" >&2
        break
    fi

    echo "  Attempt ${i}/3: not yet started" >&2
    [[ $i -lt 3 ]] && sleep 20
done

# Proceed to Sub-phase C regardless (event may have fired before script ran)

# ── Sub-phase C: Review detection (30s × 20, max ~10 minutes) ────────────────

echo "Sub-phase C: Polling for Copilot review..." >&2

for i in $(seq 1 20); do
    # Check PR state periodically (every 5th iteration)
    if [[ $((i % 5)) -eq 0 ]]; then
        if ! pr_is_open; then
            echo "PR #${PR} is no longer open — aborting poll" >&2
            jq -n '{"status": "copilot_review_timeout"}'
            exit 1
        fi
    fi

    # Single fetch — derive count from the same response (avoids double API call)
    reviews=$(gh_api "repos/${REPO}/pulls/${PR}/reviews" \
        --jq "[.[] | select(${COPILOT_REVIEW_FILTER})]") || {
        echo "Warning: reviews API failed (attempt ${i})" >&2; sleep 30; continue;
    }

    count=$(printf '%s' "$reviews" | jq '[.[] | select(.state == "COMMENTED")] | length')

    if [[ "$count" -gt 0 ]]; then
        echo "  Copilot review found (attempt ${i})" >&2

        # Single fetch for all comments — split into copilot/human client-side
        all_comments=$(gh_api "repos/${REPO}/pulls/${PR}/comments") || {
            echo "Error: failed to fetch comments" >&2; exit 3;
        }

        inline=$(printf '%s' "$all_comments" | jq "[.[] | select(.user.login | ${COPILOT_LOGIN_FILTER})]")
        human=$(printf '%s' "$all_comments" | jq "[.[] | select(.user.login | ${COPILOT_LOGIN_FILTER} | not)]")

        jq -n \
            --argjson reviews "$reviews" \
            --argjson inline "$inline" \
            --argjson human "$human" \
            '{
                status: "copilot_review_found",
                reviews: $reviews,
                inline_comments: $inline,
                human_comments: $human
            }'
        exit 0
    fi

    echo "  Attempt ${i}/20: no review yet" >&2
    [[ $i -lt 20 ]] && sleep 30
done

echo "Copilot review not received after 10 minutes" >&2
jq -n '{"status": "copilot_review_timeout"}'
exit 1

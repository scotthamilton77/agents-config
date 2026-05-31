#!/usr/bin/env bash
# poll-copilot-review.sh — Poll a GitHub PR for Copilot review completion.
# Replaces the background agent polling in wait-for-pr-comments skill.
# Zero Anthropic API tokens consumed — pure bash + gh CLI.
#
# Usage: poll-copilot-review.sh --owner <o> --repo <r> --pr <n> [--skip-request-check] [--since-timestamp <ISO-8601>]
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

# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

# ── Argument parsing ──────────────────────────────────────────────────────────

usage() {
    echo "Usage: $0 --owner <o> --repo <r> --pr <n> [--skip-request-check] [--since-timestamp <ISO-8601>]" >&2
    exit 3
}

OWNER=""
REPO=""
PR=""
SKIP_REQUEST=false
SINCE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --owner) OWNER="${2:-}"; shift 2 ;;
        --repo)  REPO="${2:-}";  shift 2 ;;
        --pr)    PR="${2:-}";    shift 2 ;;
        --skip-request-check)
            SKIP_REQUEST=true
            shift
            ;;
        --since-timestamp)
            [[ -n "${2:-}" ]] || { echo "Error: --since-timestamp requires a value" >&2; exit 3; }
            SINCE="$2"
            shift 2
            ;;
        *)
            echo "Error: unknown argument: $1" >&2
            usage
            ;;
    esac
done

[[ -n "$OWNER" ]] || { echo "Error: --owner is required" >&2; usage; }
[[ -n "$REPO"  ]] || { echo "Error: --repo is required" >&2; usage; }
[[ -n "$PR"    ]] || { echo "Error: --pr is required" >&2; usage; }

# Validate PR number is a positive integer
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "Error: --pr must be a positive integer" >&2; exit 3; }

# ── Constants ─────────────────────────────────────────────────────────────────

# Copilot identity varies by endpoint — case-insensitive match covers both
# Events API: login "Copilot" (type "Bot")
# Reviews/Comments API: login "copilot-pull-request-reviewer[bot]" (type "Bot")
COPILOT_LOGIN_FILTER='test("copilot"; "i")'
COPILOT_REVIEW_FILTER="(.user.type == \"Bot\") and (.user.login | ${COPILOT_LOGIN_FILTER})"

# ── Helper functions ──────────────────────────────────────────────────────────

pr_is_open() {
    local state
    state=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}" --jq '.state') || return 1
    [[ "$state" == "open" ]]
}

# ── Pre-flight checks ────────────────────────────────────────────────────────

preflight_checks

# ── Sub-phase A: Request detection (20s × 3, max ~1 minute) ──────────────────

if [[ "$SKIP_REQUEST" == false ]]; then
    echo "Sub-phase A: Checking if Copilot was requested as reviewer..." >&2
    copilot_requested=false

    for i in 1 2 3; do
        count=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/events" \
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
    count=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/events" \
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
if [[ -n "$SINCE" ]]; then
    echo "  Filtering for reviews submitted after ${SINCE} (stale-cache guard)" >&2
fi

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
    reviews=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}/reviews" \
        --jq "[.[] | select(${COPILOT_REVIEW_FILTER})]") || {
        echo "Warning: reviews API failed (attempt ${i})" >&2; sleep 30; continue;
    }

    # If --since-timestamp was provided, reject reviews that predate it (stale cache guard)
    if [[ -n "$SINCE" ]]; then
        fresh_reviews=$(printf '%s' "$reviews" | jq --arg since "$SINCE" '[.[] | select(.submitted_at > $since)]')
        stale_count=$(printf '%s' "$reviews" | jq --arg since "$SINCE" '[.[] | select(.submitted_at <= $since)] | length')
        if [[ "$stale_count" -gt 0 ]]; then
            echo "  Attempt ${i}/20: found ${stale_count} stale review(s) (submitted_at <= ${SINCE}), discarding" >&2
        fi
        reviews="$fresh_reviews"
    fi

    count=$(printf '%s' "$reviews" | jq '[.[] | select(.state == "COMMENTED")] | length')

    if [[ "$count" -gt 0 ]]; then
        echo "  Copilot review found (attempt ${i})" >&2

        # Single fetch for all comments — split into copilot/human client-side
        all_comments=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}/comments") || {
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

#!/usr/bin/env bash
# poll-new-comments.sh — Poll a GitHub PR for new review comments after fixes.
# Replaces CronCreate-based re-poll in wait-for-pr-comments skill.
# Zero Anthropic API tokens consumed — pure bash + gh CLI.
#
# Usage: poll-new-comments.sh <owner/repo> <pr-number> <baseline-count> <interval-secs> <max-duration-secs>
#
# Exit codes:
#   0 — New comments found (JSON on stdout)
#   1 — No new comments after max duration
#   3 — Error (auth failure, invalid args, network issue)
#
# Stdout (exit 0):
#   { "status": "new_comments_found", "baseline_count": N, "current_count": M, "new_count": K, "comments": [...] }
# Stdout (exit 1):
#   { "status": "no_new_comments", "baseline_count": N, "polls_completed": P, "duration_seconds": D }
# Stderr: diagnostic messages

set -euo pipefail

# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

# ── Argument parsing ──────────────────────────────────────────────────────────

usage() {
    echo "Usage: $0 <owner/repo> <pr-number> <baseline-count> <interval-secs> <max-duration-secs>" >&2
    exit 3
}

[[ $# -eq 5 ]] || usage

REPO="$1"
PR="$2"
BASELINE="$3"
INTERVAL="$4"
MAX_DURATION="$5"

validate_repo "$REPO"

# Validate numeric arguments
for arg in "$PR" "$BASELINE" "$INTERVAL" "$MAX_DURATION"; do
    [[ "$arg" =~ ^[0-9]+$ ]] || { echo "Error: numeric arguments must be non-negative integers" >&2; exit 3; }
done

[[ "$INTERVAL" -gt 0 ]] || { echo "Error: interval must be > 0" >&2; exit 3; }
[[ "$MAX_DURATION" -gt 0 ]] || { echo "Error: max-duration must be > 0" >&2; exit 3; }

# ── Pre-flight checks ────────────────────────────────────────────────────────

preflight_checks

# ── Calculate iterations ─────────────────────────────────────────────────────

max_iterations=$(( (MAX_DURATION + INTERVAL - 1) / INTERVAL ))

echo "Re-poll: baseline=${BASELINE}, interval=${INTERVAL}s, max=${MAX_DURATION}s, iterations=${max_iterations}" >&2

# ── Poll loop (sleep first, then check) ──────────────────────────────────────

for i in $(seq 1 "$max_iterations"); do
    sleep "$INTERVAL"

    # Single fetch — derive count client-side (avoids double API call on detection)
    comments=$(gh_api "repos/${REPO}/pulls/${PR}/comments") || {
        echo "Warning: comments API failed (attempt ${i}), continuing" >&2
        continue
    }

    count=$(printf '%s' "$comments" | jq 'length')
    echo "  Poll ${i}/${max_iterations}: count=${count} (baseline=${BASELINE})" >&2

    if [[ "$count" -gt "$BASELINE" ]]; then
        echo "  New comments detected: $((count - BASELINE)) new" >&2

        jq -n \
            --argjson baseline "$BASELINE" \
            --argjson current "$count" \
            --argjson new_count "$((count - BASELINE))" \
            --argjson comments "$comments" \
            '{
                status: "new_comments_found",
                baseline_count: $baseline,
                current_count: $current,
                new_count: $new_count,
                comments: $comments
            }'
        exit 0
    fi
done

echo "No new comments after ${MAX_DURATION}s (${max_iterations} polls)" >&2

jq -n \
    --argjson baseline "$BASELINE" \
    --argjson polls "$max_iterations" \
    --argjson duration "$MAX_DURATION" \
    '{
        status: "no_new_comments",
        baseline_count: $baseline,
        polls_completed: $polls,
        duration_seconds: $duration
    }'
exit 1

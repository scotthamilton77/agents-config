#!/usr/bin/env bash
# poll-copilot-rereview-start.sh — Detect whether Copilot has started a re-review.
# Looks for a copilot_work_started event that postdates the given timestamp.
# Used after fixes are pushed to check if Copilot will perform a second pass.
#
# Usage: poll-copilot-rereview-start.sh <owner/repo> <pr-number> <after-timestamp>
#
# after-timestamp: ISO 8601 timestamp — only events after this time are considered
#
# Configurable polling (set as env vars; defaults give the historical 80s window):
#   INITIAL_SLEEP   pre-poll delay in seconds (default: 20)
#   POLL_INTERVAL   per-attempt sleep in seconds (default: 10)
#   POLL_COUNT      number of attempts after the initial sleep (default: 6)
#
# Exit codes:
#   0 — Re-review started (JSON on stdout)
#   1 — No re-review started within polling window
#   3 — Error (auth failure, invalid args, network issue)
#
# Stdout (exit 0):
#   { "status": "copilot_rereview_started", "event_timestamp": "..." }
# Stdout (exit 1):
#   { "status": "no_rereview_started" }
# Stderr: diagnostic messages

set -euo pipefail

# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

# ── Argument parsing ──────────────────────────────────────────────────────────

usage() {
    echo "Usage: $0 <owner/repo> <pr-number> <after-timestamp>" >&2
    exit 3
}

[[ $# -eq 3 ]] || usage

REPO="$1"
PR="$2"
AFTER="$3"

INITIAL_SLEEP="${INITIAL_SLEEP:-20}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
POLL_COUNT="${POLL_COUNT:-6}"

validate_repo "$REPO"
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "Error: PR number must be a positive integer" >&2; exit 3; }
[[ -n "$AFTER" ]] || { echo "Error: after-timestamp must not be empty" >&2; exit 3; }
[[ "$INITIAL_SLEEP" =~ ^[0-9]+$ ]] || { echo "Error: INITIAL_SLEEP must be a non-negative integer" >&2; exit 3; }
[[ "$POLL_INTERVAL" =~ ^[0-9]+$ ]] || { echo "Error: POLL_INTERVAL must be a non-negative integer" >&2; exit 3; }
[[ "$POLL_COUNT" =~ ^[0-9]+$ ]] || { echo "Error: POLL_COUNT must be a non-negative integer" >&2; exit 3; }

# ── Pre-flight checks ────────────────────────────────────────────────────────

preflight_checks

# ── Poll loop (sleep first, then check) ──────────────────────────────────────

echo "Polling for Copilot re-review start (${INITIAL_SLEEP}s pre-sleep + ${POLL_COUNT} × ${POLL_INTERVAL}s = $((INITIAL_SLEEP + POLL_COUNT * POLL_INTERVAL))s max window, after ${AFTER})..." >&2

sleep "$INITIAL_SLEEP"

for ((i = 1; i <= POLL_COUNT; i++)); do
    sleep "$POLL_INTERVAL"

    events=$(gh_api "repos/${REPO}/issues/${PR}/events" \
        --jq "[.[] | select(.event == \"copilot_work_started\" and .created_at > \"${AFTER}\")]") || {
        echo "Warning: events API failed (attempt ${i}), continuing" >&2
        continue
    }

    event_ts=$(printf '%s' "$events" | jq -r '.[0].created_at // empty')
    if [[ -n "$event_ts" ]]; then
        echo "  Poll ${i}/${POLL_COUNT}: copilot_work_started detected after ${AFTER}" >&2
        echo "  Copilot re-review started at ${event_ts}" >&2
        jq -n --arg ts "$event_ts" \
            '{"status": "copilot_rereview_started", "event_timestamp": $ts}'
        exit 0
    fi
    echo "  Poll ${i}/${POLL_COUNT}: no copilot_work_started event after ${AFTER}" >&2
done

echo "No Copilot re-review started within polling window" >&2
jq -n '{"status": "no_rereview_started"}'
exit 1

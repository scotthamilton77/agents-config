#!/bin/bash
# poll-ready-beads.sh [max-minutes]
#
# Polls for implementation-ready beads at 10-minute intervals.
#
# Exits 0 with bead JSON on stdout when beads are found.
# Exits 1 with a message on stdout when max-minutes is exceeded.
# Exits on SIGINT/SIGTERM cleanly.
#
# Usage:
#   ./poll-ready-beads.sh           # poll forever
#   ./poll-ready-beads.sh 60        # poll for up to 60 minutes

MAX_MINUTES="${1:-}"
INTERVAL_SECONDS=600   # 10 minutes
ELAPSED_SECONDS=0

trap 'echo "Interrupted."; exit 2' INT TERM

while true; do
    RESULT=$(bd ready --label implementation-ready --json 2>/dev/null)
    COUNT=$(echo "$RESULT" | jq 'length' 2>/dev/null || echo "0")

    if [ "$COUNT" -gt 0 ]; then
        echo "$RESULT"
        exit 0
    fi

    if [ -n "$MAX_MINUTES" ] && [ "$ELAPSED_SECONDS" -ge "$((MAX_MINUTES * 60))" ]; then
        echo "No implementation-ready beads found after ${MAX_MINUTES} minutes."
        exit 1
    fi

    sleep "$INTERVAL_SECONDS"
    ELAPSED_SECONDS=$((ELAPSED_SECONDS + INTERVAL_SECONDS))
done

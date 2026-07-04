#!/usr/bin/env bash
# Purpose: compute the two new inventory polling fields for the bot-quiescence
# re-review budget. Pure arithmetic — no file/network I/O; the caller reads
# prior values from the head-exact inventory and merges this output into
# POLLING_FILE.
#
# Inputs:
#   --prior-count <int>        prior rereview_round_count for THIS head (default 0)
#   --prior-exhausted <bool>   prior bot_review_cap_exhausted for THIS head (default false)
#   --event <silent|chatty-cap|none>   the cycle outcome being recorded (required)
#   --silent-cap <int>         silent-ask cap (default 1)
# Output (stdout): {"rereview_round_count": <int>, "bot_review_cap_exhausted": <bool>}
# Exit: 0 ok; 2 bad usage.
set -euo pipefail

prior_count=0
prior_exhausted=false
event=""
silent_cap=1

usage() { echo "usage: $(basename "$0") --event <silent|chatty-cap|none> [--prior-count N] [--prior-exhausted true|false] [--silent-cap N]" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --prior-count)     prior_count="${2:-}"; shift 2 ;;
    --prior-exhausted) prior_exhausted="${2:-}"; shift 2 ;;
    --event)           event="${2:-}"; shift 2 ;;
    --silent-cap)      silent_cap="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ "$event" =~ ^(silent|chatty-cap|none)$ ]] || usage
[[ "$prior_count" =~ ^[0-9]+$ ]] || usage
[[ "$silent_cap" =~ ^[0-9]+$ ]] || usage
[[ "$prior_exhausted" =~ ^(true|false)$ ]] || usage

new_count=$prior_count
[ "$event" = "silent" ] && new_count=$((prior_count + 1))

exhausted=$prior_exhausted
if [ "$exhausted" != "true" ]; then
  if [ "$new_count" -ge "$silent_cap" ] && [ "$event" = "silent" ]; then exhausted=true; fi
  if [ "$event" = "chatty-cap" ]; then exhausted=true; fi
fi

jq -nc --argjson c "$new_count" --argjson e "$exhausted" \
  '{rereview_round_count: $c, bot_review_cap_exhausted: $e}'

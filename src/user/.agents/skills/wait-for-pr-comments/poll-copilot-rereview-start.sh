#!/usr/bin/env bash
# poll-copilot-rereview-start.sh — Detect whether a trusted bot has started a
# re-review: a copilot_work_started event (Copilot), or, when --bot-reviewers
# is given, an 'eyes' reaction on the PR body from an allowlisted identity
# (Codex's in-flight marker — Codex never emits copilot_work_started).
#
# Usage: poll-copilot-rereview-start.sh --owner <o> --repo <r> --pr <n> --after <ISO-8601-timestamp> [--bot-reviewers <json-array>]
#
# --after: ISO 8601 timestamp — only events/reactions after this time count.
# --bot-reviewers: JSON array of identities (mirrors poll-copilot-review.sh's
#   convention); enables the eyes-reaction check. Omit to keep the original
#   Copilot-events-only behavior.
#
# Exit codes: 0 started (JSON), 1 not started, 3 error.
# Stdout (0): {"status":"copilot_rereview_started","signal":"event"|"eyes_reaction","event_timestamp":"..."}
# Stdout (1): {"status":"no_rereview_started"}
# Stderr: diagnostics
#
# Configurable polling (set as env vars; defaults give the historical 80s window):
#   INITIAL_SLEEP   pre-poll delay in seconds (default: 20)
#   POLL_INTERVAL   per-attempt sleep in seconds (default: 10)
#   POLL_COUNT      number of attempts after the initial sleep (default: 6)

set -euo pipefail

# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

# ── Argument parsing ──────────────────────────────────────────────────────────

usage() {
    echo "Usage: $0 --owner <o> --repo <r> --pr <n> --after <ISO-8601-timestamp> [--bot-reviewers <json-array>]" >&2
    exit 3
}

OWNER=""
REPO=""
PR=""
AFTER=""
BOT_REVIEWERS=""

INITIAL_SLEEP="${INITIAL_SLEEP:-20}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
POLL_COUNT="${POLL_COUNT:-6}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --owner)         [[ $# -ge 2 ]] || usage; OWNER="${2:-}";         shift 2 ;;
        --repo)          [[ $# -ge 2 ]] || usage; REPO="${2:-}";          shift 2 ;;
        --pr)            [[ $# -ge 2 ]] || usage; PR="${2:-}";            shift 2 ;;
        --after)         [[ $# -ge 2 ]] || usage; AFTER="${2:-}";         shift 2 ;;
        --bot-reviewers) [[ $# -ge 2 ]] || usage; BOT_REVIEWERS="${2:-}"; shift 2 ;;
        *) echo "Error: unknown argument: $1" >&2; usage ;;
    esac
done

[[ -n "$OWNER" ]] || { echo "Error: --owner is required" >&2; usage; }
[[ -n "$REPO"  ]] || { echo "Error: --repo is required" >&2; usage; }
[[ -n "$PR"    ]] || { echo "Error: --pr is required" >&2; usage; }
[[ -n "$AFTER" ]] || { echo "Error: --after is required" >&2; usage; }
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "Error: --pr must be a positive integer" >&2; exit 3; }
[[ "$INITIAL_SLEEP" =~ ^[0-9]+$ ]] || { echo "Error: INITIAL_SLEEP must be a non-negative integer" >&2; exit 3; }
[[ "$POLL_INTERVAL" =~ ^[0-9]+$ ]] || { echo "Error: POLL_INTERVAL must be a non-negative integer" >&2; exit 3; }
[[ "$POLL_COUNT" =~ ^[0-9]+$ ]] || { echo "Error: POLL_COUNT must be a non-negative integer" >&2; exit 3; }

# Validate --bot-reviewers (when provided) as a non-empty JSON array of
# strings — same convention as poll-copilot-review.sh/request-rereview.sh —
# then canonicalize via jq so only clean, re-serialized JSON is interpolated
# into the jq filter below.
if [[ -n "$BOT_REVIEWERS" ]]; then
    BOT_REVIEWERS=$(jq -ce 'if (type == "array" and length > 0 and ([.[] | select(type != "string")] | length) == 0) then . else error("bad") end' <<<"$BOT_REVIEWERS" 2>/dev/null) || {
        echo "Error: --bot-reviewers must be a non-empty JSON array of strings" >&2
        exit 3
    }
fi

# Login-matching filter, applied via `<login> | ${BOT_LOGIN_FILTER}` — exact
# (case-insensitive) match against the allowlist, mirroring
# poll-copilot-review.sh's --bot-reviewers convention.
BOT_LOGIN_FILTER="ascii_downcase as \$l | (${BOT_REVIEWERS:-[]} | map(ascii_downcase) | index(\$l)) != null"

# ── Pre-flight checks ────────────────────────────────────────────────────────

preflight_checks

# ── Poll loop (sleep first, then check) ──────────────────────────────────────

echo "Polling for Copilot re-review start (${INITIAL_SLEEP}s pre-sleep + ${POLL_COUNT} × ${POLL_INTERVAL}s = $((INITIAL_SLEEP + POLL_COUNT * POLL_INTERVAL))s max window, after ${AFTER})..." >&2

sleep "$INITIAL_SLEEP"

for ((i = 1; i <= POLL_COUNT; i++)); do
    sleep "$POLL_INTERVAL"

    events=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/events" \
        --jq "[.[] | select(.event == \"copilot_work_started\" and .created_at > \"${AFTER}\")]") || {
        echo "Warning: events API failed (attempt ${i}), continuing" >&2
        continue
    }

    event_ts=$(printf '%s' "$events" | jq -r '.[0].created_at // empty')
    if [[ -n "$event_ts" ]]; then
        echo "  Poll ${i}/${POLL_COUNT}: copilot_work_started detected after ${AFTER}" >&2
        echo "  Copilot re-review started at ${event_ts}" >&2
        jq -n --arg ts "$event_ts" \
            '{"status": "copilot_rereview_started", "signal": "event", "event_timestamp": $ts}'
        exit 0
    fi

    # Eyes-reaction check (only when --bot-reviewers was given): Codex's
    # in-flight marker on the PR body, appearing within ~15s of the
    # '@codex review' ask — the only start signal Codex emits, since it
    # never fires copilot_work_started.
    if [[ -n "$BOT_REVIEWERS" ]]; then
        reactions=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/reactions?per_page=100" --paginate \
            | jq -s 'add // []') || {
            echo "Warning: reactions API failed (attempt ${i}), continuing" >&2
            reactions='[]'
        }
        eyes_ts=$(printf '%s' "$reactions" | jq -r \
            --arg after "$AFTER" \
            "[.[] | select(.content == \"eyes\" and (.user.login | ${BOT_LOGIN_FILTER}) and .created_at > \$after)] | .[0].created_at // empty")
        if [[ -n "$eyes_ts" ]]; then
            echo "  Poll ${i}/${POLL_COUNT}: eyes reaction detected after ${AFTER}" >&2
            echo "  Re-review started (eyes reaction) at ${eyes_ts}" >&2
            jq -n --arg ts "$eyes_ts" \
                '{"status": "copilot_rereview_started", "signal": "eyes_reaction", "event_timestamp": $ts}'
            exit 0
        fi
    fi

    echo "  Poll ${i}/${POLL_COUNT}: no re-review start signal after ${AFTER}" >&2
done

echo "No Copilot re-review started within polling window" >&2
jq -n '{"status": "no_rereview_started"}'
exit 1

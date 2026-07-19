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
# Exit codes: 0 started (JSON), 1 not started, 3 error (bad args, auth, OR the
# reactions endpoint still failing at the deadline with --bot-reviewers set —
# distinct from "not started", since whether Codex started is then unknown,
# not false; see the poll-loop comment on reactions_endpoint_failed).
# Stdout (0): {"status":"copilot_rereview_started","signal":"event"|"eyes_reaction","event_timestamp":"..."}
# Stdout (1): {"status":"no_rereview_started"}
# Stdout (3, reactions endpoint failed at the deadline): {"status":"rereview_start_check_error","message":"..."}
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

# Names the events/reactions endpoint as failed on the CURRENT attempt
# (reset each iteration). If either is still set when the loop exhausts,
# whether a re-review started is unobservable at the deadline: exit 1
# (no_rereview_started) would make Phase 6 count this as a silent ask and
# spend the one-ask cap on an infrastructure failure it never actually
# established — mirrors poll-copilot-review.sh's clean-signal-endpoint-
# failure handling (exit 3, not the timeout exit). The two checks are
# independent API calls (events for Copilot, reactions for Codex), so one
# failing must not skip the other — a hiccup on Copilot's endpoint must not
# blind the poll to a Codex 'eyes' that has already landed, and vice versa.
events_endpoint_failed=false
reactions_endpoint_failed=false

for ((i = 1; i <= POLL_COUNT; i++)); do
    sleep "$POLL_INTERVAL"
    events_endpoint_failed=false
    reactions_endpoint_failed=false

    # Fetch raw, filter locally (matching the reactions check below) rather
    # than filtering server-side via --jq: keeps both signals' filtering
    # logic in one place, in the same style, exercised the same way by tests.
    events=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/events") || {
        echo "Warning: events API failed (attempt ${i}), continuing" >&2
        events='[]'
        events_endpoint_failed=true
    }

    # Boundary comparison is >=, not >: see the note on the eyes-reaction
    # check below — same $AFTER, same Phase 6 step 1 contract.
    event_ts=$(printf '%s' "$events" | jq -r \
        --arg after "$AFTER" \
        '[.[] | select(.event == "copilot_work_started" and .created_at >= $after)] | .[0].created_at // empty')
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
    # never fires copilot_work_started. Runs regardless of whether the
    # events check above succeeded — see the note above the loop.
    if [[ -n "$BOT_REVIEWERS" ]]; then
        reactions=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/reactions?per_page=100" --paginate \
            | jq -s 'add // []') || {
            echo "Warning: reactions API failed (attempt ${i}), continuing" >&2
            reactions='[]'
            reactions_endpoint_failed=true
        }
        # Boundary comparison is >=, not >: $AFTER is captured immediately
        # BEFORE the re-review ask is dispatched (Phase 6 step 1), precisely
        # so a fast bot response landing in the same API-timestamp second is
        # not excluded — see that step's own stated contract. A strict >
        # here would silently drop a same-second eyes reaction and count a
        # started Codex review as a silent ask.
        eyes_ts=$(printf '%s' "$reactions" | jq -r \
            --arg after "$AFTER" \
            "[.[] | select(.content == \"eyes\" and (.user.login | ${BOT_LOGIN_FILTER}) and .created_at >= \$after)] | .[0].created_at // empty")
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

# An events- or reactions-endpoint failure still in effect on the FINAL
# attempt makes "nothing started" indistinguishable from "we couldn't
# check" — report the documented infrastructure error (exit 3) rather than
# a false no_rereview_started the caller would spend its silent-ask budget on.
if [[ "$events_endpoint_failed" == true || "$reactions_endpoint_failed" == true ]]; then
    echo "Error: an API endpoint failed at the deadline; cannot determine whether a re-review started" >&2
    jq -n '{"status": "rereview_start_check_error", "message": "endpoint failure: cannot determine whether a re-review started"}'
    exit 3
fi

echo "No Copilot re-review started within polling window" >&2
jq -n '{"status": "no_rereview_started"}'
exit 1

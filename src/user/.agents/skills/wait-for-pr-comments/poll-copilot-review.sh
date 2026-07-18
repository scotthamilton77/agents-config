#!/usr/bin/env bash
# poll-copilot-review.sh — Poll a GitHub PR for Copilot review completion.
# Replaces the background agent polling in wait-for-pr-comments skill.
# Zero Anthropic API tokens consumed — pure bash + gh CLI.
#
# Usage: poll-copilot-review.sh --owner <o> --repo <r> --pr <n> [--skip-request-check] [--since-timestamp <ISO-8601>] [--timeout-seconds <n>] [--bot-reviewers <json-array>]
#
# --timeout-seconds sets the give-up window for sub-phase C (the main
# review-wait poll). Default 600 (~10 minutes, this script's historical
# behavior). Callers should pass the resolved review policy's
# bot_inactivity_timeout_seconds (see merge-guard/resolve_policy.py).
#
# --bot-reviewers is a JSON array of the exact reviewer identities to poll for
# (e.g. '["Copilot", "copilot-pull-request-reviewer[bot]"]'). When supplied,
# review/comment matching is an EXACT (case-insensitive) login match against
# that list instead of the default Copilot substring — generalizing the poll to
# any bot the merge policy trusts. Callers should pass the resolved review
# policy's bot_reviewers list (see merge-guard/resolve_policy.py); the same
# exact-identity allowlist the merge gate enforces. Omit it to keep the
# standalone Copilot-substring default.
#
# Poll completion contract: this script's JSON output also completes without
# a review object when a bot's pass is clean. When --bot-reviewers is
# supplied, a `+1` reaction on the PR body, or an issue comment starting with
# the clean-pass marker "Codex Review: Didn't find any major issues" — each
# from an allowlisted identity and post-dating --since-timestamp when given —
# also counts as completion (the standalone Copilot-substring default never
# checks either signal). `completion_kind` distinguishes "review" /
# "clean_reaction" / "timeout"; only "timeout" should count against a
# caller's silent-ask budget.
#
# Exit codes:
#   0 — Review found (JSON on stdout)
#   1 — Timeout (no review within --timeout-seconds, default ~10 minutes)
#   2 — Copilot not requested (not added as reviewer within ~1 minute)
#   3 — Error (auth failure, invalid args, network issue)
#
# Stdout (exit 0):
#   { "status": "copilot_review_found", "completion_kind": "review"|"clean_reaction", "reviews": [...], "inline_comments": [...], "human_comments": [...] }
# Stdout (exit 1):
#   { "status": "copilot_review_timeout", "completion_kind": "timeout" }
# Stdout (exit 2):
#   { "status": "copilot_not_requested" }
# Stderr: diagnostic messages

set -euo pipefail

# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

# ── Argument parsing ──────────────────────────────────────────────────────────

usage() {
    echo "Usage: $0 --owner <o> --repo <r> --pr <n> [--skip-request-check] [--since-timestamp <ISO-8601>] [--timeout-seconds <n>] [--bot-reviewers <json-array>]" >&2
    exit 3
}

OWNER=""
REPO=""
PR=""
SKIP_REQUEST=false
SINCE=""
TIMEOUT_SECONDS=""
BOT_REVIEWERS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --owner) [[ $# -ge 2 ]] || usage; OWNER="${2:-}"; shift 2 ;;
        --repo)  [[ $# -ge 2 ]] || usage; REPO="${2:-}";  shift 2 ;;
        --pr)    [[ $# -ge 2 ]] || usage; PR="${2:-}";    shift 2 ;;
        --skip-request-check)
            SKIP_REQUEST=true
            shift
            ;;
        --since-timestamp)
            [[ -n "${2:-}" ]] || { echo "Error: --since-timestamp requires a value" >&2; exit 3; }
            SINCE="$2"
            shift 2
            ;;
        --timeout-seconds)
            [[ -n "${2:-}" ]] || { echo "Error: --timeout-seconds requires a value" >&2; exit 3; }
            TIMEOUT_SECONDS="$2"
            shift 2
            ;;
        --bot-reviewers)
            [[ -n "${2:-}" ]] || { echo "Error: --bot-reviewers requires a value" >&2; exit 3; }
            BOT_REVIEWERS="$2"
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

# Validate --timeout-seconds is a positive integer; default preserves this
# script's historical ~10-minute give-up window.
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-600}"
[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ && "$TIMEOUT_SECONDS" -gt 0 ]] || {
    echo "Error: --timeout-seconds must be a positive integer" >&2
    exit 3
}

# Validate --bot-reviewers (when provided) as a non-empty JSON array of strings,
# then canonicalize via jq so only clean, re-serialized JSON is interpolated
# into the jq filters below (no raw user string reaches a jq program). The
# non-string check is select-based (not all/2) to match the guard idiom in
# validate-inventory.sh and stay unambiguously jq-1.5-safe.
if [[ -n "$BOT_REVIEWERS" ]]; then
    BOT_REVIEWERS=$(jq -ce 'if (type == "array" and length > 0 and ([.[] | select(type != "string")] | length) == 0) then . else error("bad") end' <<<"$BOT_REVIEWERS" 2>/dev/null) || {
        echo "Error: --bot-reviewers must be a non-empty JSON array of strings" >&2
        exit 3
    }
fi

# ── Constants ─────────────────────────────────────────────────────────────────

# Login-matching filter, applied via `<login> | ${COPILOT_LOGIN_FILTER}`.
#
# Default (no --bot-reviewers): Copilot identity varies by endpoint, so a
# case-insensitive substring match covers both —
#   Events API:           login "Copilot"                            (type "Bot")
#   Reviews/Comments API: login "copilot-pull-request-reviewer[bot]" (type "Bot")
#
# With --bot-reviewers: match logins EXACTLY (case-insensitively) against the
# policy's allowlist instead, generalizing the poll to any trusted bot. The
# array is pre-validated + jq-canonicalized above, so embedding it in the jq
# program is safe.
if [[ -n "$BOT_REVIEWERS" ]]; then
    COPILOT_LOGIN_FILTER="ascii_downcase as \$l | (${BOT_REVIEWERS} | map(ascii_downcase) | index(\$l)) != null"
else
    COPILOT_LOGIN_FILTER='test("copilot"; "i")'
fi
COPILOT_REVIEW_FILTER="(.user.type == \"Bot\") and (.user.login | ${COPILOT_LOGIN_FILTER})"

# Clean-pass marker prefix (Component 3) — an issue comment body starting
# with this, from an allowlisted identity, is a clean-pass completion signal
# (checked only when --bot-reviewers is supplied; see header).
CLEAN_PASS_MARKER="Codex Review: Didn't find any major issues"

# ── Helper functions ──────────────────────────────────────────────────────────

pr_is_open() {
    local state
    state=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}" --jq '.state') || return 1
    [[ "$state" == "open" ]]
}

# emit_clean_reaction_found — shared stdout payload for both clean-pass
# completion signals (a `+1` reaction and a marker comment carry no review
# content, so both report the same empty-arrays shape).
emit_clean_reaction_found() {
    jq -n '{
        status: "copilot_review_found",
        completion_kind: "clean_reaction",
        reviews: [],
        inline_comments: [],
        human_comments: []
    }'
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

# ── Sub-phase C: Review detection (poll every POLL_INTERVAL_SECONDS, up to
#    TIMEOUT_SECONDS total — default 30s × 20 = ~10 minutes) ─────────────────

POLL_INTERVAL_SECONDS=30
# Ceiling division so a --timeout-seconds shorter than one interval still
# gets exactly one attempt instead of zero.
MAX_ITERATIONS=$(( (TIMEOUT_SECONDS + POLL_INTERVAL_SECONDS - 1) / POLL_INTERVAL_SECONDS ))

echo "Sub-phase C: Polling for Copilot review (timeout ${TIMEOUT_SECONDS}s, ${MAX_ITERATIONS} attempt(s))..." >&2
if [[ -n "$SINCE" ]]; then
    echo "  Filtering for reviews submitted after ${SINCE} (stale-cache guard)" >&2
fi

for i in $(seq 1 "$MAX_ITERATIONS"); do
    # Check PR state periodically (every 5th iteration)
    if [[ $((i % 5)) -eq 0 ]]; then
        if ! pr_is_open; then
            echo "PR #${PR} is no longer open — aborting poll" >&2
            jq -n '{"status": "copilot_review_timeout", "completion_kind": "timeout"}'
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
            echo "  Attempt ${i}/${MAX_ITERATIONS}: found ${stale_count} stale review(s) (submitted_at <= ${SINCE}), discarding" >&2
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
                completion_kind: "review",
                reviews: $reviews,
                inline_comments: $inline,
                human_comments: $human
            }'
        exit 0
    fi

    # Clean-pass completion (poll completion contract): a bot can complete
    # with no findings and thus no review object — a `+1` reaction on the PR
    # body, or a clean-pass marker issue comment, either post-dating
    # --since-timestamp when supplied. Only checked in policy mode
    # (--bot-reviewers set); the standalone Copilot-substring default never
    # sees either signal.
    if [[ -n "$BOT_REVIEWERS" ]]; then
        reactions=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/reactions" \
            --jq "[.[] | select(.content == \"+1\" and (.user.login | ${COPILOT_LOGIN_FILTER}))]") || {
            echo "Warning: reactions API failed (attempt ${i})" >&2; reactions='[]';
        }
        if [[ -n "$SINCE" ]]; then
            reactions=$(printf '%s' "$reactions" | jq --arg since "$SINCE" '[.[] | select(.created_at > $since)]')
        fi

        if [[ "$(printf '%s' "$reactions" | jq 'length')" -gt 0 ]]; then
            echo "  Clean-pass reaction found (attempt ${i})" >&2
            emit_clean_reaction_found
            exit 0
        fi

        clean_comments=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/comments" \
            --jq "[.[] | select((.user.login | ${COPILOT_LOGIN_FILTER}) and ((.body // \"\") | startswith(\"${CLEAN_PASS_MARKER}\")))]") || {
            echo "Warning: issue comments API failed (attempt ${i})" >&2; clean_comments='[]';
        }
        if [[ -n "$SINCE" ]]; then
            clean_comments=$(printf '%s' "$clean_comments" | jq --arg since "$SINCE" '[.[] | select(.created_at > $since)]')
        fi

        if [[ "$(printf '%s' "$clean_comments" | jq 'length')" -gt 0 ]]; then
            echo "  Clean-pass marker comment found (attempt ${i})" >&2
            emit_clean_reaction_found
            exit 0
        fi
    fi

    echo "  Attempt ${i}/${MAX_ITERATIONS}: no review yet" >&2
    [[ $i -lt $MAX_ITERATIONS ]] && sleep "$POLL_INTERVAL_SECONDS"
done

echo "Copilot review not received after ${TIMEOUT_SECONDS}s" >&2
jq -n '{"status": "copilot_review_timeout", "completion_kind": "timeout"}'
exit 1

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
# standalone Copilot-substring default. If it contains a comment-triggered
# identity (currently chatgpt-codex-connector[bot]/Codex — never a requested
# reviewer, mirrors request-rereview.sh's identity dispatch table), Sub-phase
# A's requested-reviewer probe auto-skips (as if --skip-request-check were
# passed) instead of risking a spurious copilot_not_requested exit; no effect
# when the list has only request-based identities (e.g. Copilot).
#
# Poll completion contract: this script's JSON output also completes without
# a review object when a bot's pass is clean. A submitted review (state
# APPROVED or COMMENTED — mirroring check-merge-eligibility.sh's own review
# path, which accepts both as a legitimate clean pass) always counts as
# completion, but ONLY when it is fresh. On a re-review round
# (--since-timestamp supplied), fresh means submitted_at > SINCE — the same
# guard used everywhere else in this script. On the INITIAL poll (no
# --since-timestamp), there is no timestamp bound, so freshness is
# established instead by requiring the review's own `.commit_id` to equal
# the CURRENT PR head, fetched fresh each attempt — matching
# check-merge-eligibility.sh's review-path acceptance in effect, not as a
# literal line-for-line copy: that script guards a missing key with
# `(.commit_id // "") == $head`, this filter compares `.commit_id` bare —
# functionally identical in jq (a missing key is `null`, and `null ==
# "<sha>"` is `false`), so both fail closed on a reviewer payload lacking
# the field. This differs
# in KIND from the reaction/marker clean-pass bound below (a time-based
# max(committer date, force-push event) window): a review object carries the
# exact commit it was submitted against, so exact equality is available and
# strictly more precise than a time-based approximation, whereas a reaction
# or issue comment carries no commit reference at all and has no equality
# check available to it. A stale review (commit_id != current head) is a
# response to code no longer at HEAD and must not complete the poll; an
# unfetchable head fails closed, rejecting all reviews that round rather than
# risk accepting a stale one. When --bot-reviewers is supplied, two additional clean-pass
# signals count too: a `+1` reaction on the PR body, or an issue comment
# starting with the clean-pass marker "Codex Review: Didn't find any major
# issues" — each from an allowlisted identity (the standalone
# Copilot-substring default never checks either signal). These two are NOT
# interchangeable: the `+1` reaction is the real qualifying signal
# check-merge-eligibility.sh's reaction-path fact requires, so it alone
# reports completion_kind "clean_reaction"; the marker comment is a genuine
# "bot responded" signal but not what that fact accepts (comment landed,
# reaction not yet earned is a real race — Codex posts the marker and earns
# the reaction via two separate API calls), so it reports the distinct
# completion_kind "clean_marker" instead, letting callers that must match the
# floor's stricter criteria branch on the two separately. A clean signal is
# accepted only when it is fresh: it must post-date --since-timestamp when
# given, else (the initial poll) the point the current head became HEAD —
# max( PR head commit's committer date, latest head_ref_force_pushed timeline
# event ), since a force-push can re-point HEAD at an older commit. If that
# freshness bound cannot be established, clean signals are rejected that round
# (fail closed). `completion_kind` distinguishes "review" / "clean_reaction" /
# "clean_marker" / "timeout"; only "timeout" should count against a caller's
# silent-ask budget.
# If a clean-signal endpoint (reactions / issue comments) is FAILING at the
# deadline, a clean pass and bot silence are indistinguishable — so the script
# exits 3 (infrastructure error), NOT 1/timeout, and a transport failure is
# never miscounted as a silent bot ask.
#
# Exit codes:
#   0 — Review found (JSON on stdout)
#   1 — Timeout (no review within --timeout-seconds, default ~10 minutes)
#   2 — Copilot not requested (not added as reviewer within ~1 minute)
#   3 — Error (auth failure, invalid args, network issue, or a clean-signal
#       endpoint failing at the deadline)
#
# Stdout (exit 0):
#   { "status": "copilot_review_found", "completion_kind": "review"|"clean_reaction"|"clean_marker", "reviews": [...], "inline_comments": [...], "human_comments": [...] }
# Stdout (exit 1):
#   { "status": "copilot_review_timeout", "completion_kind": "timeout" }
# Stdout (exit 2):
#   { "status": "copilot_not_requested" }
# Stdout (exit 3, clean-signal endpoint failed at the deadline):
#   { "status": "copilot_review_error", "completion_kind": "error", "message": "clean-signal endpoint failure: <endpoints>" }
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

# Comment-triggered bot identities (mirrors request-rereview.sh's identity
# dispatch table) — these bots are never added as a requested reviewer; they
# are triggered by an '@codex review' issue comment instead. When
# --bot-reviewers includes one of these, Sub-phase A's requested-reviewer
# probe is not a valid precondition for the whole policy (see Sub-phase A
# below).
COMMENT_TRIGGERED_BOTS='["chatgpt-codex-connector[bot]"]'

HAS_COMMENT_TRIGGERED_BOT=false
if [[ -n "$BOT_REVIEWERS" ]]; then
    if jq -e --argjson known "$COMMENT_TRIGGERED_BOTS" \
        '(map(ascii_downcase)) as $mine | ($known | map(ascii_downcase)) as $known_lc | any($mine[]; . as $m | $known_lc | index($m) != null)' \
        <<<"$BOT_REVIEWERS" >/dev/null 2>&1; then
        HAS_COMMENT_TRIGGERED_BOT=true
    fi
fi

# ── Helper functions ──────────────────────────────────────────────────────────

pr_is_open() {
    local state
    state=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}" --jq '.state') || return 1
    [[ "$state" == "open" ]]
}

# emit_clean_signal_found <completion_kind> — shared stdout payload for both
# clean-pass completion signals (a `+1` reaction and a marker comment carry
# no review content, so both report the same empty-arrays shape). The kind
# itself is NOT shared: a `+1` reaction reports "clean_reaction" (the real
# qualifying signal check-merge-eligibility.sh's reaction-path fact
# requires); a marker comment alone reports the distinct "clean_marker" —
# see the header's Poll completion contract for why they must not collapse
# into one kind.
emit_clean_signal_found() {
    local kind="$1"
    jq -n --arg kind "$kind" '{
        status: "copilot_review_found",
        completion_kind: $kind,
        reviews: [],
        inline_comments: [],
        human_comments: []
    }'
}

# fetch_head_sha — the PR's current head commit SHA, freshly fetched (never
# cached — a push landing mid-poll is reflected on the NEXT attempt rather
# than compared against a stale snapshot), or empty stdout on any failure
# (API error, missing/null .head.sha). Callers checking freshness — the
# initial-poll review filter and the committer-date bound below — both need
# this same fetch and share it here rather than duplicating the `gh_api`
# call, even though they use the SHA for different purposes (equality vs.
# looking up a commit date) and must remain free to fail independently.
fetch_head_sha() {
    local head_sha
    head_sha=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}" --jq '.head.sha') || return 0
    [[ -n "$head_sha" && "$head_sha" != "null" ]] || return 0
    printf '%s' "$head_sha"
}

# head_committer_epoch — the PR head commit's committer date as epoch seconds,
# or empty on any failure (unfetchable head SHA, missing/unparseable date).
# Committer dates are GitHub-API timestamps normalized to UTC `Z`, parsed the
# same fromdateiso8601 way as the reaction/comment created_at values.
head_committer_epoch() {
    local head_sha date_iso
    head_sha=$(fetch_head_sha)
    [[ -n "$head_sha" ]] || return 0
    date_iso=$(gh_api "repos/${OWNER}/${REPO}/commits/${head_sha}" --jq '.commit.committer.date') || return 0
    [[ -n "$date_iso" && "$date_iso" != "null" ]] || return 0
    printf '%s' "$date_iso" | jq -Rr 'fromdateiso8601? // empty' 2>/dev/null
}

# latest_force_push_epoch — created_at (epoch seconds) of the latest
# head_ref_force_pushed timeline event, or empty stdout when no such event
# exists (committer date alone then bounds freshness). Returns non-zero to
# signal a fail-closed condition: a timeline fetch failure, or force-push
# events present but none carrying a parseable created_at. The timeline is a
# top-level array paginated the same `--paginate | jq -s 'add // []'` way as the
# merge-guard reads (real `gh --paginate` streams one array per page).
latest_force_push_epoch() {
    local timeline count max_epoch
    timeline=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/timeline?per_page=100" --paginate | jq -s 'add // []') || return 1
    count=$(printf '%s' "$timeline" | jq '[.[] | select(.event == "head_ref_force_pushed")] | length') || return 1
    [[ "$count" =~ ^[0-9]+$ ]] || return 1
    [[ "$count" -gt 0 ]] || return 0
    max_epoch=$(printf '%s' "$timeline" | jq -r \
        '[.[] | select(.event == "head_ref_force_pushed") | .created_at | fromdateiso8601?] | max // empty') || return 1
    [[ -n "$max_epoch" ]] || return 1
    printf '%s' "$max_epoch"
}

# head_clean_bound_epoch — the clean-signal freshness bound on the initial poll
# (no --since-timestamp): max( head commit committer date, latest
# head_ref_force_pushed timeline event created_at ) in epoch seconds. Mirrors the
# merge-guard clean-pass predicate's last_head_change (codex-rereview spec,
# Component 2): a force-push can re-point HEAD at an older commit, so the committer
# date alone under-bounds freshness and would accept a stale reaction. Empty on
# any fail-closed condition — an unfetchable/unparseable committer date, or a
# timeline fetch failure — so the caller rejects clean signals that round. No
# force-push event → committer date alone (prior behavior).
head_clean_bound_epoch() {
    local committer_epoch force_push_epoch
    committer_epoch=$(head_committer_epoch)
    [[ -n "$committer_epoch" ]] || return 0
    force_push_epoch=$(latest_force_push_epoch) || return 1
    if [[ -n "$force_push_epoch" && "$force_push_epoch" -gt "$committer_epoch" ]]; then
        printf '%s' "$force_push_epoch"
    else
        printf '%s' "$committer_epoch"
    fi
}

# ── Pre-flight checks ────────────────────────────────────────────────────────

preflight_checks

# ── Sub-phase A: Request detection (20s × 3, max ~1 minute) ──────────────────

if [[ "$SKIP_REQUEST" == false && "$HAS_COMMENT_TRIGGERED_BOT" == false ]]; then
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
    if [[ "$SKIP_REQUEST" == true ]]; then
        echo "Sub-phase A: Skipped (--skip-request-check)" >&2
    else
        echo "Sub-phase A: Skipped (--bot-reviewers includes a comment-triggered identity; requested-reviewer probe is not a precondition)" >&2
    fi
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

# Names the clean-signal endpoint(s) that failed on the CURRENT attempt (reset
# each iteration). If it is still set when the loop exhausts, clean signals were
# unobservable at the deadline: a clean pass and bot silence are
# indistinguishable, so the poll exits 3 (infra error) rather than reporting a
# timeout the caller would miscount as a silent ask.
clean_signal_failed_endpoint=""

for i in $(seq 1 "$MAX_ITERATIONS"); do
    clean_signal_failed_endpoint=""

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
    else
        # Initial poll (no --since-timestamp): no timestamp bound exists, so
        # freshness is established by requiring the review's own `.commit_id`
        # to equal the CURRENT PR head -- mirrors check-merge-eligibility.sh's
        # review-path acceptance criteria (`.commit_id == head`) exactly.
        # Unlike the reaction/marker clean-pass signals below, a review
        # object carries the exact commit it was submitted against, so exact
        # equality is available and strictly more precise than a time-based
        # approximation (agents-config-abn9.44.14). A review whose commit_id
        # predates the current head is a response to code that is no longer
        # at HEAD, not a response to what is there now -- it must not
        # complete the poll. A legitimate review AT the current head is
        # unaffected: its own commit_id equals the freshly-fetched head, so
        # first-pass detection has no regression. Fail closed: an unfetchable
        # head rejects ALL reviews this round rather than risk accepting a
        # stale one.
        current_head=$(fetch_head_sha)
        if [[ -z "$current_head" ]]; then
            echo "  Attempt ${i}/${MAX_ITERATIONS}: could not fetch current head, rejecting reviews this round (fail closed)" >&2
            reviews='[]'
        else
            fresh_reviews=$(printf '%s' "$reviews" | jq --arg head "$current_head" '[.[] | select(.commit_id == $head)]')
            stale_count=$(printf '%s' "$reviews" | jq --arg head "$current_head" '[.[] | select(.commit_id != $head)] | length')
            if [[ "$stale_count" -gt 0 ]]; then
                echo "  Attempt ${i}/${MAX_ITERATIONS}: found ${stale_count} stale review(s) (commit_id != ${current_head}), discarding" >&2
            fi
            reviews="$fresh_reviews"
        fi
    fi

    # APPROVED or COMMENTED are both a completed review — mirrors
    # check-merge-eligibility.sh's own review path (Component 2 part (a)),
    # which accepts either as a legitimate clean pass. Missing APPROVED here
    # made a bot's clean first-pass approval indistinguishable from silence.
    count=$(printf '%s' "$reviews" | jq '[.[] | select(.state == "APPROVED" or .state == "COMMENTED")] | length')

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
    # body, or a clean-pass marker issue comment. Only checked in policy mode
    # (--bot-reviewers set); the standalone Copilot-substring default never
    # sees either signal.
    #
    # Clean signals need a freshness bound so a `+1`/marker earned by an EARLIER
    # head cannot terminate monitoring for a head that received no review (Codex
    # tears the reaction down when it re-reviews a new head, but not if it is
    # down or rate-limited). With --since-timestamp, SINCE is the (stricter,
    # later) bound. Without it — the initial poll — bound by when the current head
    # became HEAD: max( head commit committer date, latest head_ref_force_pushed
    # timeline event ), since a force-push can re-point HEAD at an older commit
    # whose committer date predates a stale reaction. Fail closed: no usable bound
    # rejects clean signals this round; review objects above are unaffected.
    # Comparison is epoch seconds (fromdateiso8601); an unparseable created_at is
    # rejected per item. The bound/created_at comparison is uniformly STRICT >
    # for both bound sources. Both bounds and created_at are only second-precision,
    # so an equal-second collision is realistic: capturing SINCE before dispatch
    # does not establish causality for a signal already present in the same second
    # (a stale `+1`/marker from the prior clean pass, when a fix is pushed
    # immediately after, can have created_at == SINCE). Accepting the tie would end
    # monitoring on a prior-head signal without reviewing the pushed fix — an
    # unsound false-accept; rejecting it costs at most one poll timeout that hands
    # off safely. Soundness over liveness on second-precision ties (spec Component 2
    # pins strictly-greater for the head-date bound; the ask bound follows suit).
    if [[ -n "$BOT_REVIEWERS" ]]; then
        if [[ -n "$SINCE" ]]; then
            clean_bound_epoch=$(printf '%s' "$SINCE" | jq -Rr 'fromdateiso8601? // empty' 2>/dev/null) || clean_bound_epoch=""
        else
            clean_bound_epoch=$(head_clean_bound_epoch) || clean_bound_epoch=""
        fi

        if [[ -z "$clean_bound_epoch" ]]; then
            echo "  Attempt ${i}/${MAX_ITERATIONS}: no freshness bound for clean signals, rejecting (fail closed)" >&2
        else
            reactions=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/reactions?per_page=100" --paginate \
                | jq -s 'add // []' \
                | jq "[.[] | select(.content == \"+1\" and (.user.login | ${COPILOT_LOGIN_FILTER}))]") || {
                echo "Warning: reactions API failed (attempt ${i})" >&2
                reactions='[]'
                clean_signal_failed_endpoint="reactions"
            }
            reactions=$(printf '%s' "$reactions" | jq --argjson bound "$clean_bound_epoch" \
                '[.[] | select((.created_at | fromdateiso8601? // -1) > $bound)]')

            if [[ "$(printf '%s' "$reactions" | jq 'length')" -gt 0 ]]; then
                echo "  Clean-pass reaction found (attempt ${i})" >&2
                emit_clean_signal_found clean_reaction
                exit 0
            fi

            clean_comments=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/comments?per_page=100" --paginate \
                | jq -s 'add // []' \
                | jq "[.[] | select((.user.login | ${COPILOT_LOGIN_FILTER}) and ((.body // \"\") | startswith(\"${CLEAN_PASS_MARKER}\")))]") || {
                echo "Warning: issue comments API failed (attempt ${i})" >&2
                clean_comments='[]'
                clean_signal_failed_endpoint="${clean_signal_failed_endpoint:+$clean_signal_failed_endpoint, }issue comments"
            }
            clean_comments=$(printf '%s' "$clean_comments" | jq --argjson bound "$clean_bound_epoch" \
                '[.[] | select((.created_at | fromdateiso8601? // -1) > $bound)]')

            if [[ "$(printf '%s' "$clean_comments" | jq 'length')" -gt 0 ]]; then
                echo "  Clean-pass marker comment found (attempt ${i})" >&2
                emit_clean_signal_found clean_marker
                exit 0
            fi
        fi
    fi

    echo "  Attempt ${i}/${MAX_ITERATIONS}: no review yet" >&2
    [[ $i -lt $MAX_ITERATIONS ]] && sleep "$POLL_INTERVAL_SECONDS"
done

echo "Copilot review not received after ${TIMEOUT_SECONDS}s" >&2

# A clean-signal endpoint failing on the final attempt makes a clean pass
# indistinguishable from bot silence — report the documented infrastructure
# error (exit 3) rather than a timeout the caller would burn its silent-ask
# budget on.
if [[ -n "$clean_signal_failed_endpoint" ]]; then
    echo "Error: clean-signal endpoint(s) failed at the deadline (${clean_signal_failed_endpoint}); cannot distinguish a clean pass from bot silence" >&2
    jq -n --arg ep "$clean_signal_failed_endpoint" '{
        status: "copilot_review_error",
        completion_kind: "error",
        message: ("clean-signal endpoint failure: " + $ep)
    }'
    exit 3
fi

jq -n '{"status": "copilot_review_timeout", "completion_kind": "timeout"}'
exit 1

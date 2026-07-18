#!/usr/bin/env bash
# Smoke test for poll-copilot-review.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/poll-copilot-review.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0

assert() {
  if eval "$2"; then
    echo "  ok: $1"
  else
    echo "  FAIL: $1"
    FAIL=1
  fi
}

echo "[poll-copilot-review_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -25 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"
assert "no positional owner/repo parsing" "! grep -qE '^\s*REPO=\"\\\$1\"' '$SCRIPT'"

# Missing required flags — exit 3
"$SCRIPT" 2>/dev/null
rc_no_args=$?
assert "exits 3 with no flags" "[ \$rc_no_args -eq 3 ]"

"$SCRIPT" --owner o --repo r 2>/dev/null
rc_no_pr=$?
assert "exits 3 when --pr missing" "[ \$rc_no_pr -eq 3 ]"

"$SCRIPT" --owner o --pr 1 2>/dev/null
rc_no_repo=$?
assert "exits 3 when --repo missing" "[ \$rc_no_repo -eq 3 ]"

"$SCRIPT" --repo r --pr 1 2>/dev/null
rc_no_owner=$?
assert "exits 3 when --owner missing" "[ \$rc_no_owner -eq 3 ]"

# Bad --pr value
"$SCRIPT" --owner o --repo r --pr notanumber 2>/dev/null
rc_bad_pr=$?
assert "exits 3 for non-integer --pr" "[ \$rc_bad_pr -eq 3 ]"

# Unknown flag
"$SCRIPT" --owner o --repo r --pr 1 --bogus 2>/dev/null
rc_bogus=$?
assert "exits 3 for unknown flag" "[ \$rc_bogus -eq 3 ]"

# Trailing flag with no value — must exit 3 (not silent exit 1)
"$SCRIPT" --owner 2>/dev/null
rc_dangling=$?
assert "exits 3 for flag with no value (not silent exit 1)" "[ \$rc_dangling -eq 3 ]"

# ── --timeout-seconds (plumbs Axis-1 bot_inactivity_timeout_seconds) ─────────

assert "accepts --timeout-seconds flag" "grep -q -- '--timeout-seconds' '$SCRIPT'"

"$SCRIPT" --owner o --repo r --pr 1 --timeout-seconds notanumber 2>/dev/null
rc_bad_timeout=$?
assert "exits 3 for non-integer --timeout-seconds" "[ \$rc_bad_timeout -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --timeout-seconds 0 2>/dev/null
rc_zero_timeout=$?
assert "exits 3 for --timeout-seconds 0" "[ \$rc_zero_timeout -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --timeout-seconds -5 2>/dev/null
rc_neg_timeout=$?
assert "exits 3 for negative --timeout-seconds" "[ \$rc_neg_timeout -eq 3 ]"

# ── --timeout-seconds drives the deadline (gh stub, no real gh calls) ───────────

STUB_DIR="$TMP/bin"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
[ "$1" = "auth" ] && exit 0
if [ "$1" = "api" ]; then
  shift
  path="$1"; shift
  filter=""
  while [ $# -gt 0 ]; do
    case "$1" in --jq) filter="$2"; shift 2 ;; *) shift ;; esac
  done
  case "$path" in
    */issues/*/events*)    body="${FIXTURE_EVENTS:-[]}" ;;
    */issues/*/reactions*) body="${FIXTURE_REACTIONS:-[]}" ;;
    */issues/*/comments*)  body="${FIXTURE_ISSUE_COMMENTS:-[]}" ;;
    */issues/*/timeline*)
        if [ "${FIXTURE_TIMELINE_FAIL:-0}" = 1 ]; then
          echo "gh: 500 Internal Server Error" >&2; exit 1
        fi
        body="${FIXTURE_TIMELINE:-[]}" ;;
    */pulls/*/reviews*)    body="${FIXTURE_REVIEWS:-[]}" ;;
    */pulls/*/comments*)   body="${FIXTURE_COMMENTS:-[]}" ;;
    */commits/*)           body="${FIXTURE_COMMIT:-'{}'}" ;;
    */pulls/*)             body="${FIXTURE_PR:-'{"state":"open"}'}" ;;
    *)                     body='{}' ;;
  esac
  body="${body#\'}"; body="${body%\'}"
  if [ -n "$filter" ]; then printf '%s' "$body" | jq -r "$filter"; else printf '%s' "$body"; fi
  exit 0
fi
exit 0
STUB
chmod +x "$STUB_DIR/gh"

# Skip sub-phase A (--skip-request-check) and make sub-phase B resolve on its
# first attempt (copilot_work_started already present) so no real sleep is
# incurred before reaching sub-phase C's timeout loop.
FIXTURE_EVENTS_STARTED='[{"event":"copilot_work_started"}]'

start_ts=$(date +%s)
out=$(env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 2>/dev/null)
rc_tiny_timeout=$?
end_ts=$(date +%s)
elapsed=$((end_ts - start_ts))

assert "tiny --timeout-seconds exits 1 (timeout)" "[ \$rc_tiny_timeout -eq 1 ]"
assert "tiny --timeout-seconds reports copilot_review_timeout" "printf '%s' '$out' | grep -q copilot_review_timeout"
assert "tiny --timeout-seconds does not wait for the default ~10-minute window" "[ \$elapsed -lt 15 ]"

# ── --bot-reviewers (generalizes the poll to non-Copilot policy bots) ────────

assert "accepts --bot-reviewers flag" "grep -q -- '--bot-reviewers' '$SCRIPT'"

# Malformed values must be rejected up front (exit 3), not silently ignored.
"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers 'not-json' 2>/dev/null
rc_bad_bots=$?
assert "exits 3 for non-array --bot-reviewers" "[ \$rc_bad_bots -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '[]' 2>/dev/null
rc_empty_bots=$?
assert "exits 3 for empty --bot-reviewers array" "[ \$rc_empty_bots -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["ok", 3]' 2>/dev/null
rc_mixed_bots=$?
assert "exits 3 for --bot-reviewers array with a non-string" "[ \$rc_mixed_bots -eq 3 ]"

# A non-Copilot bot review is found ONLY when its identity is in --bot-reviewers,
# proving the poll matches by policy allowlist, not the hardcoded Copilot substring.
FIXTURE_REVIEWS_OTHERBOT='[{"user":{"login":"My-Bot[bot]","type":"Bot"},"state":"COMMENTED","submitted_at":"2026-01-01T00:00:00Z"}]'

out_bot=$(env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS="$FIXTURE_REVIEWS_OTHERBOT" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 5 --bot-reviewers '["my-bot[bot]"]' 2>/dev/null)
rc_bot=$?
assert "non-Copilot bot in --bot-reviewers yields a found review (exit 0)" "[ \$rc_bot -eq 0 ]"
assert "matched review reports copilot_review_found" "printf '%s' \"\$out_bot\" | grep -q copilot_review_found"

# Control: the same bot is invisible to the default Copilot filter → timeout.
env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS="$FIXTURE_REVIEWS_OTHERBOT" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 >/dev/null 2>&1
rc_default=$?
assert "default Copilot filter does NOT match the non-Copilot bot (timeout, exit 1)" "[ \$rc_default -eq 1 ]"

# A findings review reports completion_kind "review".
assert "matched review reports completion_kind review" "printf '%s' \"\$out_bot\" | jq -e '.completion_kind == \"review\"' >/dev/null"

# ── Poll completion contract (Component 3): clean-pass completion ───────────
# A clean bot pass submits no review object at all — only a `+1` reaction on
# the PR body, or a clean-pass marker issue comment, post-dating the ask
# (--since-timestamp). Both must be recognised as completion (exit 0,
# completion_kind "clean_reaction"), and ONLY a true timeout may report
# completion_kind "timeout" — that is the only outcome a caller may count as
# a silent ask against its retry cap.

CODEX_ID='chatgpt-codex-connector[bot]'
SINCE_TS='2026-01-01T00:00:00Z'

# Clean case 1: a `+1` reaction from an allowlisted identity, post-dating the ask.
FIXTURE_REACTIONS_CLEAN='[{"id":1,"content":"+1","user":{"login":"chatgpt-codex-connector[bot]","type":"Bot"},"created_at":"2026-01-01T00:00:10Z"}]'

out_reaction=$(env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_CLEAN" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --since-timestamp "$SINCE_TS" --bot-reviewers "[\"$CODEX_ID\"]" 2>/dev/null)
rc_reaction=$?
assert "a post-dating +1 reaction completes (exit 0)" "[ \$rc_reaction -eq 0 ]"
assert "a post-dating +1 reaction reports completion_kind clean_reaction" "printf '%s' \"\$out_reaction\" | jq -e '.completion_kind == \"clean_reaction\"' >/dev/null"

# Clean case 2: a clean-pass marker issue comment from an allowlisted identity,
# post-dating the ask — no reaction present at all.
FIXTURE_ISSUE_COMMENTS_CLEAN="[{\"id\":2,\"user\":{\"login\":\"$CODEX_ID\"},\"body\":\"Codex Review: Didn't find any major issues in this PR.\",\"created_at\":\"2026-01-01T00:00:10Z\"}]"

out_comment=$(env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_REACTIONS='[]' FIXTURE_ISSUE_COMMENTS="$FIXTURE_ISSUE_COMMENTS_CLEAN" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --since-timestamp "$SINCE_TS" --bot-reviewers "[\"$CODEX_ID\"]" 2>/dev/null)
rc_comment=$?
assert "a post-dating marker comment completes (exit 0)" "[ \$rc_comment -eq 0 ]"
assert "a post-dating marker comment reports completion_kind clean_reaction" "printf '%s' \"\$out_comment\" | jq -e '.completion_kind == \"clean_reaction\"' >/dev/null"

# A `+1` reaction that PREDATES the ask must NOT complete (stale-cache guard,
# same discipline as the existing review submitted_at filter) — falls through
# to a real timeout.
FIXTURE_REACTIONS_STALE='[{"id":3,"content":"+1","user":{"login":"chatgpt-codex-connector[bot]","type":"Bot"},"created_at":"2025-12-31T23:59:00Z"}]'

env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_STALE" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --since-timestamp "$SINCE_TS" --bot-reviewers "[\"$CODEX_ID\"]" >/dev/null 2>&1
rc_stale_reaction=$?
assert "a pre-dating +1 reaction does NOT complete (timeout, exit 1)" "[ \$rc_stale_reaction -eq 1 ]"

# The inverse: nothing arrives at all → real timeout, completion_kind "timeout".
out_timeout=$(env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_REACTIONS='[]' FIXTURE_ISSUE_COMMENTS='[]' \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --since-timestamp "$SINCE_TS" --bot-reviewers "[\"$CODEX_ID\"]" 2>/dev/null)
rc_timeout=$?
assert "no signal at all times out (exit 1)" "[ \$rc_timeout -eq 1 ]"
assert "timeout reports completion_kind timeout" "printf '%s' \"\$out_timeout\" | jq -e '.completion_kind == \"timeout\"' >/dev/null"

# Without --bot-reviewers, the clean-reaction/marker-comment checks never run
# (Copilot never emits either signal) — a fixture that WOULD complete under
# --bot-reviewers must still time out under the standalone Copilot default.
env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_CLEAN" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 >/dev/null 2>&1
rc_no_policy=$?
assert "clean-reaction signal is ignored without --bot-reviewers (timeout, exit 1)" "[ \$rc_no_policy -eq 1 ]"

# ── Equal-second clean signal on the ask-bound (--since-timestamp) path ──────
# SINCE is captured to second precision immediately before dispatch; GitHub
# reaction/comment created_at is also second precision. A fast Codex clean
# response created in that same second has created_at == SINCE. Causality — the
# capture precedes the ask, which precedes any response — makes an equal-second
# signal necessarily this round's, so the ask-bound path accepts it (>=), where
# the head-date bound below keeps strict >.

FIXTURE_REACTIONS_EQUAL="[{\"id\":4,\"content\":\"+1\",\"user\":{\"login\":\"$CODEX_ID\",\"type\":\"Bot\"},\"created_at\":\"$SINCE_TS\"}]"

out_equal_reaction=$(env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_EQUAL" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --since-timestamp "$SINCE_TS" --bot-reviewers "[\"$CODEX_ID\"]" 2>/dev/null)
rc_equal_reaction=$?
assert "ask-bound: +1 created in the ask second completes (exit 0)" "[ \$rc_equal_reaction -eq 0 ]"
assert "ask-bound: equal-second +1 reports completion_kind clean_reaction" "printf '%s' \"\$out_equal_reaction\" | jq -e '.completion_kind == \"clean_reaction\"' >/dev/null"

FIXTURE_ISSUE_COMMENTS_EQUAL="[{\"id\":5,\"user\":{\"login\":\"$CODEX_ID\"},\"body\":\"Codex Review: Didn't find any major issues in this PR.\",\"created_at\":\"$SINCE_TS\"}]"

out_equal_comment=$(env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_REACTIONS='[]' FIXTURE_ISSUE_COMMENTS="$FIXTURE_ISSUE_COMMENTS_EQUAL" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --since-timestamp "$SINCE_TS" --bot-reviewers "[\"$CODEX_ID\"]" 2>/dev/null)
rc_equal_comment=$?
assert "ask-bound: marker comment created in the ask second completes (exit 0)" "[ \$rc_equal_comment -eq 0 ]"
assert "ask-bound: equal-second marker comment reports completion_kind clean_reaction" "printf '%s' \"\$out_equal_comment\" | jq -e '.completion_kind == \"clean_reaction\"' >/dev/null"

# Only "timeout" may count as a silent ask against a caller's retry cap: chain
# the actual accounting helper the skill uses, mapping this script's exit
# code the way SKILL.md Phase 6 does (0 -> --event none, 1 -> --event silent).
# A clean_reaction completion (exit 0) must NOT advance the silent counter; a
# real timeout (exit 1) must.
map_to_polling_event() { [ "$1" -eq 0 ] && echo none || echo silent; }

polling_after_clean=$("$HERE/compute-rereview-polling.sh" --prior-count 0 --prior-exhausted false \
  --event "$(map_to_polling_event "$rc_reaction")")
assert "clean_reaction completion does NOT increment the silent-ask counter" \
  "[ \"\$(jq '.rereview_round_count' <<<\"\$polling_after_clean\")\" = 0 ]"

polling_after_timeout=$("$HERE/compute-rereview-polling.sh" --prior-count 0 --prior-exhausted false \
  --event "$(map_to_polling_event "$rc_timeout")")
assert "a real timeout DOES increment the silent-ask counter" \
  "[ \"\$(jq '.rereview_round_count' <<<\"\$polling_after_timeout\")\" = 1 ]"

# ── Initial-poll freshness (no --since-timestamp) ────────────────────────────
# On the initial policy-mode round SINCE is empty, so clean signals must be
# bounded by the PR head commit's committer date. A `+1`/marker earned by an
# EARLIER head (Codex tears it down on re-review, but not if it is down or
# rate-limited) must NOT terminate monitoring for a head that received no
# review; a signal post-dating the head commit is a real clean pass. An
# unfetchable/unparseable head date fails closed (rejects clean signals).

HEAD_SHA='abc123def4567890'
FIXTURE_PR_HEAD="{\"state\":\"open\",\"head\":{\"sha\":\"$HEAD_SHA\"}}"
FIXTURE_COMMIT_HEADDATE='{"commit":{"committer":{"date":"2026-01-01T00:00:00Z"}}}'

# (a) A `+1` predating the head committer date is NOT accepted on the initial
#     poll (no --since-timestamp) — falls through to a real timeout.
FIXTURE_REACTIONS_PREHEAD='[{"id":10,"content":"+1","user":{"login":"chatgpt-codex-connector[bot]","type":"Bot"},"created_at":"2025-12-31T23:59:00Z"}]'

env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_PR="$FIXTURE_PR_HEAD" FIXTURE_COMMIT="$FIXTURE_COMMIT_HEADDATE" \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_PREHEAD" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --bot-reviewers "[\"$CODEX_ID\"]" >/dev/null 2>&1
rc_preheaddate=$?
assert "initial poll: +1 predating head committer date does NOT complete (timeout, exit 1)" "[ \$rc_preheaddate -eq 1 ]"

# (b) A `+1` post-dating the head committer date IS accepted on the initial poll
#     (no --since-timestamp), completion_kind clean_reaction.
FIXTURE_REACTIONS_POSTHEAD='[{"id":11,"content":"+1","user":{"login":"chatgpt-codex-connector[bot]","type":"Bot"},"created_at":"2026-01-01T00:00:10Z"}]'

out_posthead=$(env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_PR="$FIXTURE_PR_HEAD" FIXTURE_COMMIT="$FIXTURE_COMMIT_HEADDATE" \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_POSTHEAD" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --bot-reviewers "[\"$CODEX_ID\"]" 2>/dev/null)
rc_posthead=$?
assert "initial poll: +1 post-dating head committer date completes (exit 0)" "[ \$rc_posthead -eq 0 ]"
assert "initial poll: post-dating +1 reports completion_kind clean_reaction" "printf '%s' \"\$out_posthead\" | jq -e '.completion_kind == \"clean_reaction\"' >/dev/null"

# (b2) A `+1` created in the SAME second as the head committer date is still
#      REJECTED on the initial poll (no --since-timestamp): the head-date bound
#      keeps strict > because an equal-second reaction could belong to the
#      pre-push head (the ~10s tear-down race), per spec Component 2 — the
#      asymmetric counterpart to the ask-bound path's inclusive >=.
FIXTURE_REACTIONS_EQUALHEAD='[{"id":12,"content":"+1","user":{"login":"chatgpt-codex-connector[bot]","type":"Bot"},"created_at":"2026-01-01T00:00:00Z"}]'

env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_PR="$FIXTURE_PR_HEAD" FIXTURE_COMMIT="$FIXTURE_COMMIT_HEADDATE" \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_EQUALHEAD" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --bot-reviewers "[\"$CODEX_ID\"]" >/dev/null 2>&1
rc_equalhead=$?
assert "initial poll: +1 in the same second as head committer date does NOT complete (timeout, exit 1)" "[ \$rc_equalhead -eq 1 ]"

# (c) An unparseable head committer date rejects clean signals on the initial
#     poll (fail closed) — even a would-be-fresh `+1`.
FIXTURE_COMMIT_BADDATE='{"commit":{"committer":{"date":"not-a-date"}}}'

env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_PR="$FIXTURE_PR_HEAD" FIXTURE_COMMIT="$FIXTURE_COMMIT_BADDATE" \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_POSTHEAD" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --bot-reviewers "[\"$CODEX_ID\"]" >/dev/null 2>&1
rc_baddate=$?
assert "initial poll: unparseable head committer date rejects clean signals (fail closed, exit 1)" "[ \$rc_baddate -eq 1 ]"

# ── Initial-poll freshness with a force-push timeline event ─────────────────
# The bound is max( head committer date, latest head_ref_force_pushed timeline
# event created_at ) — mirroring the merge-guard clean-pass predicate (codex-
# rereview spec, Component 2). A force-push can re-point HEAD at an OLDER commit,
# leaving a prior `+1` later than that commit's committer date yet still stale
# relative to when the head actually changed. A +1 between the committer date and
# the force-push event is stale (REJECTED); a +1 after the force-push event is a
# real clean pass (ACCEPTED). A timeline fetch failure fails closed.

FIXTURE_TIMELINE_FORCEPUSH='[{"event":"head_ref_force_pushed","created_at":"2026-01-01T00:05:00Z"}]'

# (d) A +1 AFTER the committer date but BEFORE the force-push event is stale —
#     the force-push moved the head later than that reaction.
FIXTURE_REACTIONS_BETWEEN='[{"id":20,"content":"+1","user":{"login":"chatgpt-codex-connector[bot]","type":"Bot"},"created_at":"2026-01-01T00:02:00Z"}]'

env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_PR="$FIXTURE_PR_HEAD" FIXTURE_COMMIT="$FIXTURE_COMMIT_HEADDATE" \
  FIXTURE_TIMELINE="$FIXTURE_TIMELINE_FORCEPUSH" \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_BETWEEN" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --bot-reviewers "[\"$CODEX_ID\"]" >/dev/null 2>&1
rc_between=$?
assert "initial poll: +1 between committer date and force-push event is stale (timeout, exit 1)" "[ \$rc_between -eq 1 ]"

# (e) A +1 AFTER the force-push event is a real clean pass.
FIXTURE_REACTIONS_AFTERPUSH='[{"id":21,"content":"+1","user":{"login":"chatgpt-codex-connector[bot]","type":"Bot"},"created_at":"2026-01-01T00:10:00Z"}]'

out_afterpush=$(env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_PR="$FIXTURE_PR_HEAD" FIXTURE_COMMIT="$FIXTURE_COMMIT_HEADDATE" \
  FIXTURE_TIMELINE="$FIXTURE_TIMELINE_FORCEPUSH" \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_AFTERPUSH" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --bot-reviewers "[\"$CODEX_ID\"]" 2>/dev/null)
rc_afterpush=$?
assert "initial poll: +1 after the force-push event completes (exit 0)" "[ \$rc_afterpush -eq 0 ]"
assert "initial poll: +1 after force-push reports completion_kind clean_reaction" "printf '%s' \"\$out_afterpush\" | jq -e '.completion_kind == \"clean_reaction\"' >/dev/null"

# (f) A timeline fetch failure fails closed — even a would-be-fresh +1 is rejected.
env PATH="$STUB_DIR:$PATH" FIXTURE_EVENTS="$FIXTURE_EVENTS_STARTED" FIXTURE_REVIEWS='[]' \
  FIXTURE_PR="$FIXTURE_PR_HEAD" FIXTURE_COMMIT="$FIXTURE_COMMIT_HEADDATE" \
  FIXTURE_TIMELINE_FAIL=1 \
  FIXTURE_REACTIONS="$FIXTURE_REACTIONS_AFTERPUSH" \
  "$SCRIPT" --owner o --repo r --pr 1 --skip-request-check --timeout-seconds 1 \
  --bot-reviewers "[\"$CODEX_ID\"]" >/dev/null 2>&1
rc_tlfail=$?
assert "initial poll: timeline fetch failure fails closed (timeout, exit 1)" "[ \$rc_tlfail -eq 1 ]"

exit $FAIL

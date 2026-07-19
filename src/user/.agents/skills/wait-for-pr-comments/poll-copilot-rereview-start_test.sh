#!/usr/bin/env bash
# Smoke test for poll-copilot-rereview-start.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/poll-copilot-rereview-start.sh"
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

echo "[poll-copilot-rereview-start_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -25 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"
assert "accepts --after flag" "grep -q -- '--after' '$SCRIPT'"
assert "no positional owner/repo parsing" "! grep -qE '^\s*REPO=\"\\\$1\"' '$SCRIPT'"

# Missing required flags — exit 3
"$SCRIPT" 2>/dev/null
rc_no_args=$?
assert "exits 3 with no flags" "[ \$rc_no_args -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 2>/dev/null
rc_no_after=$?
assert "exits 3 when --after missing" "[ \$rc_no_after -eq 3 ]"

"$SCRIPT" --owner o --repo r --after 2026-01-01T00:00:00Z 2>/dev/null
rc_no_pr=$?
assert "exits 3 when --pr missing" "[ \$rc_no_pr -eq 3 ]"

# Bad --pr value
"$SCRIPT" --owner o --repo r --pr notanumber --after 2026-01-01T00:00:00Z 2>/dev/null
rc_bad_pr=$?
assert "exits 3 for non-integer --pr" "[ \$rc_bad_pr -eq 3 ]"

# Unknown flag
"$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z --bogus 2>/dev/null
rc_bogus=$?
assert "exits 3 for unknown flag" "[ \$rc_bogus -eq 3 ]"

# Trailing flag with no value — must exit 3 (not silent exit 1)
"$SCRIPT" --owner 2>/dev/null
rc_dangling=$?
assert "exits 3 for flag with no value (not silent exit 1)" "[ \$rc_dangling -eq 3 ]"

# ── --bot-reviewers (eyes-reaction start signal) ─────────────────────────────

assert "accepts --bot-reviewers flag" "grep -q -- '--bot-reviewers' '$SCRIPT'"

"$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z --bot-reviewers 'not-json' 2>/dev/null
rc_bad_bots=$?
assert "exits 3 for non-array --bot-reviewers" "[ \$rc_bad_bots -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z --bot-reviewers '[]' 2>/dev/null
rc_empty_bots=$?
assert "exits 3 for empty --bot-reviewers array" "[ \$rc_empty_bots -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z --bot-reviewers '["ok", 3]' 2>/dev/null
rc_mixed_bots=$?
assert "exits 3 for --bot-reviewers array with a non-string" "[ \$rc_mixed_bots -eq 3 ]"

# --- Fake-gh shim (argv-routed fixtures): dispatches on the endpoint path so
# a single fixture per test controls the events/reactions API response. Poll
# window collapsed to one fast attempt (INITIAL_SLEEP/POLL_INTERVAL=0,
# POLL_COUNT=1) so these tests don't pay the real 80s window.
FAKEBIN="$TMP/bin"
mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/gh" <<'FAKE'
#!/usr/bin/env bash
if [ "$1" = "auth" ] && [ "$2" = "status" ]; then
  exit 0
fi
if [ "$1" = "api" ]; then
  shift
  endpoint=""
  for arg in "$@"; do
    case "$arg" in
      --*) ;;
      *) endpoint="$arg"; break ;;
    esac
  done
  case "$endpoint" in
    */issues/*/events*)
      cat "${FAKE_EVENTS_FILE:-/dev/null}" 2>/dev/null || echo '[]'
      ;;
    */issues/*/reactions*)
      cat "${FAKE_REACTIONS_FILE:-/dev/null}" 2>/dev/null || echo '[]'
      ;;
    *) echo '[]' ;;
  esac
  exit 0
fi
exit 0
FAKE
chmod +x "$FAKEBIN/gh"

export INITIAL_SLEEP=0 POLL_INTERVAL=0 POLL_COUNT=1
EMPTY_EVENTS="$TMP/empty-events.json"
echo '[]' > "$EMPTY_EVENTS"
EMPTY_REACTIONS="$TMP/empty-reactions.json"
echo '[]' > "$EMPTY_REACTIONS"

# Regression: the original copilot_work_started event path still works
# standalone (no --bot-reviewers) — the pre-existing behavior this bead must
# not disturb.
EVENTS_FILE="$TMP/events-copilot.json"
cat > "$EVENTS_FILE" <<'JSON'
[{"event":"copilot_work_started","created_at":"2026-01-01T00:05:00Z"}]
JSON
out=$(FAKE_EVENTS_FILE="$EVENTS_FILE" PATH="$FAKEBIN:$PATH" "$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z 2>/dev/null)
rc_event=$?
assert "copilot_work_started event exits 0" "[ \$rc_event -eq 0 ]"
assert "copilot_work_started event reports signal event" "printf '%s' '$out' | jq -e '.signal == \"event\"' >/dev/null"

# Without --bot-reviewers, an eyes reaction is NOT checked — old behavior
# (Copilot-events-only) is preserved even if one happens to be present.
REACTIONS_EYES="$TMP/reactions-eyes.json"
cat > "$REACTIONS_EYES" <<'JSON'
[{"content":"eyes","user":{"login":"chatgpt-codex-connector[bot]"},"created_at":"2026-01-01T00:05:00Z"}]
JSON
FAKE_EVENTS_FILE="$EMPTY_EVENTS" FAKE_REACTIONS_FILE="$REACTIONS_EYES" PATH="$FAKEBIN:$PATH" \
  "$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z >/dev/null 2>&1
rc_no_flag=$?
assert "eyes reaction ignored when --bot-reviewers omitted (exit 1, old behavior)" "[ \$rc_no_flag -eq 1 ]"

# With --bot-reviewers, an eyes reaction from an allowlisted identity
# post-dating --after is a start signal.
out=$(FAKE_EVENTS_FILE="$EMPTY_EVENTS" FAKE_REACTIONS_FILE="$REACTIONS_EYES" PATH="$FAKEBIN:$PATH" \
  "$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' 2>/dev/null)
rc_eyes=$?
assert "eyes reaction from an allowlisted identity exits 0" "[ \$rc_eyes -eq 0 ]"
assert "eyes reaction reports signal eyes_reaction" "printf '%s' '$out' | jq -e '.signal == \"eyes_reaction\"' >/dev/null"

# Case-insensitive identity match, mirroring poll-copilot-review.sh's convention.
FAKE_EVENTS_FILE="$EMPTY_EVENTS" FAKE_REACTIONS_FILE="$REACTIONS_EYES" PATH="$FAKEBIN:$PATH" \
  "$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z \
  --bot-reviewers '["CHATGPT-CODEX-CONNECTOR[bot]"]' >/dev/null 2>&1
rc_ci=$?
assert "uppercase allowlist entry still matches (case-insensitive)" "[ \$rc_ci -eq 0 ]"

# An eyes reaction from an identity NOT on the allowlist is ignored.
REACTIONS_OTHER="$TMP/reactions-other.json"
cat > "$REACTIONS_OTHER" <<'JSON'
[{"content":"eyes","user":{"login":"some-other-bot[bot]"},"created_at":"2026-01-01T00:05:00Z"}]
JSON
FAKE_EVENTS_FILE="$EMPTY_EVENTS" FAKE_REACTIONS_FILE="$REACTIONS_OTHER" PATH="$FAKEBIN:$PATH" \
  "$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' >/dev/null 2>&1
rc_other=$?
assert "eyes reaction from a non-allowlisted identity is ignored (exit 1)" "[ \$rc_other -eq 1 ]"

# A non-eyes reaction (e.g. a clean-pass +1) is not a start signal.
REACTIONS_PLUS1="$TMP/reactions-plus1.json"
cat > "$REACTIONS_PLUS1" <<'JSON'
[{"content":"+1","user":{"login":"chatgpt-codex-connector[bot]"},"created_at":"2026-01-01T00:05:00Z"}]
JSON
FAKE_EVENTS_FILE="$EMPTY_EVENTS" FAKE_REACTIONS_FILE="$REACTIONS_PLUS1" PATH="$FAKEBIN:$PATH" \
  "$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' >/dev/null 2>&1
rc_plus1=$?
assert "a +1 reaction (not eyes) is not a start signal (exit 1)" "[ \$rc_plus1 -eq 1 ]"

# An eyes reaction that PREDATES --after is stale and ignored.
REACTIONS_STALE="$TMP/reactions-stale.json"
cat > "$REACTIONS_STALE" <<'JSON'
[{"content":"eyes","user":{"login":"chatgpt-codex-connector[bot]"},"created_at":"2025-12-31T23:00:00Z"}]
JSON
FAKE_EVENTS_FILE="$EMPTY_EVENTS" FAKE_REACTIONS_FILE="$REACTIONS_STALE" PATH="$FAKEBIN:$PATH" \
  "$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' >/dev/null 2>&1
rc_stale=$?
assert "an eyes reaction predating --after is ignored (exit 1)" "[ \$rc_stale -eq 1 ]"

# Neither an event nor an eyes reaction present: exits 1, no_rereview_started.
out=$(FAKE_EVENTS_FILE="$EMPTY_EVENTS" FAKE_REACTIONS_FILE="$EMPTY_REACTIONS" PATH="$FAKEBIN:$PATH" \
  "$SCRIPT" --owner o --repo r --pr 1 --after 2026-01-01T00:00:00Z \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' 2>/dev/null)
rc_none=$?
assert "neither signal present exits 1" "[ \$rc_none -eq 1 ]"
assert "neither signal present reports no_rereview_started" "printf '%s' '$out' | jq -e '.status == \"no_rereview_started\"' >/dev/null"

exit $FAIL

#!/usr/bin/env bash
# Smoke test for request-rereview.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/request-rereview.sh"
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

echo "[request-rereview_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "documents GraphQL projection in header" "head -60 '$SCRIPT' | grep -qiE 'graphql|projection|query'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"

# --- Fake-gh shim: any gh invocation succeeds with empty stdout ---
FAKEBIN="$TMP/bin"
mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/gh" <<'FAKE'
#!/usr/bin/env bash
# Fake gh — accepts remove+add reviewer calls, exits 0.
exit 0
FAKE
chmod +x "$FAKEBIN/gh"

# Happy path: with fake gh, request-rereview should exit 0.
PATH="$FAKEBIN:$PATH" "$SCRIPT" --owner o --repo r --pr 1 > "$TMP/out.txt" 2>&1
rc_happy=$?
assert "exits 0 on happy path with fake gh" "[ \$rc_happy -eq 0 ]"

# Failure path: missing required flag must error
if "$SCRIPT" 2>/dev/null; then
  echo "  FAIL: accepted invocation with no flags"
  FAIL=1
else
  echo "  ok: rejects missing required flags"
fi

# Failure path: unknown flag (--bogus FIRST so it's seen before any I/O)
if "$SCRIPT" --bogus --owner o --repo r --pr 1 2>/dev/null; then
  echo "  FAIL: accepted unknown flag"
  FAIL=1
else
  echo "  ok: rejects unknown flag"
fi

# ── --bot-reviewers (Component 1: per-bot re-review dispatch) ───────────────

assert "accepts --bot-reviewers flag" "grep -q -- '--bot-reviewers' '$SCRIPT'"

# Malformed values must be rejected up front (exit 2 — this script's usage-
# error code), not silently ignored.
"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers 'not-json' 2>/dev/null
rc_bad_bots=$?
assert "exits 2 for non-array --bot-reviewers" "[ \$rc_bad_bots -eq 2 ]"

"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '[]' 2>/dev/null
rc_empty_bots=$?
assert "exits 2 for empty --bot-reviewers array" "[ \$rc_empty_bots -eq 2 ]"

"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["ok", 3]' 2>/dev/null
rc_mixed_bots=$?
assert "exits 2 for --bot-reviewers array with a non-string" "[ \$rc_mixed_bots -eq 2 ]"

# --- Fake-gh shim (argv capture): logs every invocation; --add-reviewer / `gh
# pr comment` can be made to fail via FAKE_GH_FAIL_EDIT / FAKE_GH_FAIL_COMMENT
# so per-identity dispatch failure and the exit-code matrix can be exercised.
FAKEBIN2="$TMP/bin2"
mkdir -p "$FAKEBIN2"
export FAKE_GH_LOG="$TMP/fake-gh.log"
cat > "$FAKEBIN2/gh" <<'FAKE'
#!/usr/bin/env bash
# Fake gh — logs every invocation; --add-reviewer / pr comment can be made to
# fail via FAKE_GH_FAIL_EDIT / FAKE_GH_FAIL_COMMENT env vars.
LOG="${FAKE_GH_LOG:-/tmp/fake-gh.log}"
echo "$@" >> "$LOG"
for arg in "$@"; do
  if [ "$arg" = "--add-reviewer" ] && [ "${FAKE_GH_FAIL_EDIT:-0}" = "1" ]; then
    echo "fake-gh: simulated add-reviewer failure" >&2
    exit 1
  fi
done
if [ "$1" = "pr" ] && [ "$2" = "comment" ] && [ "${FAKE_GH_FAIL_COMMENT:-0}" = "1" ]; then
  echo "fake-gh: simulated comment failure" >&2
  exit 1
fi
exit 0
FAKE
chmod +x "$FAKEBIN2/gh"

# Per-identity dispatch: Copilot -> remove+re-add reviewer dance.
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["Copilot"]' >/dev/null 2>&1
rc_copilot=$?
assert "Copilot identity exits 0" "[ \$rc_copilot -eq 0 ]"
assert "Copilot identity dispatches --remove-reviewer @copilot" "grep -qF -- '--remove-reviewer @copilot' '$FAKE_GH_LOG'"
assert "Copilot identity dispatches --add-reviewer @copilot" "grep -qF -- '--add-reviewer @copilot' '$FAKE_GH_LOG'"
assert "Copilot identity does NOT post a codex review comment" "! grep -qF 'pr comment' '$FAKE_GH_LOG'"

# Per-identity dispatch: copilot-pull-request-reviewer[bot] (exact GH login)
# dispatches the same mechanism as 'Copilot', case-insensitively matched.
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["copilot-pull-request-reviewer[bot]"]' >/dev/null 2>&1
rc_copilot_bot=$?
assert "copilot-pull-request-reviewer[bot] identity exits 0" "[ \$rc_copilot_bot -eq 0 ]"
assert "copilot-pull-request-reviewer[bot] identity dispatches the reviewer dance" "grep -qF -- '--add-reviewer @copilot' '$FAKE_GH_LOG'"

# Per-identity dispatch: chatgpt-codex-connector[bot] -> '@codex review' issue comment.
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["chatgpt-codex-connector[bot]"]' >/dev/null 2>&1
rc_codex=$?
assert "Codex identity exits 0" "[ \$rc_codex -eq 0 ]"
assert "Codex identity posts an '@codex review' issue comment" "grep -qF -- 'pr comment 1 --repo o/r --body @codex review' '$FAKE_GH_LOG'"
assert "Codex identity does NOT touch reviewers" "! grep -qF -- '--add-reviewer' '$FAKE_GH_LOG'"

# Case-insensitive identity match (spec: mirrors poll-copilot-review.sh's convention).
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["CHATGPT-CODEX-CONNECTOR[bot]"]' >/dev/null 2>&1
rc_codex_upper=$?
assert "uppercase Codex identity still dispatches (case-insensitive match)" "[ \$rc_codex_upper -eq 0 ] && grep -qF 'pr comment' '$FAKE_GH_LOG'"

# Multi-identity dispatch: both known bots asked in one call.
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 \
  --bot-reviewers '["Copilot", "chatgpt-codex-connector[bot]"]' >/dev/null 2>&1
rc_multi=$?
assert "multi-identity dispatch exits 0" "[ \$rc_multi -eq 0 ]"
assert "multi-identity dispatch asks Copilot" "grep -qF -- '--add-reviewer @copilot' '$FAKE_GH_LOG'"
assert "multi-identity dispatch asks Codex" "grep -qF 'pr comment' '$FAKE_GH_LOG'"

# Alias dedup: both Copilot aliases share one mechanism, so a call listing both
# must run the remove+re-add dance exactly ONCE — not once per alias.
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 \
  --bot-reviewers '["Copilot", "copilot-pull-request-reviewer[bot]"]' >/dev/null 2>&1
rc_alias_dedup=$?
assert "both Copilot aliases exit 0" "[ \$rc_alias_dedup -eq 0 ]"
assert "both Copilot aliases remove @copilot exactly once" "[ \$(grep -cF -- '--remove-reviewer @copilot' '$FAKE_GH_LOG') -eq 1 ]"
assert "both Copilot aliases add @copilot exactly once" "[ \$(grep -cF -- '--add-reviewer @copilot' '$FAKE_GH_LOG') -eq 1 ]"

# Unknown identity: warns to stderr and is skipped WITHOUT aborting siblings.
: > "$FAKE_GH_LOG"
err_out=$(PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 \
  --bot-reviewers '["some-other-bot[bot]", "Copilot"]' 2>&1 >/dev/null)
rc_unknown_mixed=$?
assert "unknown identity mixed with a known one still exits 0" "[ \$rc_unknown_mixed -eq 0 ]"
assert "unknown identity warns on stderr" "printf '%s' \"\$err_out\" | grep -qiF 'some-other-bot[bot]'"
assert "unknown identity does not abort dispatch to Copilot" "grep -qF -- '--add-reviewer @copilot' '$FAKE_GH_LOG'"

# All-unknown: exit 1 (no ask succeeded), still no abort/crash.
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["totally-unknown-bot"]' >/dev/null 2>&1
rc_all_unknown=$?
assert "all-unknown identities exit 1 (none succeeded)" "[ \$rc_all_unknown -eq 1 ]"

# Exit-code matrix: a known identity whose gh call fails still counts as a
# failed ask; when it is the ONLY identity, exit 1 (none succeeded).
: > "$FAKE_GH_LOG"
FAKE_GH_FAIL_EDIT=1 PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["Copilot"]' >/dev/null 2>&1
rc_all_fail=$?
assert "single failing identity exits 1 (none succeeded)" "[ \$rc_all_fail -eq 1 ]"

# Exit-code matrix: one identity fails, the other succeeds -> still exit 0
# (at least one ask succeeded).
: > "$FAKE_GH_LOG"
FAKE_GH_FAIL_EDIT=1 PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 \
  --bot-reviewers '["Copilot", "chatgpt-codex-connector[bot]"]' >/dev/null 2>&1
rc_partial=$?
assert "one failing + one succeeding identity exits 0 (at least one succeeded)" "[ \$rc_partial -eq 0 ]"

# Flag-omitted default: still performs the Copilot-only dance, unchanged.
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 >/dev/null 2>&1
rc_default=$?
assert "omitting --bot-reviewers exits 0 (Copilot default)" "[ \$rc_default -eq 0 ]"
assert "omitting --bot-reviewers still dispatches the Copilot dance" "grep -qF -- '--add-reviewer @copilot' '$FAKE_GH_LOG'"
assert "omitting --bot-reviewers never posts a codex review comment" "! grep -qF 'pr comment' '$FAKE_GH_LOG'"

# ── --disposition-table / --since-sha (do-not-relitigate context) ───────────

assert "accepts --disposition-table flag" "grep -q -- '--disposition-table' '$SCRIPT'"
assert "accepts --since-sha flag" "grep -q -- '--since-sha' '$SCRIPT'"

# Malformed --disposition-table must be rejected up front (exit 2), same
# convention as --bot-reviewers.
"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["chatgpt-codex-connector[bot]"]' --disposition-table 'not-json' 2>/dev/null
rc_bad_table=$?
assert "exits 2 for non-array --disposition-table" "[ \$rc_bad_table -eq 2 ]"

"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["chatgpt-codex-connector[bot]"]' --disposition-table '[]' 2>/dev/null
rc_empty_table=$?
assert "exits 2 for empty --disposition-table array" "[ \$rc_empty_table -eq 2 ]"

"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["chatgpt-codex-connector[bot]"]' --disposition-table '["not-an-object"]' 2>/dev/null
rc_nonobj_table=$?
assert "exits 2 for --disposition-table array with a non-object member" "[ \$rc_nonobj_table -eq 2 ]"

"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  --disposition-table '[{"finding":"x","classification":"WRONG","detail":"y"}]' 2>/dev/null
rc_badclass_table=$?
assert "exits 2 for --disposition-table entry with bad classification" "[ \$rc_badclass_table -eq 2 ]"

"$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  --disposition-table '[{"classification":"FIX","detail":"abc123"}]' 2>/dev/null
rc_missingfield_table=$?
assert "exits 2 for --disposition-table entry missing a required field" "[ \$rc_missingfield_table -eq 2 ]"

err_out=$("$SCRIPT" --owner o --repo r --pr 1 --bot-reviewers '["chatgpt-codex-connector[bot]"]' --disposition-table 'not-json' 2>&1 >/dev/null)
assert "malformed --disposition-table gives a clear stderr message" "printf '%s' \"\$err_out\" | grep -qiF 'disposition-table'"

# (a) both flags supplied: the posted Codex comment carries the structured
# table and the since-sha line, not the bare '@codex review' string.
: > "$FAKE_GH_LOG"
export FAKE_GH_STDIN_LOG="$TMP/fake-gh-stdin.log"
DISPOSITION='[{"finding":"missing null check","classification":"FIX","detail":"abc1234"},{"finding":"style nit","classification":"SKIP","detail":"cosmetic, out of scope"},{"finding":"race condition claim","classification":"REBUT","detail":"lock is held across the whole critical section, see line 42"}]'
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' \
  --disposition-table "$DISPOSITION" \
  --since-sha deadbeef >/dev/null 2>&1
rc_table=$?
assert "disposition-table dispatch exits 0" "[ \$rc_table -eq 0 ]"
assert "codex comment body contains the FIX finding" "grep -qF -- 'missing null check' '$FAKE_GH_LOG'"
assert "codex comment body contains the SKIP rationale" "grep -qF -- 'cosmetic, out of scope' '$FAKE_GH_LOG'"
assert "codex comment body contains the REBUT rationale" "grep -qF -- 'lock is held across the whole critical section' '$FAKE_GH_LOG'"
assert "codex comment body contains the since-sha line" "grep -qiF -- 'since deadbeef' '$FAKE_GH_LOG'"
assert "codex comment body is NOT the bare '@codex review' string" "[ \$(wc -l < '$FAKE_GH_LOG') -gt 1 ]"

# (c) neither flag supplied: comment body is still the bare string (regression guard).
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 \
  --bot-reviewers '["chatgpt-codex-connector[bot]"]' >/dev/null 2>&1
rc_bare=$?
assert "no disposition-table/since-sha exits 0" "[ \$rc_bare -eq 0 ]"
assert "no disposition-table/since-sha posts the bare '@codex review' string" "grep -qF -- 'pr comment 1 --repo o/r --body @codex review' '$FAKE_GH_LOG'"

# (d) the flags have no effect on the Copilot mechanism: both bots dispatched,
# disposition-table supplied -> Copilot still gets the plain remove+re-add dance.
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN2:$PATH" "$SCRIPT" --owner o --repo r --pr 1 \
  --bot-reviewers '["Copilot", "chatgpt-codex-connector[bot]"]' \
  --disposition-table "$DISPOSITION" \
  --since-sha deadbeef >/dev/null 2>&1
rc_both=$?
assert "disposition-table with both bots exits 0" "[ \$rc_both -eq 0 ]"
assert "Copilot mechanism unaffected by --disposition-table" "grep -qF -- '--add-reviewer @copilot' '$FAKE_GH_LOG'"
assert "Codex mechanism still carries the disposition table when both bots dispatched" "grep -qF -- 'missing null check' '$FAKE_GH_LOG'"

exit $FAIL

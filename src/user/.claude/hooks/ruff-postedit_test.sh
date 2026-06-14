#!/usr/bin/env bash
# Hermetic tests for ruff-postedit.py. A fake `ruff` shim on PATH makes
# exit-code/gating behavior deterministic without depending on real ruff
# (ruff's own fix/format behavior is ruff's to test, not ours).
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="$SCRIPT_DIR/ruff-postedit.py"
PASS=0; FAIL=0

assert_rc()       { if [ "$2" -eq "$3" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: $1 (expected rc=$2, got $3)"; fi; }
assert_contains() { case "$3" in *"$2"*) PASS=$((PASS+1));; *) FAIL=$((FAIL+1)); echo "FAIL: $1 (stderr missing '$2')";; esac; }
# assert a line in $RUFF_ARGV_LOG that contains BOTH needles (a marker + a flag)
assert_argv_line() { # $1=desc $2=marker $3=needle
  if grep -- "$2" "$RUFF_ARGV_LOG" 2>/dev/null | grep -q -- "$3"; then PASS=$((PASS+1));
  else FAIL=$((FAIL+1)); echo "FAIL: $1 (no ruff invocation matching '$2' carried '$3')"; fi; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# fake ruff shim. Records every invocation's argv to $RUFF_ARGV_LOG so tests can
# assert the hook's *contract with ruff* (which flags it passes) without depending
# on real ruff's fix/format behavior — that's ruff's to test, not ours. The final
# `check` (the one WITHOUT --fix) decides the gating outcome.
BIN="$WORK/bin"; mkdir -p "$BIN"
export RUFF_ARGV_LOG="$WORK/ruff_argv.log"
cat > "$BIN/ruff" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$RUFF_ARGV_LOG"
# Identify the final blocking check: `check` present, `--fix` absent.
is_check=0; has_fix=0
for a in "$@"; do
  [ "$a" = "check" ] && is_check=1
  [ "$a" = "--fix" ] && has_fix=1
done
if [ "$is_check" = "1" ] && [ "$has_fix" = "0" ]; then
  if [ "${FAKE_RUFF_RESIDUAL:-0}" = "1" ]; then
    echo "bad.py:1:1: F821 Undefined name \`x\`"
    exit 1
  fi
fi
exit 0
SH
chmod +x "$BIN/ruff"
PATH="$BIN:$PATH"; export PATH

# ruff-configured project fixture (no uv.lock -> hook uses PATH ruff = our shim)
PROJ="$WORK/proj"; mkdir -p "$PROJ"
printf '[tool.ruff]\nline-length = 100\n' > "$PROJ/pyproject.toml"
echo "x = 1" > "$PROJ/clean.py"

run_hook() { local _tmp; _tmp=$(mktemp); printf '%s' "$1" | python3 "$HOOK" >"$_tmp" 2>&1; RC=${PIPESTATUS[1]}; ERR=$(<"$_tmp"); rm -f "$_tmp"; }

# 1. non-.py -> silent 0
run_hook "{\"tool_input\":{\"file_path\":\"$PROJ/clean.txt\"}}"
assert_rc "non-python file is ignored" 0 "$RC"

# 2. .py with no ruff config in tree -> silent 0
echo "x=1" > "$WORK/loose.py"
run_hook "{\"tool_input\":{\"file_path\":\"$WORK/loose.py\"}}"
assert_rc "no ruff config -> skip" 0 "$RC"

# 3. clean .py in configured project -> silent 0
run_hook "{\"tool_input\":{\"file_path\":\"$PROJ/clean.py\"}}"
assert_rc "clean file -> exit 0" 0 "$RC"

# 4. residual unfixable -> exit 2 + helpful stderr
export FAKE_RUFF_RESIDUAL=1
run_hook "{\"tool_input\":{\"file_path\":\"$PROJ/clean.py\"}}"
assert_rc       "residual -> exit 2" 2 "$RC"
assert_contains "residual names rule" "F821" "$ERR"
assert_contains "residual has nudge"  "manual attention" "$ERR"
unset FAKE_RUFF_RESIDUAL

# 5. malformed JSON -> silent 0
run_hook "not json at all"
assert_rc "malformed JSON -> exit 0" 0 "$RC"

# 6. missing file_path -> silent 0
run_hook "{}"
assert_rc "missing file_path -> exit 0" 0 "$RC"

# 6b. tool_input present but not a dict (string) -> silent 0, no traceback
run_hook "{\"tool_input\":\"oops\"}"
assert_rc "non-dict tool_input -> exit 0" 0 "$RC"
case "$ERR" in *Traceback*) FAIL=$((FAIL+1)); echo "FAIL: non-dict tool_input emitted a traceback";; *) PASS=$((PASS+1));; esac

# 7. ruff absent (PATH has only python3) -> silent 0
PYBIN="$WORK/pybin"; mkdir -p "$PYBIN"; ln -s "$(command -v python3)" "$PYBIN/python3"
ERR="$(printf '%s' "{\"tool_input\":{\"file_path\":\"$PROJ/clean.py\"}}" | PATH="$PYBIN" python3 "$HOOK" 2>&1 >/dev/null)"; RC=$?
assert_rc "ruff absent -> exit 0" 0 "$RC"

# 8. REGRESSION: transient codes (F401 unused import, F841 unused variable) must
#    not be auto-deleted or block per-edit, so multi-edit authoring doesn't churn
#    F821 (add import in one edit; use it in a later edit). Pin the hook's
#    contract with ruff:
#    - the --fix step marks F401,F841 --unfixable (never auto-deleted between edits)
#    - the final blocking check --ignore's F401,F841 (a just-added, not-yet-used
#      import/var doesn't return exit 2)
: > "$RUFF_ARGV_LOG"
run_hook "{\"tool_input\":{\"file_path\":\"$PROJ/clean.py\"}}"
assert_rc         "transient codes -> exit 0 (non-blocking)" 0 "$RC"
assert_argv_line  "fix step keeps transient codes unfixable" "--fix" "--unfixable F401,F841"
assert_argv_line  "final check ignores transient codes"      "check --ignore" "--ignore F401,F841"

# 9. The --ignore on the final check must NOT swallow a REAL violation: when ruff
#    reports a non-transient residual (F821), the hook still blocks with exit 2.
#    (Re-uses the residual shim path, which fires only on the final no-fix check.)
: > "$RUFF_ARGV_LOG"
export FAKE_RUFF_RESIDUAL=1
run_hook "{\"tool_input\":{\"file_path\":\"$PROJ/clean.py\"}}"
assert_rc        "real error still blocks despite --ignore" 2 "$RC"
assert_contains  "real error names F821"                    "F821" "$ERR"
unset FAKE_RUFF_RESIDUAL

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]

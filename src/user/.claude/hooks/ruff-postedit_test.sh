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

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# fake ruff shim: only the final `check --force-exclude` decides the outcome
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/ruff" <<'SH'
#!/bin/sh
if [ "$1" = "check" ] && [ "$2" = "--force-exclude" ]; then
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

# 7. ruff absent (PATH has only python3) -> silent 0
PYBIN="$WORK/pybin"; mkdir -p "$PYBIN"; ln -s "$(command -v python3)" "$PYBIN/python3"
ERR="$(printf '%s' "{\"tool_input\":{\"file_path\":\"$PROJ/clean.py\"}}" | PATH="$PYBIN" python3 "$HOOK" 2>&1 >/dev/null)"; RC=$?
assert_rc "ruff absent -> exit 0" 0 "$RC"

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]

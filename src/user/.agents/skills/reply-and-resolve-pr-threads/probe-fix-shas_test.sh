#!/usr/bin/env bash
# Smoke test for probe-fix-shas.sh
# Helper does not exist yet — these tests MUST fail in red phase.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/probe-fix-shas.sh"
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

echo "[probe-fix-shas_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --branch flag" "grep -q -- '--branch' '$SCRIPT'"
assert "accepts --items flag" "grep -q -- '--items' '$SCRIPT'"

# Items fixture: one nonexistent SHA so the script's existence-check has
# something to classify as "missing". Real probe uses git locally; no network.
ITEMS="$TMP/items.json"
echo '[{"comment_id":"c1","fix_commit_sha":"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"}]' >"$ITEMS"

# Happy path: with the fixture, expect JSON output containing
# present/missing buckets. The SHA is bogus so it should be reported as
# missing, but the structure must still be well-formed.
"$SCRIPT" --branch main --items "$ITEMS" > "$TMP/out.json" 2>&1
rc_happy=$?
assert "exits 0 on happy path" "[ \$rc_happy -eq 0 ]"
assert "output has present key" "jq -e 'has(\"present\")' '$TMP/out.json' >/dev/null 2>&1"
assert "output has missing key" "jq -e 'has(\"missing\")' '$TMP/out.json' >/dev/null 2>&1"

# Failure path: missing flags
if "$SCRIPT" 2>/dev/null; then
  echo "  FAIL: accepted invocation with no flags"
  FAIL=1
else
  echo "  ok: rejects missing required flags"
fi

# Failure path: unknown flag (--bogus FIRST so it's seen before any I/O)
if "$SCRIPT" --bogus --branch main --items "$ITEMS" 2>/dev/null; then
  echo "  FAIL: accepted unknown flag"
  FAIL=1
else
  echo "  ok: rejects unknown flag"
fi

exit $FAIL

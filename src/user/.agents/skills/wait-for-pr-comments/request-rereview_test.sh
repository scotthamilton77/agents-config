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

exit $FAIL

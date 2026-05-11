#!/usr/bin/env bash
# Smoke test for verify-head-sha.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/verify-head-sha.sh"
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

echo "[verify-head-sha_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"
assert "accepts --expected-sha flag" "grep -q -- '--expected-sha' '$SCRIPT'"

# --- Fake-gh shim: returns canned headRefOid ---
EXPECTED="expected-sha-abc123"
FAKEBIN="$TMP/bin"
mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/gh" <<FAKE
#!/usr/bin/env bash
# Fake gh — returns canned PR head ref oid.
echo '{"headRefOid":"$EXPECTED"}'
FAKE
chmod +x "$FAKEBIN/gh"

# Happy path: matching --expected-sha with fake gh response → exit 0.
PATH="$FAKEBIN:$PATH" "$SCRIPT" --owner o --repo r --pr 1 --expected-sha "$EXPECTED" > "$TMP/out.txt" 2>&1
rc_happy=$?
assert "exits 0 when expected-sha matches fake-gh response" "[ \$rc_happy -eq 0 ]"

# Failure path: missing required flag must fail
if "$SCRIPT" 2>/dev/null; then
  echo "  FAIL: accepted invocation with no flags"
  FAIL=1
else
  echo "  ok: rejects missing required flags"
fi

# Failure path: unknown flag (--bogus FIRST so it's seen before any I/O)
if "$SCRIPT" --bogus --owner o --repo r --pr 1 --expected-sha abc 2>/dev/null; then
  echo "  FAIL: accepted unknown flag"
  FAIL=1
else
  echo "  ok: rejects unknown flag"
fi

exit $FAIL

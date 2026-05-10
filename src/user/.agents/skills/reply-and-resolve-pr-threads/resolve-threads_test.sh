#!/usr/bin/env bash
# Smoke test for resolve-threads.sh
# Helper does not exist yet — these tests MUST fail in red phase.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/resolve-threads.sh"
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

echo "[resolve-threads_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --inventory flag" "grep -q -- '--inventory' '$SCRIPT'"

# Inventory fixture: one FIX item with a thread_id ready to resolve.
INV="$TMP/inv.json"
cat >"$INV" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 42, "owner": "o", "repo": "r"},
  "items": [
    {
      "comment_id": "c1",
      "classification": "FIX",
      "fix_outcome": "committed",
      "thread_id": "THREAD_ABC123"
    }
  ]
}
JSON

# --- Fake-gh shim: handles resolveReviewThread mutation ---
FAKEBIN="$TMP/bin"
mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/gh" <<'FAKE'
#!/usr/bin/env bash
# Fake gh — accepts the GraphQL mutation, returns success.
echo '{"data":{"resolveReviewThread":{"thread":{"isResolved":true}}}}'
FAKE
chmod +x "$FAKEBIN/gh"

# Happy path: with fake gh, expect "RESOLVED THREAD_ABC123" in output.
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV" > "$TMP/out.txt" 2>&1
rc_happy=$?
assert "exits 0 on happy path with fake gh" "[ \$rc_happy -eq 0 ]"
if grep -q 'RESOLVED THREAD_ABC123' "$TMP/out.txt"; then
  echo "  ok: emits RESOLVED <thread_id> line"
else
  echo "  FAIL: missing RESOLVED <thread_id> output; got: $(cat "$TMP/out.txt")"
  FAIL=1
fi

# Failure path: missing required flag
if "$SCRIPT" 2>/dev/null; then
  echo "  FAIL: accepted invocation with no flags"
  FAIL=1
else
  echo "  ok: rejects missing required flags"
fi

# Failure path: nonexistent inventory file
if "$SCRIPT" --inventory /nonexistent/path.json 2>/dev/null; then
  echo "  FAIL: accepted nonexistent inventory file"
  FAIL=1
else
  echo "  ok: rejects nonexistent inventory file"
fi

# Failure path: unknown flag (--bogus FIRST so it's seen before any I/O)
if "$SCRIPT" --bogus --inventory "$INV" 2>/dev/null; then
  echo "  FAIL: accepted unknown flag"
  FAIL=1
else
  echo "  ok: rejects unknown flag"
fi

exit $FAIL

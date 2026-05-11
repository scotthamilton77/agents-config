#!/usr/bin/env bash
# Smoke test for fetch-and-normalize-comments.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/fetch-and-normalize-comments.sh"
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

echo "[fetch-and-normalize-comments_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"

# --- Fake-gh shim for happy path ---
FAKEBIN="$TMP/bin"
mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/gh" <<'FAKE'
#!/usr/bin/env bash
# Fake gh — returns well-formed empty responses for both the GraphQL
# review-threads query and the REST issue-comments endpoint.
# The GraphQL path requires an object shape (data.repository.pullRequest...);
# the REST issues path returns a JSON array.
for arg in "$@"; do
  if [ "$arg" = "graphql" ]; then
    echo '{"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[]}}}}}'
    exit 0
  fi
done
echo '[]'
FAKE
chmod +x "$FAKEBIN/gh"

# Happy path: with fake gh, expect a JSON array on stdout.
PATH="$FAKEBIN:$PATH" "$SCRIPT" --owner o --repo r --pr 1 > "$TMP/out.json" 2>&1
rc_happy=$?
assert "exits 0 on happy path with fake gh" "[ \$rc_happy -eq 0 ]"
assert "output is a JSON array" "jq -e 'type == \"array\"' '$TMP/out.json' >/dev/null 2>&1"

# Failure path: missing required flag must fail
if "$SCRIPT" 2>/dev/null; then
  echo "  FAIL: accepted invocation with no flags"
  FAIL=1
else
  echo "  ok: rejects missing required flags"
fi

# Failure path: unknown flag (--bogus FIRST so flag-parser sees it before I/O)
if "$SCRIPT" --bogus --owner o --repo r --pr 1 2>/dev/null; then
  echo "  FAIL: accepted unknown flag --bogus"
  FAIL=1
else
  echo "  ok: rejects unknown flag"
fi

exit $FAIL

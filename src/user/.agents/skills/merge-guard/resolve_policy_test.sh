#!/usr/bin/env bash
# Smoke wrapper: runs the Python unittest suite for resolve_policy.py.
# The [gates].test glob only discovers *_test.sh, hence this shim.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[resolve_policy_test]"

skip() {
    echo "" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "SKIPPED: resolve_policy suite NOT RUN (python3 >=3.11 unavailable)" >&2
    echo "reason: $1" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "" >&2
    exit 0
}

if ! command -v python3 >/dev/null 2>&1; then
    skip "python3 not found on PATH"
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    skip "python3 < 3.11 (tomllib unavailable)"
fi

python3 "$HERE/resolve_policy_test.py" -v

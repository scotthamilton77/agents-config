#!/usr/bin/env bash
# Smoke wrapper: runs the Python unittest suite for approve_pr.py.
# The [gates].test glob only discovers *_test.sh, hence this shim.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[approve_pr_test]"

skip() {
    echo "" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "SKIPPED: approve_pr suite NOT RUN (python3 >=3.11 unavailable)" >&2
    echo "reason: $1" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "" >&2
    exit 0
}

if ! command -v python3 >/dev/null 2>&1; then
    skip "python3 not found on PATH"
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    skip "python3 < 3.11"
fi

cd "$HERE" && python3 approve_pr_test.py -v

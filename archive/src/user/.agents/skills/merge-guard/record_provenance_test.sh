#!/usr/bin/env bash
# Smoke wrapper: runs the Python unittest suite for record_provenance.py.
# The [gates].test glob only discovers *_test.sh, hence this shim.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
echo "[record_provenance_test]"
skip() {
    echo "SKIPPED: record_provenance suite NOT RUN — $1" >&2
    exit 0
}
command -v python3 >/dev/null 2>&1 || skip "python3 not found on PATH"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || skip "python3 < 3.11"
python3 "$HERE/record_provenance_test.py" -v

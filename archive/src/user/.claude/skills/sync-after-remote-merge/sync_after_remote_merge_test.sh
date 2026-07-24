#!/usr/bin/env bash
# Smoke-runs the sync-after-remote-merge pytest suite via uv (stdlib-only + pytest).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --with pytest python -m pytest "$HERE/sync_after_remote_merge_test.py" -v

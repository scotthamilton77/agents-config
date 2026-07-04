#!/usr/bin/env bash
# Smoke-runs the gate-triage pytest suite via uv (PEP 723 deps + pytest).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --with pytest --with "pathspec>=0.12" python -m pytest "$HERE/gate_triage_test.py" -v

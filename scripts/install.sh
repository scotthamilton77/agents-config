#!/usr/bin/env bash
# Install agent configurations for AI coding assistants.
# Delegates to the Python installer package via uv.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run --project "$REPO_ROOT/packages/installer" python -m installer "$@"

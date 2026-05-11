#!/usr/bin/env bash
# setup-worker-audit.sh — Idempotently create .beads/worker-audit/ and its .gitignore.
#
# Usage: setup-worker-audit.sh <repo-root>
#
# Creates <repo-root>/.beads/worker-audit/ if absent, then writes a .gitignore
# that ignores all contents so worker-audit YAML reports never appear in git
# status. Safe to call on every implement-bead invocation.
#
# <repo-root> must be the MAIN repo root — not a worktree path. Derive it with:
#   dirname "$(git -C "<worktree-path>" rev-parse --path-format=absolute --git-common-dir)"
# --git-common-dir returns the shared .git/ regardless of which worktree is active,
# so dirname always resolves to the main repo root where .beads/ lives.

set -euo pipefail

REPO_ROOT="${1:?Usage: setup-worker-audit.sh <repo-root>}"
AUDIT_DIR="$REPO_ROOT/.beads/worker-audit"
GITIGNORE="$AUDIT_DIR/.gitignore"

mkdir -p "$AUDIT_DIR"

if [[ ! -f "$GITIGNORE" ]]; then
    printf '*\n' > "$GITIGNORE"
fi

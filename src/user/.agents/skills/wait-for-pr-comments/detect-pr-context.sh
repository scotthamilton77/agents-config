#!/usr/bin/env bash
# Purpose: detect PR context (number, owner, repo, paths) from CLI flag or current branch.
#
# Inputs:
#   --pr <n-or-url>   optional — PR number or URL; absent = auto-detect from current branch
#
# Outputs:
#   stdout: JSON {pr_number, owner, repo, inventory_path, concurrency_state}
#   exit codes:
#     0 = success
#     1 = could not detect PR / gh failure
#     2 = bad flag usage
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") [--pr <n-or-url>]

Detects PR context for the current worktree.
Emits JSON to stdout: {pr_number, owner, repo, inventory_path, concurrency_state}
EOF
  exit 2
}

PR_INPUT=""

if [ $# -eq 0 ]; then
  : # auto-detect path; allowed
fi

while [ $# -gt 0 ]; do
  case "$1" in
    --pr)
      [ $# -ge 2 ] || usage
      PR_INPUT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "error: unknown flag: $1" >&2
      usage
      ;;
  esac
done

# Resolve PR number/owner/repo using gh. Use mktemp + trap to avoid the
# predictable-path symlink / race issues of /tmp/.pr-ctx.$$.
TMP_CTX="$(mktemp)"
trap 'rm -f "$TMP_CTX"' EXIT

if [ -n "$PR_INPUT" ]; then
  if ! gh pr view "$PR_INPUT" --json number,headRepository,headRepositoryOwner > "$TMP_CTX" 2>/dev/null; then
    echo "error: gh pr view failed for '$PR_INPUT'" >&2
    exit 1
  fi
else
  if ! gh pr view --json number,headRepository,headRepositoryOwner > "$TMP_CTX" 2>/dev/null; then
    echo "error: gh pr view failed (no PR detected for current branch)" >&2
    exit 1
  fi
fi

PR_NUMBER="$(jq -r '.number // empty' "$TMP_CTX")"
OWNER="$(jq -r '.headRepositoryOwner.login // empty' "$TMP_CTX")"
REPO="$(jq -r '.headRepository.name // empty' "$TMP_CTX")"

if [ -z "$PR_NUMBER" ] || [ -z "$OWNER" ] || [ -z "$REPO" ]; then
  echo "error: could not resolve pr_number/owner/repo" >&2
  exit 1
fi

INVENTORY_DIR="$HOME/.claude/state/pr-inventory"
mkdir -p "$INVENTORY_DIR" 2>/dev/null || true
# Get head SHA (short) from PR; falls back to "unknown" if gh fails. The path
# is a detection hint for concurrency probing, not a write target.
HEAD_SHA="$(gh api "repos/$OWNER/$REPO/pulls/$PR_NUMBER" --jq '.head.sha' 2>/dev/null | head -c 12)"
[ -n "$HEAD_SHA" ] || HEAD_SHA="unknown"
INVENTORY_PATH="$INVENTORY_DIR/${OWNER}-${REPO}-${PR_NUMBER}-${HEAD_SHA}.json"
CONCURRENCY_STATE="$INVENTORY_DIR/${OWNER}-${REPO}-${PR_NUMBER}-${HEAD_SHA}.state.json"

jq -nc \
  --argjson pr "$PR_NUMBER" \
  --arg owner "$OWNER" \
  --arg repo "$REPO" \
  --arg inv "$INVENTORY_PATH" \
  --arg cc "$CONCURRENCY_STATE" \
  '{pr_number: $pr, owner: $owner, repo: $repo, inventory_path: $inv, concurrency_state: $cc}'

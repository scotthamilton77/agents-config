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

# Resolve PR number/owner/repo using gh
if [ -n "$PR_INPUT" ]; then
  if ! gh pr view "$PR_INPUT" --json number,headRepository,headRepositoryOwner > /tmp/.pr-ctx.$$ 2>/dev/null; then
    echo "error: gh pr view failed for '$PR_INPUT'" >&2
    rm -f /tmp/.pr-ctx.$$
    exit 1
  fi
else
  if ! gh pr view --json number,headRepository,headRepositoryOwner > /tmp/.pr-ctx.$$ 2>/dev/null; then
    echo "error: gh pr view failed (no PR detected for current branch)" >&2
    rm -f /tmp/.pr-ctx.$$
    exit 1
  fi
fi

PR_NUMBER="$(jq -r '.number // empty' /tmp/.pr-ctx.$$)"
OWNER="$(jq -r '.headRepositoryOwner.login // empty' /tmp/.pr-ctx.$$)"
REPO="$(jq -r '.headRepository.name // empty' /tmp/.pr-ctx.$$)"
rm -f /tmp/.pr-ctx.$$

if [ -z "$PR_NUMBER" ] || [ -z "$OWNER" ] || [ -z "$REPO" ]; then
  echo "error: could not resolve pr_number/owner/repo" >&2
  exit 1
fi

INVENTORY_PATH="/tmp/pr-${PR_NUMBER}-inventory.json"
CONCURRENCY_STATE="/tmp/pr-${PR_NUMBER}-state.json"

jq -nc \
  --argjson pr "$PR_NUMBER" \
  --arg owner "$OWNER" \
  --arg repo "$REPO" \
  --arg inv "$INVENTORY_PATH" \
  --arg cc "$CONCURRENCY_STATE" \
  '{pr_number: $pr, owner: $owner, repo: $repo, inventory_path: $inv, concurrency_state: $cc}'

#!/usr/bin/env bash
# Purpose: request a Copilot re-review via the remove+re-add reviewer
# idempotency dance. The `gh pr edit --remove-reviewer @copilot && sleep && gh
# pr edit --add-reviewer @copilot` pattern reliably triggers a new review
# event even when @copilot is already listed.
#
# Inputs:
#   --owner <o>  repository owner
#   --repo  <r>  repository name
#   --pr    <n>  PR number
#
# Outputs:
#   stdout: (none on success)
#   exit codes:
#     0 = re-review requested
#     1 = gh failure
#     2 = bad flag usage
#
# GraphQL projection: none directly; uses `gh pr edit` REST under the hood.
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --owner <o> --repo <r> --pr <n>

Removes and re-adds @copilot as a reviewer to trigger a Copilot re-review.
EOF
  exit 2
}

OWNER=""
REPO=""
PR=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --owner) OWNER="${2:-}"; shift 2 ;;
    --repo)  REPO="${2:-}";  shift 2 ;;
    --pr)    PR="${2:-}";    shift 2 ;;
    -h|--help) usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$OWNER" ] && [ -n "$REPO" ] && [ -n "$PR" ] || {
  echo "error: --owner, --repo, --pr are all required" >&2
  exit 2
}

PR_REF="$OWNER/$REPO#$PR"

# Remove @copilot — tolerate "not currently a reviewer" by capturing stderr.
gh pr edit "$PR" --repo "$OWNER/$REPO" --remove-reviewer @copilot >/dev/null 2>&1 || true

sleep 2

if ! gh pr edit "$PR" --repo "$OWNER/$REPO" --add-reviewer @copilot >/dev/null 2>&1; then
  echo "error: gh pr edit --add-reviewer failed for $PR_REF" >&2
  exit 1
fi

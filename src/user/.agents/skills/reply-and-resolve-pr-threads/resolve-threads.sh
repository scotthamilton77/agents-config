#!/usr/bin/env bash
# Purpose: resolve each FIX review-thread in the inventory via GraphQL
# `resolveReviewThread` mutation.
#
# Only acts on items with:
#   kind == "review_thread" (or absent + thread_id present)
#   classification == "FIX"
#   thread_id non-empty
#
# Inputs:
#   --inventory <file>  inventory JSON (must contain .items array)
#
# Outputs:
#   stdout: per thread, one of:
#     RESOLVED <thread_id>
#     FAILED <thread_id> <reason>
#   exit codes:
#     0 = all targets resolved (or none to resolve)
#     1 = at least one resolve failed
#     2 = bad flag usage / missing input
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --inventory <file>

Resolves every FIX review-thread in the inventory via GraphQL.
EOF
  exit 2
}

INV=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --inventory) INV="${2:-}"; shift 2 ;;
    -h|--help)   usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$INV" ] || { echo "error: --inventory is required" >&2; exit 2; }
[ -f "$INV" ] || { echo "error: inventory file not found: $INV" >&2; exit 2; }

any_failed=0

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

jq -c '
  .items[]?
  | select((.classification // "") == "FIX")
  | select(((.kind // "review_thread") == "review_thread"))
  | select((.thread_id // "") != "")
' "$INV" > "$TMP"

while IFS= read -r item; do
  [ -n "$item" ] || continue
  tid="$(echo "$item" | jq -r '.thread_id')"

  if gh api graphql \
    -f query='mutation($tid:ID!){resolveReviewThread(input:{threadId:$tid}){thread{isResolved}}}' \
    -f tid="$tid" >/dev/null 2>&1; then
    echo "RESOLVED $tid"
  else
    echo "FAILED $tid gh-graphql-resolve-failed"
    any_failed=1
  fi
done < "$TMP"

[ "$any_failed" -eq 0 ] || exit 1
exit 0

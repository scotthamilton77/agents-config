#!/usr/bin/env bash
# Purpose: count unresolved (and non-outdated) review threads on a PR.
#
# Inputs:
#   --owner <o>  repository owner
#   --repo  <r>  repository name
#   --pr    <n>  PR number
#
# Outputs:
#   stdout: JSON {count: <n>, thread_ids: [<id>, ...]}
#   exit codes:
#     0 = success
#     1 = gh / network failure
#     2 = bad flag usage
#
# GraphQL projection:
#   pullRequest.reviewThreads(first:100, after:$cursor) {
#     nodes { id, isResolved, isOutdated }
#     pageInfo { hasNextPage, endCursor }
#   }
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --owner <o> --repo <r> --pr <n>

Counts non-resolved, non-outdated review threads. Emits JSON {count, thread_ids}.
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

QUERY='query($owner:String!,$repo:String!,$pr:Int!,$cursor:String){repository(owner:$owner,name:$repo){pullRequest(number:$pr){reviewThreads(first:100,after:$cursor){nodes{id isResolved isOutdated} pageInfo{hasNextPage endCursor}}}}}'

cursor=""
all_threads="[]"

while :; do
  if [ -n "$cursor" ]; then
    PAGE="$(gh api graphql -F "owner=$OWNER" -F "repo=$REPO" -F "pr=$PR" -F "cursor=$cursor" -f query="$QUERY" 2>/dev/null || echo '')"
  else
    PAGE="$(gh api graphql -F "owner=$OWNER" -F "repo=$REPO" -F "pr=$PR" -f query="$QUERY" 2>/dev/null || echo '')"
  fi

  if [ -z "$PAGE" ]; then
    echo "error: gh api graphql failed" >&2
    exit 1
  fi

  NODES="$(echo "$PAGE" | jq -c '.data.repository.pullRequest.reviewThreads.nodes // []' 2>/dev/null || echo '[]')"
  all_threads="$(jq -nc --argjson a "$all_threads" --argjson b "$NODES" '$a + $b')"

  HAS_NEXT="$(echo "$PAGE" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage // false' 2>/dev/null || echo false)"
  if [ "$HAS_NEXT" != "true" ]; then
    break
  fi
  cursor="$(echo "$PAGE" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor // empty')"
  [ -n "$cursor" ] || break
done

echo "$all_threads" | jq -c '
  map(select(.isResolved == false and .isOutdated == false))
  | {count: length, thread_ids: map(.id)}
'

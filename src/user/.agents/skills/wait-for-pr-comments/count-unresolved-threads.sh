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

GH_ERR="$(mktemp)"
trap 'rm -f "$GH_ERR"' EXIT

while :; do
  if [ -n "$cursor" ]; then
    if ! PAGE="$(gh api graphql -F "owner=$OWNER" -F "repo=$REPO" -F "pr=$PR" -F "cursor=$cursor" -f query="$QUERY" 2>"$GH_ERR")"; then
      echo "error: gh api graphql failed: $(cat "$GH_ERR")" >&2
      exit 1
    fi
  else
    if ! PAGE="$(gh api graphql -F "owner=$OWNER" -F "repo=$REPO" -F "pr=$PR" -f query="$QUERY" 2>"$GH_ERR")"; then
      echo "error: gh api graphql failed: $(cat "$GH_ERR")" >&2
      exit 1
    fi
  fi

  if ! NODES="$(printf '%s' "$PAGE" | jq -c '.data.repository.pullRequest.reviewThreads.nodes // []' 2>"$GH_ERR")"; then
    echo "error: jq failed to parse reviewThreads.nodes: $(cat "$GH_ERR")" >&2
    exit 1
  fi
  if ! all_threads="$(jq -nc --argjson a "$all_threads" --argjson b "$NODES" '$a + $b' 2>"$GH_ERR")"; then
    echo "error: jq failed to merge thread pages: $(cat "$GH_ERR")" >&2
    exit 1
  fi

  if ! HAS_NEXT="$(printf '%s' "$PAGE" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage // false' 2>"$GH_ERR")"; then
    echo "error: jq failed to read pageInfo.hasNextPage: $(cat "$GH_ERR")" >&2
    exit 1
  fi
  if [ "$HAS_NEXT" != "true" ]; then
    break
  fi
  if ! cursor="$(printf '%s' "$PAGE" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor // empty' 2>"$GH_ERR")"; then
    echo "error: jq failed to read pageInfo.endCursor: $(cat "$GH_ERR")" >&2
    exit 1
  fi
  [ -n "$cursor" ] || break
done

printf '%s' "$all_threads" | jq -c '
  map(select(.isResolved == false and .isOutdated == false))
  | {count: length, thread_ids: map(.id)}
'

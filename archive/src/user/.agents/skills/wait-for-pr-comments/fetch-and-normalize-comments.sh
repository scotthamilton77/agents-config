#!/usr/bin/env bash
# Purpose: fetch the first page of PR review-thread comments and issue comments, normalize into a single JSON array.
#
# v1 scope: single-page only — reviewThreads(first:100) and comments(first:100)
# with no pagination. PRs with more than 100 threads (or more than 100 comments
# in any single thread) will silently produce an incomplete inventory. Pagination
# is tracked separately and intentionally deferred.
#
# Inputs:
#   --owner <o>    repository owner
#   --repo  <r>    repository name
#   --pr    <n>    PR number
#
# Outputs:
#   stdout: JSON array of items, each:
#     { kind, thread_id, reply_to_comment_id, issue_comment_id,
#       is_outdated, author, body_excerpt, body_full }
#   exit codes:
#     0 = success
#     1 = gh / network failure
#     2 = bad flag usage
#
# GraphQL projection (review threads):
#   pullRequest.reviewThreads.nodes {
#     id, isResolved, isOutdated,
#     comments(first: 100) { nodes { id, databaseId, author{login}, body } }
#   }
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --owner <o> --repo <r> --pr <n>

Fetches PR review-thread comments + issue comments, emits normalized JSON array on stdout.
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

# Fetch review-thread comments via GraphQL (single page; production callers can paginate).
GRAPHQL_QUERY='query($owner:String!,$repo:String!,$pr:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$pr){reviewThreads(first:100){nodes{id isResolved isOutdated comments(first:100){nodes{id databaseId author{login} body}}}}}}}'

# Capture stderr separately and propagate gh / network failures (do not silently swallow).
GH_ERR="$(mktemp)"
trap 'rm -f "$GH_ERR"' EXIT

if ! THREADS_JSON="$(gh api graphql \
  -F "owner=$OWNER" -F "repo=$REPO" -F "pr=$PR" \
  -f query="$GRAPHQL_QUERY" 2>"$GH_ERR")"; then
  echo "error: gh api graphql failed: $(cat "$GH_ERR")" >&2
  exit 1
fi

# Fetch issue-level comments via REST.
if ! ISSUE_COMMENTS_JSON="$(gh api "repos/$OWNER/$REPO/issues/$PR/comments" 2>"$GH_ERR")"; then
  echo "error: gh api issues comments failed: $(cat "$GH_ERR")" >&2
  exit 1
fi

# Normalize both sources into a single array.
echo "$THREADS_JSON" | jq --argjson issues "$ISSUE_COMMENTS_JSON" '
  def review_items:
    (.data.repository.pullRequest.reviewThreads.nodes // [])
    | map(
        . as $t
        | ($t.comments.nodes // [])
        | map({
            kind: "review_thread",
            thread_id: $t.id,
            reply_to_comment_id: .databaseId,
            issue_comment_id: null,
            is_outdated: ($t.isOutdated // false),
            author: (.author.login // null),
            body_excerpt: ((.body // "") | .[0:200]),
            body_full: (.body // "")
          })
      )
    | flatten;
  def issue_items:
    $issues
    | map({
        kind: "issue_comment",
        thread_id: null,
        reply_to_comment_id: null,
        issue_comment_id: .id,
        is_outdated: false,
        author: (.user.login // null),
        body_excerpt: ((.body // "") | .[0:200]),
        body_full: (.body // "")
      });
  if type != "object" then
    error("unexpected GraphQL response shape (expected object, got \(type))")
  else
    review_items + issue_items
  end
'

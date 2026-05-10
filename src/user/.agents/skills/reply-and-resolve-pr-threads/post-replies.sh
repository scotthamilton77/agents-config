#!/usr/bin/env bash
# Purpose: post a reply to every inventory thread/comment.
#
# Dispatches by `kind`:
#   review_thread → GraphQL addPullRequestReviewThreadReply mutation
#   issue_comment → REST POST /repos/{o}/{r}/issues/{n}/comments
#
# IDEMPOTENCY: this helper is NOT idempotent. If a partial run posted some
# replies and then crashed, the caller MUST pass --skip-comment-ids with the
# csv of already-posted comment_ids on the next invocation.
#
# Inputs:
#   --inventory        <file>  inventory JSON (must contain .items array)
#   --owner            <o>     repository owner
#   --repo             <r>     repository name
#   --pr               <n>     PR number
#   --skip-comment-ids <csv>   (optional) csv of comment_ids to skip
#
# Outputs:
#   stdout: per item, one of:
#     POSTED <comment_id>
#     FAILED <comment_id> <reason>
#     SKIPPED <comment_id> (matched --skip-comment-ids)
#   exit codes:
#     0 = all items posted (or skipped) successfully
#     1 = at least one item failed
#     2 = bad flag usage / missing input
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --inventory <file> --owner <o> --repo <r> --pr <n>
                        [--skip-comment-ids <csv>]

Posts replies to each inventory item; not idempotent — caller must pass
--skip-comment-ids on re-invocation.
EOF
  exit 2
}

INV=""
OWNER=""
REPO=""
PR=""
SKIP_CSV=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --inventory)        INV="${2:-}";      shift 2 ;;
    --owner)            OWNER="${2:-}";    shift 2 ;;
    --repo)             REPO="${2:-}";     shift 2 ;;
    --pr)               PR="${2:-}";       shift 2 ;;
    --skip-comment-ids) SKIP_CSV="${2:-}"; shift 2 ;;
    -h|--help)          usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$INV" ]   || { echo "error: --inventory is required" >&2; exit 2; }
[ -n "$OWNER" ] || { echo "error: --owner is required" >&2; exit 2; }
[ -n "$REPO" ]  || { echo "error: --repo is required" >&2; exit 2; }
[ -n "$PR" ]    || { echo "error: --pr is required" >&2; exit 2; }
[ -f "$INV" ]   || { echo "error: inventory file not found: $INV" >&2; exit 2; }

skipset=""
if [ -n "$SKIP_CSV" ]; then
  skipset=",$SKIP_CSV,"
fi

any_failed=0

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
jq -c '.items[]?' "$INV" > "$TMP"

while IFS= read -r item; do
  [ -n "$item" ] || continue
  cid="$(echo "$item" | jq -r '.comment_id // empty')"
  kind="$(echo "$item" | jq -r '.kind // empty')"
  classification="$(echo "$item" | jq -r '.classification // ""')"

  if [ -n "$cid" ] && [ -n "$skipset" ] && [[ "$skipset" == *",$cid,"* ]]; then
    echo "SKIPPED $cid"
    continue
  fi

  # Only FIX and SKIP classifications get replies via this helper.
  # ESCALATE items are handled separately (escalation notice posted in-model).
  if [ "$classification" != "FIX" ] && [ "$classification" != "SKIP" ]; then
    echo "POSTED $cid (skipped: classification=$classification)"
    continue
  fi

  # reply_body is required — caller (Skill B Phase 2) renders templates.
  body="$(echo "$item" | jq -r '.reply_body // empty')"
  if [ -z "$body" ]; then
    echo "FAILED $cid reply_body_missing"
    any_failed=1
    continue
  fi

  if [ "$kind" = "issue_comment" ]; then
    if gh api "repos/$OWNER/$REPO/issues/$PR/comments" \
      -X POST -f body="$body" >/dev/null 2>&1; then
      echo "POSTED $cid"
    else
      echo "FAILED $cid gh-issue-comment-post-failed"
      any_failed=1
    fi
  else
    # Default: review_thread (or unknown kind treated as such).
    # Use REST replies endpoint: POST /repos/{o}/{r}/pulls/{n}/comments/{reply_to_comment_id}/replies
    reply_to="$(echo "$item" | jq -r '.reply_to_comment_id // empty')"
    if [ -z "$reply_to" ]; then
      echo "FAILED $cid reply_to_comment_id_missing"
      any_failed=1
      continue
    fi
    if gh api "repos/$OWNER/$REPO/pulls/$PR/comments/${reply_to}/replies" \
      --method POST -f body="$body" >/dev/null 2>&1; then
      echo "POSTED $cid"
    else
      echo "FAILED $cid gh-rest-reply-failed"
      any_failed=1
    fi
  fi
done < "$TMP"

[ "$any_failed" -eq 0 ] || exit 1
exit 0

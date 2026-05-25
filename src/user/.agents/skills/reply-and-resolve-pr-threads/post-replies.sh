#!/usr/bin/env bash
# Purpose: post a reply to every inventory thread/comment.
#
# Dispatches by `kind`:
#   review_thread  → REST POST /repos/{o}/{r}/pulls/{n}/comments/{reply_to_comment_id}/replies
#   issue_comment  → REST POST /repos/{o}/{r}/issues/{n}/comments
#   review_summary → REST POST /repos/{o}/{r}/issues/{n}/comments
#                    (review_summary has no per-item id; synthetic cid is
#                     `summary-<12-char sha1 of the item JSON>` so retries
#                     against the same content are idempotent.)
#
# IDEMPOTENCY: this helper is self-recording. Each successful POST is
# appended to a sidecar file <inventory>.posted (one cid per line). On
# startup the sidecar is read and unioned with --skip-comment-ids to form
# the effective skip-set, so crash-recovery re-runs against the same
# inventory will SKIP previously-posted items automatically.
# - On a 100%-success run (any_failed=0) the sidecar is deleted.
# - On a partial-failure run the sidecar is preserved for the next retry.
# - Callers MAY still pass --skip-comment-ids explicitly; both sources
#   union into the same skip-set.
# - The sidecar's lifecycle is bounded by the inventory itself: inventory
#   filenames are keyed by (owner, repo, pr, head_sha) so each new push
#   gets a fresh inventory and a fresh sidecar.
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
#     FAILED <comment_id> <reason> [— <gh-stderr-one-line>]
#     SKIPPED <comment_id> (matched skip-set: sidecar ∪ --skip-comment-ids)
#     FILTERED <comment_id> (classification=<value>) — item is not replyable
#       (e.g., ESCALATE without escalation_filed=true); not an error
#   exit codes:
#     0 = all items posted (or skipped) successfully
#     1 = at least one item failed
#     2 = bad flag usage / missing input
#
# <comment_id> is the canonical id per kind:
#   kind=review_thread  → .reply_to_comment_id  (numeric REST databaseId)
#   kind=issue_comment  → .issue_comment_id     (numeric REST databaseId)
#   kind=review_summary → summary-<12-char sha1 of item JSON> (synthetic; stable)
#   otherwise           → .thread_id // .reply_to_comment_id // .issue_comment_id
# (Inventory items do NOT carry a top-level .comment_id — see
#  build-inventory-body.sh and SKILL.md §"Inventory schema".)
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --inventory <file> --owner <o> --repo <r> --pr <n>
                        [--skip-comment-ids <csv>]

Posts replies to each inventory item. Self-recording: each POSTED cid is
appended to <inventory>.posted; subsequent runs against the same
inventory automatically SKIP previously-posted items. A 100%-success run
deletes the sidecar; partial-failure runs preserve it for retry.
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

POSTED_SIDECAR="${INV}.posted"

skipset=","
if [ -n "$SKIP_CSV" ]; then
  skipset="${skipset}${SKIP_CSV},"
fi
# Union any prior <inventory>.posted entries into the skipset.
if [ -f "$POSTED_SIDECAR" ]; then
  while IFS= read -r prior_cid; do
    [ -n "$prior_cid" ] || continue
    skipset="${skipset}${prior_cid},"
  done < "$POSTED_SIDECAR"
fi
[ "$skipset" = "," ] && skipset=""

any_failed=0

TMP="$(mktemp)"
ERR="$(mktemp)"
trap 'rm -f "$TMP" "$ERR"' EXIT
jq -c '.items[]?' "$INV" > "$TMP"

while IFS= read -r item; do
  [ -n "$item" ] || continue
  kind="$(echo "$item" | jq -r '.kind // empty')"
  classification="$(echo "$item" | jq -r '.classification // ""')"
  # Canonical id dispatch — see header comment for the per-kind contract.
  case "$kind" in
    review_thread)  cid="$(echo "$item" | jq -r '.reply_to_comment_id // empty')" ;;
    issue_comment)  cid="$(echo "$item" | jq -r '.issue_comment_id // empty')" ;;
    review_summary)
      # No per-item id; synthesize one from sha1(item-json) so retries against
      # the same content are idempotent and distinguishable from sibling summaries.
      cid="summary-$(printf '%s' "$item" | shasum -a 1 | cut -d' ' -f1 | cut -c1-12)"
      ;;
    *)              cid="$(echo "$item" | jq -r '.thread_id // .reply_to_comment_id // .issue_comment_id // empty')" ;;
  esac

  if [ -n "$cid" ] && [ -n "$skipset" ] && [[ "$skipset" == *",$cid,"* ]]; then
    echo "SKIPPED $cid"
    continue
  fi

  # Only replyable items proceed: FIX, SKIP, and ESCALATE with escalation_filed=true.
  escalation_filed="$(echo "$item" | jq -r '.escalation_filed // false')"
  if [ "$classification" = "FIX" ] || [ "$classification" = "SKIP" ] || \
     { [ "$classification" = "ESCALATE" ] && [ "$escalation_filed" = "true" ]; }; then
    : # replyable — fall through to reply_body check
  else
    echo "FILTERED $cid (classification=$classification)"
    continue
  fi

  # reply_body is required — caller (Skill B Phase 2) renders templates.
  body="$(echo "$item" | jq -r '.reply_body // empty')"
  if [ -z "$body" ]; then
    echo "FAILED $cid reply_body_missing"
    any_failed=1
    continue
  fi

  # Per-kind POST target. issue_comment + review_summary share the REST
  # issue-comments endpoint (gh pr comment is a wrapper around it). Unknown
  # kinds fall through to the review_thread path (historical behavior).
  case "$kind" in
    issue_comment|review_summary)
      post_url="repos/$OWNER/$REPO/issues/$PR/comments"
      fail_label="gh-issue-comment-post-failed"
      ;;
    *)
      reply_to="$(echo "$item" | jq -r '.reply_to_comment_id // empty')"
      if [ -z "$reply_to" ]; then
        echo "FAILED $cid reply_to_comment_id_missing"
        any_failed=1
        continue
      fi
      # REST endpoint /pulls/<n>/comments/<id>/replies requires the integer
      # databaseId, not the GraphQL node id string.
      if ! [[ "$reply_to" =~ ^[0-9]+$ ]]; then
        echo "FAILED $cid reply_to_comment_id_not_numeric"
        any_failed=1
        continue
      fi
      post_url="repos/$OWNER/$REPO/pulls/$PR/comments/${reply_to}/replies"
      fail_label="gh-rest-reply-failed"
      ;;
  esac

  # The leading printf|gh pipe is load-bearing: it isolates gh's stdin from
  # the outer loop's `< "$TMP"` redirection AND prevents gh's `@<file>` /
  # typed-value parsing from misinterpreting body content (apostrophes,
  # leading @, newlines). $ERR is truncated per attempt and surfaced into
  # the FAILED line so script-internal vs API-rejection failures are
  # distinguishable.
  : > "$ERR"
  if printf '%s' "$body" | gh api "$post_url" \
      --method POST --field body=@- >/dev/null 2>"$ERR"; then
    echo "POSTED $cid"
    [ -n "$cid" ] && printf '%s\n' "$cid" >> "$POSTED_SIDECAR"
  else
    err_msg="$(tr '\n' ' ' <"$ERR" | sed 's/  */ /g; s/^ //; s/ $//')"
    echo "FAILED $cid ${fail_label}${err_msg:+ — $err_msg}"
    any_failed=1
  fi
done < "$TMP"

# 100% success: drop the sidecar so it can't leak into an unrelated run.
# Partial failures preserve it so the next retry inherits the skip-set.
if [ "$any_failed" -eq 0 ] && [ -f "$POSTED_SIDECAR" ]; then
  rm -f "$POSTED_SIDECAR"
fi

[ "$any_failed" -eq 0 ] || exit 1
exit 0

#!/usr/bin/env bash
# Purpose: post a reply to every inventory thread/comment.
#
# Dispatches by `kind`:
#   review_thread  → REST POST /repos/{o}/{r}/pulls/{n}/comments/{reply_to_comment_id}/replies
#   issue_comment  → REST POST /repos/{o}/{r}/issues/{n}/comments
#   review_summary → REST POST /repos/{o}/{r}/issues/{n}/comments
#                    (review_summary has no per-item id; synthetic cid is
#                     `summary-<12-char sha1 of the item JSON, minus any
#                     posted_reply_id>` so retries against the same content
#                     are idempotent — see IDEMPOTENCY note below on why
#                     posted_reply_id must be excluded from the hash.)
#
# IDEMPOTENCY: this helper is self-recording. Each successful POST is
# appended to a sidecar file <inventory>.posted (one cid per line). On
# startup the sidecar is read and unioned with --skip-comment-ids to form
# the effective skip-set, so crash-recovery re-runs against the same
# inventory will SKIP previously-posted items automatically.
# - On a 100%-success run (any_failed=0) AND when --skip-comment-ids was
#   NOT supplied, the sidecar is deleted: the script can prove the sidecar
#   is a complete record of what this inventory needed.
# - On a partial-failure run the sidecar is preserved for the next retry.
# - When --skip-comment-ids was supplied the sidecar is preserved even on
#   any_failed=0: the operator has externally asserted some items are
#   already done, so the script can NOT claim the sidecar is a complete
#   record of what THIS run posted. Deleting it would lose the prior-run
#   POSTED record and let a subsequent retry (without the flag) re-post
#   duplicates.
# - Callers MAY still pass --skip-comment-ids explicitly; both sources
#   union into the same skip-set. The CSV input tolerates whitespace
#   (spaces, tabs, newlines): "11111, 22222" is normalized to "11111,22222"
#   before being spliced into the skipset so the membership check still
#   matches.
# - A sidecar write failure (e.g., unwritable directory, full disk) AFTER
#   a successful GitHub POST is a run failure: the script emits a WARNING
#   on stderr naming the cid and the manual recovery action, sets the
#   failure flag, and exits 1. Without this, the cid would be posted but
#   not persisted, and the next retry would re-post a duplicate.
# - review_summary's cid is a content hash of the item JSON, computed with
#   posted_reply_id EXCLUDED. record_reply_id() mutates the item in-place
#   with posted_reply_id after a successful POST, so on a partial-failure
#   retry the re-read item would otherwise hash to a DIFFERENT cid than the
#   one already written to the sidecar, miss the skip-set, and re-post a
#   duplicate summary — the sidecar entry's whole purpose defeated by the
#   very act of recording success. Excluding the field keeps the hash a
#   function of content only, independent of prior-run bookkeeping.
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
deletes the sidecar UNLESS --skip-comment-ids was supplied (in which
case the operator has externally asserted some items are already done
and the script can't prove the sidecar is complete, so it is preserved);
partial-failure runs preserve the sidecar for retry.
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

# Normalize --skip-comment-ids: strip ALL whitespace so operators or tooling
# passing "11111, 22222" (with spaces/newlines) still match the *,<cid>,*
# skipset membership test. Without this, the whitespace would be glued onto
# the cid in the skipset and silently fail to match, causing duplicate POSTs.
SKIP_CSV="$(printf '%s' "$SKIP_CSV" | tr -d '[:space:]')"

skipset=","
if [ -n "$SKIP_CSV" ]; then
  skipset="${skipset}${SKIP_CSV},"
fi
# Union any prior <inventory>.posted entries into the skipset.
# Defensively strip whitespace per line — we control the writer, but the
# normalization is cheap and symmetric with the CSV handling above.
if [ -f "$POSTED_SIDECAR" ]; then
  while IFS= read -r prior_cid; do
    prior_cid="$(printf '%s' "$prior_cid" | tr -d '[:space:]')"
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

# Record the CREATED reply's id on the matching inventory item — the
# eligibility floor excludes agent replies by exact recorded id, never by
# author login (the agent commonly posts through its human operator's own
# GitHub account, so a login filter would hide that human's real comments).
record_reply_id() {  # record_reply_id <item-key> <match-value> <reply-id>
  local key="$1" val="$2" rid="$3" tmp_inv
  tmp_inv="$(mktemp)"
  if jq --arg k "$key" --arg v "$val" --argjson rid "$rid" \
       '.items |= map(if ((.[$k] // "") | tostring) == $v then . + {posted_reply_id: $rid} else . end)' \
       "$INV" > "$tmp_inv" && mv "$tmp_inv" "$INV"; then
    :
  else
    rm -f "$tmp_inv"
    echo "WARNING $val reply-id-record-failed: reply $rid posted to GitHub but not recorded in $INV; the eligibility check will treat it as incoming feedback until triaged" >&2
  fi
}

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
      # Canonicalize with `jq -c --sort-keys` so the cid depends only on content,
      # not on jq's emitted key order (otherwise two semantically identical
      # items could hash differently and break idempotency). `-c` (compact
      # output) is REQUIRED for cross-version/platform stability: jq's
      # pretty-print whitespace and indentation can shift across jq versions,
      # which would change the hash bytes and break idempotency across
      # environments. Compact form is deterministic.
      # `del(.posted_reply_id)` is REQUIRED: that field is written onto the
      # item by record_reply_id() AFTER a successful POST, so a retry's
      # re-read of the item must hash identically to the pre-POST read or
      # the cid drifts off the sidecar's recorded value — see IDEMPOTENCY
      # note in the file header.
      cid="summary-$(printf '%s' "$item" | jq -c --sort-keys 'del(.posted_reply_id)' | shasum -a 1 | cut -d' ' -f1 | cut -c1-12)"
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
  if resp="$(printf '%s' "$body" | gh api "$post_url" \
      --method POST --field body=@- 2>"$ERR")"; then
    echo "POSTED $cid"
    # Sidecar recording is part of the idempotency contract. The append CANNOT
    # be expressed as `&& printf ... >> $POSTED_SIDECAR`: under `set -e`, a
    # failed `>>` inside an `&&`-list is NOT treated as a fatal error, so the
    # write loss would be silent — the cid would be POSTED to GitHub but never
    # persisted, and a crash-recovery retry would re-post a duplicate. The
    # GitHub-side and sidecar-side state are already divergent at this point;
    # surface it loudly and fail the run so the operator can manually append
    # the cid before retrying.
    if [ -n "$cid" ]; then
      if ! printf '%s\n' "$cid" >> "$POSTED_SIDECAR"; then
        echo "WARNING $cid sidecar-append-failed: posted to GitHub but $POSTED_SIDECAR write failed; manually append $cid to that file before retrying or the next run will re-post a duplicate" >&2
        any_failed=1
      fi
    fi
    reply_id="$(printf '%s' "$resp" | jq -r '.id // empty' 2>/dev/null)"
    if [ -n "$reply_id" ]; then
      case "$kind" in
        issue_comment)  record_reply_id issue_comment_id "$cid" "$reply_id" ;;
        review_summary)
          rsid="$(echo "$item" | jq -r '.review_id // empty')"
          if [ -n "$rsid" ]; then
            record_reply_id review_id "$rsid" "$reply_id"
          else
            echo "WARNING $cid reply-id-not-recorded: legacy review_summary item lacks review_id" >&2
          fi
          ;;
        *)              record_reply_id reply_to_comment_id "$reply_to" "$reply_id" ;;
      esac
    else
      echo "WARNING $cid reply-id-not-recorded: API response carried no .id" >&2
    fi
  else
    err_msg="$(tr '\n' ' ' <"$ERR" | sed 's/  */ /g; s/^ //; s/ $//')"
    echo "FAILED $cid ${fail_label}${err_msg:+ — $err_msg}"
    any_failed=1
  fi
done < "$TMP"

# 100% success: drop the sidecar so it can't leak into an unrelated run.
# Partial failures preserve it so the next retry inherits the skip-set.
# When --skip-comment-ids was supplied we preserve it too: the operator has
# externally asserted that some items are already done, so we can't confidently
# claim the sidecar is a complete record of what THIS run handled. Deleting
# it would lose the prior-run POSTED record and let a subsequent retry
# (without the flag) re-post duplicates.
if [ "$any_failed" -eq 0 ] && [ -z "$SKIP_CSV" ] && [ -f "$POSTED_SIDECAR" ]; then
  rm -f "$POSTED_SIDECAR"
fi

[ "$any_failed" -eq 0 ] || exit 1
exit 0

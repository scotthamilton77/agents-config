#!/usr/bin/env bash
# Purpose: render reply_body for every replyable inventory item using the
# pinned reply-text template matrix from reply-and-resolve-pr-threads SKILL.md.
#
# This is the single owner of the reply template matrix. It reads an inventory
# JSON file, populates .reply_body on every replyable item, and writes the
# resulting inventory JSON to the output path. Items that are not replyable
# (e.g., ESCALATE without escalation_filed=true, unknown classifications) are
# passed through unchanged with no reply_body set.
#
# Inputs:
#   --inventory <file>  inventory JSON path (must contain .items array)
#   --out       <file>  output path for inventory-with-reply_body
#
# Outputs:
#   <out-file>: same inventory JSON with .reply_body populated on replyable items
#   exit codes:
#     0 = success
#     1 = render error (e.g., FIX-committed item missing required field)
#     2 = bad flag usage / missing input
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --inventory <file> --out <file>

Renders reply_body for every replyable inventory item using the pinned
reply template matrix. Emits inventory JSON with .reply_body populated.

Exit codes:
  0 = success
  1 = render error (missing required field on a replyable item)
  2 = bad flag usage / missing input
EOF
  exit 2
}

INV=""
OUT=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --inventory) INV="${2:-}"; shift 2 ;;
    --out)       OUT="${2:-}"; shift 2 ;;
    -h|--help)   usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$INV" ] || { echo "error: --inventory is required" >&2; exit 2; }
[ -n "$OUT" ] || { echo "error: --out is required" >&2; exit 2; }
[ -f "$INV" ] || { echo "error: inventory file not found: $INV" >&2; exit 2; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

# Walk items and validate that FIX-committed items have required fields
# before we attempt rendering. Defense in depth: validate-inventory.sh
# catches most of this, but render-reply-bodies is the template owner.
any_error=0

while IFS= read -r item; do
  [ -n "$item" ] || continue
  cid="$(echo "$item" | jq -r '.comment_id // "<?>"')"
  classification="$(echo "$item" | jq -r '.classification // ""')"
  fix_outcome="$(echo "$item" | jq -r '.fix_outcome // ""')"

  if [ "$classification" = "FIX" ] && [ "$fix_outcome" = "committed" ]; then
    sha="$(echo "$item" | jq -r '.fix_commit_sha // ""')"
    summary="$(echo "$item" | jq -r '.fix_summary // ""')"
    dup="$(echo "$item" | jq -r '.duplicate_of // ""')"
    # duplicate_of path doesn't need sha+summary in the rendered output,
    # but the item still needs duplicate_of to be non-empty.
    if [ -z "$dup" ]; then
      [ -n "$sha" ] || { echo "error: FIX-committed item $cid missing fix_commit_sha" >&2; any_error=1; }
      [ -n "$summary" ] || { echo "error: FIX-committed item $cid missing fix_summary" >&2; any_error=1; }
    fi
  fi
done < <(jq -c '.items[]?' "$INV")

[ "$any_error" -eq 0 ] || exit 1

# Render reply_body for each item via jq.
# Template matrix (from SKILL.md §Reply text templates):
#   FIX + committed + duplicate_of non-null  → "Fixed via the change addressing <duplicate_of>."
#   FIX + committed                          → "Fixed in <fix_commit_sha>. <fix_summary>"
#   FIX + already_addressed                  → "Already addressed in <fix_commit_sha>."
#   SKIP                                     → "<rationale>"
#   ESCALATE + escalation_filed=true + rationale=="exceeded re-review round cap"
#                                            → "Round limit reached on this PR; deferring further iterations to a human reviewer."
#   ESCALATE + escalation_filed=true (other) → "Captured for follow-up; will respond on a later push to this PR or in a related issue."
#   ESCALATE + escalation_filed != true      → (no reply_body set)
#   anything else                            → (no reply_body set)

jq '
  .items = [
    .items[]? |
    if .classification == "FIX" then
      if .fix_outcome == "committed" then
        if (.duplicate_of // "") != "" then
          . + {reply_body: ("Fixed via the change addressing " + .duplicate_of + ".")}
        else
          . + {reply_body: ("Fixed in " + .fix_commit_sha + ". " + .fix_summary)}
        end
      elif .fix_outcome == "already_addressed" then
        . + {reply_body: ("Already addressed in " + .fix_commit_sha + ".")}
      else
        .
      end
    elif .classification == "SKIP" then
      . + {reply_body: .rationale}
    elif .classification == "ESCALATE" and .escalation_filed == true then
      if .rationale == "exceeded re-review round cap" then
        . + {reply_body: "Round limit reached on this PR; deferring further iterations to a human reviewer."}
      else
        . + {reply_body: "Captured for follow-up; will respond on a later push to this PR or in a related issue."}
      end
    else
      .
    end
  ]
' "$INV" > "$TMP"

cp "$TMP" "$OUT"
exit 0

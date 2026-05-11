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

TMP_OUT="$(mktemp)"
TMP_ERR="$(mktemp)"
trap 'rm -f "$TMP_OUT" "$TMP_ERR"' EXIT

# Render reply_body for each item via a single jq invocation. Validation is
# co-located with rendering via jq's `error()` so a malformed replyable item
# fails the whole render with a clear diagnostic — no silent pass-through and
# no second pass that could disagree with the first.
#
# Template matrix (from SKILL.md §Reply text templates — this helper is the
# single owner of the matrix):
#   FIX + committed + duplicate_of non-null  → "Fixed via the change addressing <duplicate_of>."
#   FIX + committed                          → "Fixed in <fix_commit_sha>. <fix_summary>"
#   FIX + already_addressed                  → "Already addressed in <fix_commit_sha>."
#   SKIP                                     → "<rationale>"
#   ESCALATE + escalation_filed=true + rationale=="exceeded re-review round cap"
#                                            → "Round limit reached on this PR; deferring further iterations to a human reviewer."
#   ESCALATE + escalation_filed=true (other) → "Captured for follow-up; will respond on a later push to this PR or in a related issue."
#   ESCALATE + escalation_filed != true      → (no reply_body set)
#   anything else                            → (no reply_body set)
#
# Recovery DEFER/ABANDON templates from SKILL.md are NOT rendered here:
# Phase 1.5 recovery triage in `--resume` mode reclassifies ABANDON items to
# SKIP and stamps DEFER items with a tracking_link; by the time this helper
# runs, those items look like ordinary SKIPs to the matrix above.

if ! jq '
  .items = [
    .items[]? |
    if .classification == "FIX" then
      if .fix_outcome == "committed" then
        if (.duplicate_of // "") != "" then
          . + {reply_body: ("Fixed via the change addressing " + .duplicate_of + ".")}
        elif (.fix_commit_sha // "") == "" then
          error("FIX-committed item \(.comment_id // "<?>") missing fix_commit_sha")
        elif (.fix_summary // "") == "" then
          error("FIX-committed item \(.comment_id // "<?>") missing fix_summary")
        else
          . + {reply_body: ("Fixed in " + .fix_commit_sha + ". " + .fix_summary)}
        end
      elif .fix_outcome == "already_addressed" then
        if (.fix_commit_sha // "") == "" then
          error("FIX-already_addressed item \(.comment_id // "<?>") missing fix_commit_sha")
        else
          . + {reply_body: ("Already addressed in " + .fix_commit_sha + ".")}
        end
      else
        .
      end
    elif .classification == "SKIP" then
      if (.rationale // "") == "" then
        error("SKIP item \(.comment_id // "<?>") missing rationale")
      else
        . + {reply_body: .rationale}
      end
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
' "$INV" > "$TMP_OUT" 2> "$TMP_ERR"; then
  cat "$TMP_ERR" >&2
  exit 1
fi

mv "$TMP_OUT" "$OUT"
exit 0

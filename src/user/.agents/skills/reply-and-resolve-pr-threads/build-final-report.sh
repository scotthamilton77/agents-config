#!/usr/bin/env bash
# Purpose: render the operator-facing markdown summary of a completed
# reply-and-resolve run.
#
# Inputs:
#   --inventory <file>  inventory JSON (must contain .items array)
#
# Outputs:
#   stdout: markdown report. Includes the comment_id of every inventory item.
#   exit codes:
#     0 = success
#     2 = bad flag usage / missing input file
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --inventory <file>

Renders the final operator-facing markdown report for a reply-and-resolve run.
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

PR_NUM="$(jq -r '.pr.number // "?"' "$INV")"
OWNER="$(jq -r '.pr.owner // "?"' "$INV")"
REPO="$(jq -r '.pr.repo // "?"' "$INV")"
TOTAL="$(jq -r '(.items // []) | length' "$INV")"
FIX_COUNT="$(jq -r '[(.items // [])[] | select((.classification // "") == "FIX")] | length' "$INV")"

echo "# PR Review Reply & Resolve Report"
echo
echo "**PR:** $OWNER/$REPO#$PR_NUM"
echo "**Total items:** $TOTAL"
echo "**FIX items:** $FIX_COUNT"
echo
echo "## Items"
echo

jq -r '
  (.items // [])[]
  | "- **\(.comment_id // "?"):** \(.classification // "?") / \(.fix_outcome // "n/a")"
' "$INV"

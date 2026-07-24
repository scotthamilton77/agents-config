#!/usr/bin/env bash
# Purpose: assemble the canonical inventory JSON body from items, pr metadata,
# and polling metadata. This is the single owner of the inventory schema —
# all phases of `wait-for-pr-comments` invoke this script instead of inlining
# the jq pipeline.
#
# Inputs:
#   --items   <file>  JSON file: array of inventory items
#   --pr      <file>  JSON file: PR metadata object (number, owner, repo, head_sha, ...)
#   --polling <file>  JSON file: polling metadata object (started_at, duration_s, ...)
#
# Outputs:
#   stdout: JSON {schema_version: 1, pr: <obj>, polling: <obj>, items: <array>}
#   exit codes:
#     0 = success
#     2 = bad flag usage / missing input file
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --items <file> --pr <file> --polling <file>

Assembles inventory JSON body. Emits to stdout.
EOF
  exit 2
}

ITEMS=""
PR=""
POLLING=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --items)   ITEMS="${2:-}";   shift 2 ;;
    --pr)      PR="${2:-}";      shift 2 ;;
    --polling) POLLING="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$ITEMS" ]   || { echo "error: --items is required" >&2; exit 2; }
[ -n "$PR" ]      || { echo "error: --pr is required" >&2; exit 2; }
[ -n "$POLLING" ] || { echo "error: --polling is required" >&2; exit 2; }
[ -f "$ITEMS" ]   || { echo "error: items file not found: $ITEMS" >&2; exit 2; }
[ -f "$PR" ]      || { echo "error: pr file not found: $PR" >&2; exit 2; }
[ -f "$POLLING" ] || { echo "error: polling file not found: $POLLING" >&2; exit 2; }

jq -n \
  --slurpfile items   "$ITEMS" \
  --slurpfile pr      "$PR" \
  --slurpfile polling "$POLLING" \
  '{schema_version: 1, pr: $pr[0], polling: $polling[0], items: $items[0]}'

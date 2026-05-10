#!/usr/bin/env bash
# Purpose: probe each inventory item's fix_sha for ancestry on the given branch.
# Items whose fix_sha is an ancestor of the branch tip go in `present`;
# items missing or not ancestors go in `missing`.
#
# Inputs:
#   --branch <ref>   branch (or ref) to probe against (e.g., the PR's head branch)
#   --items  <file>  JSON file: inventory items array (each may have fix_sha and comment_id)
#
# Outputs:
#   stdout: JSON {present: [{comment_id, fix_sha, ...}], missing: [...]}
#   exit codes:
#     0 = probe completed (regardless of present/missing split)
#     2 = bad flag usage / missing input file
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --branch <ref> --items <file>

Probes each item's fix_sha for ancestry on <ref>; emits {present, missing} JSON.
EOF
  exit 2
}

BRANCH=""
ITEMS=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --branch) BRANCH="${2:-}"; shift 2 ;;
    --items)  ITEMS="${2:-}";  shift 2 ;;
    -h|--help) usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$BRANCH" ] || { echo "error: --branch is required" >&2; exit 2; }
[ -n "$ITEMS" ]  || { echo "error: --items is required" >&2; exit 2; }
[ -f "$ITEMS" ]  || { echo "error: items file not found: $ITEMS" >&2; exit 2; }

# Per item: classify as present/missing.
PRESENT="[]"
MISSING="[]"

# Use a temp file to capture iteration output (avoids subshell variable scope).
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

jq -c '.[]?' "$ITEMS" > "$TMP"

while IFS= read -r item; do
  [ -n "$item" ] || continue
  fix_sha="$(echo "$item" | jq -r '.fix_sha // empty')"
  if [ -n "$fix_sha" ] && git merge-base --is-ancestor "$fix_sha" "$BRANCH" 2>/dev/null; then
    PRESENT="$(jq -nc --argjson a "$PRESENT" --argjson i "$item" '$a + [$i]')"
  else
    MISSING="$(jq -nc --argjson a "$MISSING" --argjson i "$item" '$a + [$i]')"
  fi
done < "$TMP"

jq -nc --argjson p "$PRESENT" --argjson m "$MISSING" '{present: $p, missing: $m}'

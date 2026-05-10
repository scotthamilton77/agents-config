#!/usr/bin/env bash
# Purpose: verify the PR's current head SHA matches an expected value.
# Retries up to 2 times with a 5s delay on mismatch (covers GitHub eventual
# consistency after a push).
#
# Inputs:
#   --owner        <o>    repository owner
#   --repo         <r>    repository name
#   --pr           <n>    PR number
#   --expected-sha <sha>  expected head SHA
#
# Outputs:
#   stdout: (none on success)
#   exit codes:
#     0 = head SHA matches
#     1 = persistent mismatch / gh failure
#     2 = bad flag usage
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --owner <o> --repo <r> --pr <n> --expected-sha <sha>

Verifies PR head SHA matches expected. Retries up to 2 times.
EOF
  exit 2
}

OWNER=""
REPO=""
PR=""
EXPECTED=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --owner)        OWNER="${2:-}";    shift 2 ;;
    --repo)         REPO="${2:-}";     shift 2 ;;
    --pr)           PR="${2:-}";       shift 2 ;;
    --expected-sha) EXPECTED="${2:-}"; shift 2 ;;
    -h|--help)      usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$OWNER" ] && [ -n "$REPO" ] && [ -n "$PR" ] && [ -n "$EXPECTED" ] || {
  echo "error: --owner, --repo, --pr, --expected-sha are all required" >&2
  exit 2
}

GH_ERR="$(mktemp)"
trap 'rm -f "$GH_ERR"' EXIT

ACTUAL=""
attempt=0
while [ "$attempt" -lt 3 ]; do
  # Distinguish a successful gh call (where SHA might legitimately mismatch and
  # we should retry for eventual consistency) from a failed gh call (auth /
  # network / 5xx) where we should fail fast instead of looping.
  if RESPONSE="$(gh api "repos/$OWNER/$REPO/pulls/$PR" 2>"$GH_ERR")"; then
    ACTUAL="$(echo "$RESPONSE" | jq -r '.headRefOid // .head.sha // empty' 2>/dev/null || true)"
    if [ -n "$ACTUAL" ] && [ "$ACTUAL" = "$EXPECTED" ]; then
      exit 0
    fi
  else
    echo "error: gh api failed for repos/$OWNER/$REPO/pulls/$PR: $(cat "$GH_ERR")" >&2
    exit 1
  fi

  attempt=$((attempt + 1))
  if [ "$attempt" -lt 3 ]; then
    sleep 5
  fi
done

echo "error: PR $OWNER/$REPO#$PR head SHA is '$ACTUAL', expected '$EXPECTED'" >&2
exit 1

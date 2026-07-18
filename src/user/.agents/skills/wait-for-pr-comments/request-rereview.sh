#!/usr/bin/env bash
# Purpose: request a re-review from one or more trusted PR bot reviewers,
# dispatching on reviewer identity — each bot's ask mechanism differs:
#
#   Identity                              Mechanism
#   -------------------------------------  ------------------------------------
#   Copilot,                               remove+re-add reviewer dance. The
#   copilot-pull-request-reviewer[bot]     `gh pr edit --remove-reviewer
#                                           @copilot && sleep && gh pr edit
#                                           --add-reviewer @copilot` pattern
#                                           reliably triggers a new review
#                                           event even when @copilot is already
#                                           listed. Copilot does not respond to
#                                           an issue comment.
#   chatgpt-codex-connector[bot] (Codex)   post an `@codex review` issue
#                                           comment. Codex does not respond to
#                                           reviewer-request events at all.
#
# An identity with no known mechanism warns to stderr and is skipped without
# aborting dispatch to its siblings.
#
# Inputs:
#   --owner <o>              repository owner
#   --repo  <r>              repository name
#   --pr    <n>              PR number
#   --bot-reviewers <json>   JSON array of reviewer identities to dispatch to
#                            (non-empty array of strings; identity matched
#                            case-insensitively, mirroring
#                            poll-copilot-review.sh's convention). Omit to
#                            preserve the legacy Copilot-only dance
#                            (backward-compatible default, not how the
#                            wait-for-pr-comments/merge-guard loops run).
#
# Outputs:
#   stdout: (none on success)
#   exit codes:
#     0 = at least one ask succeeded
#     1 = no ask succeeded (gh failure on every dispatched identity)
#     2 = bad flag usage
#
# GraphQL projection: none directly; uses `gh pr edit` / `gh pr comment` REST
# under the hood.
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --owner <o> --repo <r> --pr <n> [--bot-reviewers <json-array>]

Requests a re-review from one or more trusted bot reviewers, dispatching on
identity: Copilot / copilot-pull-request-reviewer[bot] get the remove+re-add
reviewer dance; chatgpt-codex-connector[bot] gets an '@codex review' issue
comment. Omit --bot-reviewers to request only Copilot (legacy default).
EOF
  exit 2
}

OWNER=""
REPO=""
PR=""
BOT_REVIEWERS=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --owner)         OWNER="${2:-}";         shift 2 ;;
    --repo)          REPO="${2:-}";          shift 2 ;;
    --pr)            PR="${2:-}";            shift 2 ;;
    --bot-reviewers) BOT_REVIEWERS="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$OWNER" ] && [ -n "$REPO" ] && [ -n "$PR" ] || {
  echo "error: --owner, --repo, --pr are all required" >&2
  exit 2
}

# Validate --bot-reviewers (when provided) as a non-empty JSON array of
# strings — same convention as poll-copilot-review.sh — then canonicalize via
# jq so only clean, re-serialized JSON is read below.
if [ -n "$BOT_REVIEWERS" ]; then
  BOT_REVIEWERS=$(jq -ce 'if (type == "array" and length > 0 and ([.[] | select(type != "string")] | length) == 0) then . else error("bad") end' <<<"$BOT_REVIEWERS" 2>/dev/null) || {
    echo "error: --bot-reviewers must be a non-empty JSON array of strings" >&2
    exit 2
  }
fi

PR_REF="$OWNER/$REPO#$PR"

GH_ERR="$(mktemp)"
trap 'rm -f "$GH_ERR"' EXIT

# request_copilot — remove+re-add @copilot to trigger a fresh review event.
request_copilot() {
  # Remove @copilot — tolerate "not currently a reviewer" (a common no-op error).
  gh pr edit "$PR" --repo "$OWNER/$REPO" --remove-reviewer @copilot >/dev/null 2>"$GH_ERR" || true

  sleep 2

  # Add @copilot — capture stderr so callers (and operators debugging auth /
  # permission / rate-limit / invalid-PR failures) see the underlying gh message,
  # not just a generic exit code.
  if ! gh pr edit "$PR" --repo "$OWNER/$REPO" --add-reviewer @copilot >/dev/null 2>"$GH_ERR"; then
    echo "error: gh pr edit --add-reviewer failed for $PR_REF: $(cat "$GH_ERR")" >&2
    return 1
  fi
}

# request_codex — post an '@codex review' issue comment. Codex reviews on
# push, mark-draft-ready, and this comment, but not on a reviewer-request
# event, so this is its only ask mechanism.
request_codex() {
  if ! gh pr comment "$PR" --repo "$OWNER/$REPO" --body "@codex review" >/dev/null 2>"$GH_ERR"; then
    echo "error: gh pr comment '@codex review' failed for $PR_REF: $(cat "$GH_ERR")" >&2
    return 1
  fi
}

if [ -z "$BOT_REVIEWERS" ]; then
  # Backward-compatible default: the legacy Copilot-only dance.
  if request_copilot; then
    exit 0
  fi
  exit 1
fi

SUCCEEDED=0
while IFS= read -r identity; do
  lower=$(printf '%s' "$identity" | tr '[:upper:]' '[:lower:]')
  case "$lower" in
    copilot|"copilot-pull-request-reviewer[bot]")
      if request_copilot; then SUCCEEDED=$((SUCCEEDED + 1)); fi
      ;;
    "chatgpt-codex-connector[bot]")
      if request_codex; then SUCCEEDED=$((SUCCEEDED + 1)); fi
      ;;
    *)
      echo "warning: no known re-review mechanism for reviewer identity '$identity' — skipping" >&2
      ;;
  esac
done < <(jq -r '.[]' <<<"$BOT_REVIEWERS")

[ "$SUCCEEDED" -gt 0 ] && exit 0
exit 1

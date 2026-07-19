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
#   --disposition-table <json>
#                            Do-not-relitigate context for the Codex ask ONLY
#                            (Copilot is unaffected, gets neither this nor
#                            --since-sha). Non-empty JSON array of objects:
#                            {finding, classification: FIX|SKIP|REBUT, detail}
#                            — detail is the fixing commit SHA for FIX, a
#                            rationale for SKIP/REBUT. Renders as a markdown
#                            table in the '@codex review' comment instead of
#                            the bare string, so Codex does not re-raise
#                            settled findings next round (confirmed PR #317,
#                            #331 — bare re-ask re-cites SKIP/fixed items;
#                            a disposition table does not, and can carry a
#                            REBUT Codex accepts instead of re-flagging).
#   --since-sha <sha>        Optional. Codex-only: appends a "focus on
#                            commits since <sha>" line to the comment body.
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
Usage: $(basename "$0") --owner <o> --repo <r> --pr <n> [--bot-reviewers <json-array>] [--disposition-table <json-array>] [--since-sha <sha>]

Requests a re-review from one or more trusted bot reviewers, dispatching on
identity: Copilot / copilot-pull-request-reviewer[bot] get the remove+re-add
reviewer dance; chatgpt-codex-connector[bot] gets an '@codex review' issue
comment. Omit --bot-reviewers to request only Copilot (legacy default).
--disposition-table and --since-sha add do-not-relitigate context to the
Codex ask only; they have no effect on the Copilot mechanism.
EOF
  exit 2
}

OWNER=""
REPO=""
PR=""
BOT_REVIEWERS=""
DISPOSITION_TABLE=""
SINCE_SHA=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --owner)              OWNER="${2:-}";              shift 2 ;;
    --repo)               REPO="${2:-}";                shift 2 ;;
    --pr)                 PR="${2:-}";                  shift 2 ;;
    --bot-reviewers)      BOT_REVIEWERS="${2:-}";       shift 2 ;;
    --disposition-table)  DISPOSITION_TABLE="${2:-}";   shift 2 ;;
    --since-sha)          SINCE_SHA="${2:-}";            shift 2 ;;
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

# Validate --disposition-table (when provided) as a non-empty JSON array of
# objects, each with a "finding" string, a "classification" of FIX/SKIP/REBUT,
# and a "detail" string (commit SHA for FIX, rationale for SKIP/REBUT) — same
# fail-closed convention as --bot-reviewers, then canonicalize via jq.
if [ -n "$DISPOSITION_TABLE" ]; then
  DISPOSITION_TABLE=$(jq -ce '
    if (type == "array" and length > 0 and
        ([.[] | select(
          (type == "object") and
          (has("finding") and (.finding | type) == "string") and
          (has("classification") and (.classification as $c | ["FIX","SKIP","REBUT"] | index($c) != null)) and
          (has("detail") and (.detail | type) == "string")
          | not
        )] | length) == 0)
    then . else error("bad") end
  ' <<<"$DISPOSITION_TABLE" 2>/dev/null) || {
    echo "error: --disposition-table must be a non-empty JSON array of objects, each with a string 'finding', a 'classification' of FIX/SKIP/REBUT, and a string 'detail' (commit SHA for FIX, rationale for SKIP/REBUT)" >&2
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

# build_codex_comment_body — bare '@codex review' by default; when
# --disposition-table and/or --since-sha are supplied, renders them as a
# structured markdown table + focus line instead. This do-not-relitigate
# context is Codex-only — request_copilot never sees it.
build_codex_comment_body() {
  if [ -z "$DISPOSITION_TABLE" ] && [ -z "$SINCE_SHA" ]; then
    echo "@codex review"
    return
  fi

  echo "@codex review"
  echo

  if [ -n "$DISPOSITION_TABLE" ]; then
    echo "Prior-round findings — do not re-raise FIX/SKIP/REBUT items below:"
    echo
    echo "| Finding | Classification | Commit / Rationale |"
    echo "| --- | --- | --- |"
    jq -r '.[] | "| " + .finding + " | " + .classification + " | " + .detail + " |"' <<<"$DISPOSITION_TABLE"
    echo
  fi

  if [ -n "$SINCE_SHA" ]; then
    echo "Focus on commits since $SINCE_SHA."
  fi
}

# request_codex — post an '@codex review' issue comment. Codex reviews on
# push, mark-draft-ready, and this comment, but not on a reviewer-request
# event, so this is its only ask mechanism.
request_codex() {
  local body
  body="$(build_codex_comment_body)"
  if ! gh pr comment "$PR" --repo "$OWNER/$REPO" --body "$body" >/dev/null 2>"$GH_ERR"; then
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
# Track mechanisms already dispatched this invocation. Multiple aliases can map
# to the same mechanism (e.g. both `Copilot` and
# `copilot-pull-request-reviewer[bot]` -> the reviewer dance); dispatching each
# mechanism at most once avoids a redundant remove+re-add cycle per alias.
DISPATCHED=""
while IFS= read -r identity; do
  lower=$(printf '%s' "$identity" | tr '[:upper:]' '[:lower:]')
  case "$lower" in
    copilot|"copilot-pull-request-reviewer[bot]") mechanism=copilot ;;
    "chatgpt-codex-connector[bot]")               mechanism=codex ;;
    *)
      echo "warning: no known re-review mechanism for reviewer identity '$identity' — skipping" >&2
      continue
      ;;
  esac

  # Skip mechanisms already asked this invocation (alias dedup).
  case " $DISPATCHED " in
    *" $mechanism "*) continue ;;
  esac
  DISPATCHED="$DISPATCHED $mechanism"

  case "$mechanism" in
    copilot) if request_copilot; then SUCCEEDED=$((SUCCEEDED + 1)); fi ;;
    codex)   if request_codex;   then SUCCEEDED=$((SUCCEEDED + 1)); fi ;;
  esac
done < <(jq -r '.[]' <<<"$BOT_REVIEWERS")

[ "$SUCCEEDED" -gt 0 ] && exit 0
exit 1
